"""Versioned review with independently validated modules and explicit partial failure."""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from typing import Literal
from pydantic import Field
from .models import Model
from . import structured_review as legacy
from .structured_review import Sources,extract_call
from .fact_grounding import GroundedFacts,GROUNDING_PROMPT,validate_calculation
from .assignment_review import AssignmentFacts,ASSIGNMENT_PROMPT,validate_assignment,assignment_payload
from .liability_review import LiabilityFacts,LiabilityEvent,LIABILITY_PROMPT,validate_liability,liability_candidate_payload,liability_batches
from .amount_review import classify as classify_amount
from .field_review import classify as classify_field
from .reference_index import index_references
from .review_issues import build_review_issues,summarize_rule_status
from .attachment_review import AttachmentResults,ATTACHMENT_PROMPT,index_attachment_contents,evaluate_attachment_references
from .interactive_review import reference_candidates,model_source_payload
from .llm import ExtractionError
from .rule_registry import BASE_IDS


class BasicFinding(Model):
    rule_id:Literal['RL-01','RL-04']
    status:Literal['flag','no_flag_for_target_rule','insufficient_evidence','not_applicable']
    explanation:str=Field(min_length=1,max_length=1000)
    refs:list[str]=Field(max_length=50)
class BasicResults(Model):
    findings:list[BasicFinding]=Field(min_length=2,max_length=2)
class AccurateSchema(Model):
    facts:GroundedFacts
    assignment:AssignmentFacts
    basic:BasicResults
    liability:LiabilityFacts
    attachments:AttachmentResults

BASIC_PROMPT='\n'.join(line for line in legacy.OTHER_PROMPT.splitlines() if not line.startswith('RL-03')) .replace('RL-01、RL-03、RL-04','RL-01、RL-04')
FACT_PROMPT=legacy.INDEXED_FACT_PROMPT+GROUNDING_PROMPT+'''\n正文和已读材料一起检查金额和字段。附件只从main_document明确引用抽取；materials仅为收到的文件目录。用户说明不是合同事实。已匹配的实际材料优先于正文旧有未提供字样。'''
VERSION_PROMPT='\n---\n'.join([FACT_PROMPT,BASIC_PROMPT,ASSIGNMENT_PROMPT,LIABILITY_PROMPT,ATTACHMENT_PROMPT])


def implementation_hash():
    from pathlib import Path
    names=('accurate_review.py','fact_grounding.py','assignment_review.py','liability_review.py','rule_registry.py','review_issues.py','reference_index.py','amount_review.py','field_review.py','structured_review.py','interactive_review.py','attachment_review.py')
    root=Path(__file__).parent
    return sha256(b''.join((root/n).read_bytes() for n in names)).hexdigest()


def review_accurate(settings,model,blocks,context,rules,*,bundle=None,policy_version='review-liability-v1',progress_callback=None,retain_non_amount_facts=False,execution_callback=None):
    started=time.monotonic();deadline=started+min(120,settings.timeout)
    all_blocks=list(blocks);materials=(bundle or {}).get('materials',[])
    for m in materials:
        if m.get('parse_status') not in ('failed','unsupported'):all_blocks.extend(m.get('blocks',[]))
    if len({b['id'] for b in all_blocks})!=len(all_blocks):raise legacy.fail('duplicate_source_block_id')
    sources=Sources(all_blocks);main_sources=Sources(blocks);main_refs=set(main_sources.blocks)
    seeds,aliases=reference_candidates(main_sources)
    _,plans=index_references(sources,legacy.grounded_role,legacy.TECH,legacy.PRICE)
    public=[b if retain_non_amount_facts else b|{'origin':'main_document' if b['id'] in main_refs else 'material'} for b in sources.public]
    payload={'blocks':public,'context':context,
             'main_document_refs':sorted(main_refs) if retain_non_amount_facts else [],
             'document_parse_status':(bundle or {}).get('document_parse_status','parsed'),
             'document_contains_unreadable_images':bool((bundle or {}).get('document_image_block_ids')),
             'materials':[{k:m.get(k) for k in ('id','filename','parse_status')} for m in materials]}
    trace=[];errors=[];records=[];issues=[];checks=[];raw_extractions={};batch_coverage=[]
    if progress_callback:progress_callback('extracting')
    def call(name,prompt,schema,content,validate):
        titles={'facts':'提取金额、附件和关键字段','basic':'核查合同基础规则','assignment':'核查合同转让条款','attachments':'核验附件材料','liability':'核查责任条款'}
        if execution_callback:
            execution_callback('task_discovered',task_id='base:'+name,title=titles.get(name,name))
            execution_callback('task_started',task_id='base:'+name)
        result=call_inner(name,prompt,schema,content,validate)
        if execution_callback:
            execution_callback('task_failed' if result[1] else 'task_completed',task_id='base:'+name,message=result[1]['message'] if result[1] else '')
        return result
    def call_inner(name,prompt,schema,content,validate):
        attempts=[]
        try:
            def record_and_validate(value):
                raw_extractions.setdefault(name,[]).append(value.model_dump(mode='json'))
                return validate(value)
            if name=='liability':
                batches=liability_batches(content)
                if len(batches)>1:
                    events=[]
                    for index,batch in enumerate(batches,1):
                        allowed={b['id'] for b in batch['blocks']}
                        coverage={'batch':index,'total_batches':len(batches),'refs':[b['id'] for b in batch['blocks']],'state':'started'}
                        batch_coverage.append(coverage)
                        def validate_batch(value):
                            if any(r not in allowed for e in value.events for r in e.refs+e.related_refs):
                                raise legacy.fail('liability_reference_outside_batch')
                            return record_and_validate(value)
                        batch_attempts=[]
                        try:
                            parsed,_=extract_call(settings,model,prompt,schema,batch,validate_batch,deadline,batch_attempts)
                            events.extend(parsed.events);coverage['state']='completed'
                        except ExtractionError:
                            coverage['state']='failed'
                            raise
                        finally:
                            attempts.extend(a|{'batch':index,'total_batches':len(batches)} for a in batch_attempts)
                    combined=LiabilityFacts().model_copy(update={'events':events})
                    return (combined,validate(combined)),None,attempts
            result=extract_call(settings,model,prompt,schema,content,record_and_validate,deadline,attempts)
            return result,None,attempts
        except ExtractionError as exc:
            return None,{'module':name,'code':exc.code,'message':exc.message},attempts
    def norm(facts):
        for a in facts.attachments:
            if not set(a.references+a.technical_refs+a.pricing_refs).issubset(main_refs):raise legacy.fail('material_title_is_not_main_reference')
        validation=[validate_calculation(c,sources) for c in facts.calculations]
        if any(v['state']!='verified' for v in validation) and not retain_non_amount_facts:
            raise legacy.fail(next(v['reason'] for v in validation if v['state']!='verified'))
        if retain_non_amount_facts:
            facts=facts.model_copy(update={'calculations':[c for c,v in zip(facts.calculations,validation) if v['state']=='verified']})
        # Use the unchanged legacy normalizer only after provenance validation.
        base=legacy.ContractFacts.model_validate(facts.model_dump(exclude={'calculations'})|{'calculations':[c.model_dump(include={'operation','operands','stated_total','refs'}) for c in facts.calculations]})
        for ref,block in sources.blocks.items():
            match=re.fullmatch(r'\s*(合同编号|合同号|项目编号)\s*[:：]\s*[_＿—-]*\s*',block['text'])
            if match:
                for field in base.fields:
                    if ref in field.refs and field.name==match[1]:
                        field.value_state='blank'
                        if field.timing=='signature_block':field.timing='unknown'
            if match and not any(ref in f.refs and f.name==match[1] for f in base.fields):
                base.fields.append(legacy.MissingField(name=match[1],value_state='blank',timing='unknown',refs=[ref],requirement_refs=[]))
        value=legacy.normalize_indexed_facts(base,sources,seeds,plans)
        return value,validation
    def norm_basic(value):
        if {r.rule_id for r in value.findings}!={'RL-01','RL-04'}:raise legacy.fail('basic_coverage_missing')
        for f in value.findings:
            sources.evidence(f.refs)
            if f.status=='flag' and not f.refs:raise legacy.fail('flag_without_evidence')
        return value
    def norm_liability(facts):
        facts=facts.model_copy(deep=True)
        covered={r for e in facts.events for r in e.refs}
        for ref in liability_candidate_payload(sources)['candidate_refs']:
            if ref not in covered:
                # A source-indexed paragraph is observable, not an invented legal fact.
                # Unknown event/party remains unknown; only supported textual mechanisms are checked.
                facts.events.append(LiabilityEvent(refs=[ref]))
        return validate_liability(facts,sources,context)
    tasks={
        'facts':(FACT_PROMPT,GroundedFacts,payload|{'attachment_reference_candidates':seeds,'normalized_instalment_candidates':plans},norm),
        'basic':(BASIC_PROMPT,BasicResults,payload|{'rules':[r for r in rules if r['id'] in ('RL-01','RL-04')]},norm_basic),
        'assignment':(ASSIGNMENT_PROMPT,AssignmentFacts,assignment_payload(sources)|{'context':context},lambda f:validate_assignment(f,sources,context,require_bilateral_protection=next((r.get('require_bilateral_protection',True) for r in rules if r['id']=='RL-03'),True))),
    }
    liability=policy_version=='review-liability-v1'
    if liability:tasks['liability']=(LIABILITY_PROMPT,LiabilityFacts,liability_candidate_payload(sources)|{'context':context},norm_liability)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={name:pool.submit(call,name,*args) for name,args in tasks.items()}
        outputs={}
        for name,future in futures.items():
            result,error,attempts=future.result();trace.extend([a|{'module':name} for a in attempts])
            if error:errors.append(error)
            else:outputs[name]=result
    if progress_callback:progress_callback('checking')
    def failed(rid,module):
        return dict(rule_id=rid,status='insufficient_evidence',execution_state='failed',review_reason='module_failed',explanation='本项抽取或证据校验未完成，请重试；不能据此判断未发现问题。',evidence=[],suggested_text=None,module=module)
    if 'basic' in outputs:
        for f in outputs['basic'][0].findings:records.append(dict(rule_id=f.rule_id,status=f.status,explanation=f.explanation,evidence=sources.evidence(f.refs),suggested_text=None,execution_state='completed'))
    else:records.extend(failed(r,'basic') for r in ('RL-01','RL-04'))
    records.append(outputs['assignment'][1] if 'assignment' in outputs else failed('RL-03','assignment'))
    if 'facts' in outputs:
        (facts,(attachments,amounts,fields),normalization),grounding=outputs['facts'][1]
        if attachments and bundle is not None:
            def norm_attachments(value):
                if sorted(c.name for c in value.checks)!=sorted(a['name'] for a in attachments):raise legacy.fail('attachment_coverage_mismatch')
                by_name={c.name:c.model_dump(exclude={'name'}) for c in value.checks}
                return evaluate_attachment_references([a|{'observation':by_name[a['name']]} for a in attachments],bundle,sources)
            content=payload|{'assertions':bundle.get('assertions',[]),'candidate_links':bundle.get('links',[]),'document_parse_status':bundle.get('document_parse_status','parsed'),'attachment_references':attachments,'attachment_content_candidates':index_attachment_contents(attachments,bundle,sources)}
            value,error,attempts=call('attachments',ATTACHMENT_PROMPT,AttachmentResults,model_source_payload(content,sources),norm_attachments)
            trace.extend([a|{'module':'attachments'} for a in attempts])
            if error:
                errors.append(error);records=[r for r in records if r['rule_id']!='RL-04']+[failed('RL-04','attachments')]
            else:
                checks=value[1];matched={c['reference_name'] for c in checks if c['attachment_state']=='matched'}
                facts.missing_prices=[m for m in facts.missing_prices if not(m.kind=='pricing_attachment' and m.attachment_name in matched)]
                _,amounts,fields=legacy.normalize_facts(facts,sources)
        status,note,computed=classify_amount(amounts)
        records.append(dict(rule_id='RL-02',status=status,explanation=note,evidence=legacy.unique_evidence([e.model_dump() for a in amounts for e in a.evidence]),amount_checks=[a.model_dump() for a in amounts],computed_calculations=computed,numeric_grounding=grounding,execution_state='completed'))
        if retain_non_amount_facts and any(v['state']!='verified' for v in grounding):
            records[-1].update(status='insufficient_evidence',execution_state='failed',explanation='部分计算关系未通过原文核验，金额检查未完成；其余字段与附件继续核验。')
            errors.append({'module':'amounts','code':'ungrounded_calculation','message':'计算关系无法核验，未采纳；其他事实保留。'})
        status,note=classify_field(fields)
        records.append(dict(rule_id='RL-05',status=status,explanation=note,evidence=legacy.unique_evidence([e.model_dump() for f in fields for e in f.evidence+f.requirement_evidence]),field_checks=[f.model_dump() for f in fields],execution_state='completed'))
        rule=next(r for r in records if r['rule_id']=='RL-04');rule['attachment_references']=attachments
        if not attachments and rule.get('execution_state')=='completed':rule.update(status='no_flag_for_target_rule',explanation='本次正文未识别到明确附件引用，无附件核验待办。',evidence=[])
    else:
        records.extend(failed(r,'facts') for r in ('RL-02','RL-05'))
        records=[r for r in records if r['rule_id']!='RL-04']+[failed('RL-04','facts')]
    if liability:
        if 'liability' in outputs:issues=outputs['liability'][1]
        for rid in ('CR-01','CR-02'):
            values=[i for i in issues if i['rule_id']==rid]
            if 'liability' not in outputs:record=failed(rid,'liability')
            else:record=dict(rule_id=rid,status=summarize_rule_status([i['status'] for i in values]) if values else 'no_flag_for_target_rule',explanation='发现需法务复核的责任及费用事项。' if values else '已完成本项案例提示检查，未识别到对应事项。',evidence=legacy.unique_evidence([e for i in values for e in i['evidence']]),execution_state='completed')
            records.append(record|{'execution_mode':'case_advisory'})
    for r in records:r.setdefault('execution_mode','confirmed_rule');r.setdefault('suggested_text',None)
    if progress_callback:progress_callback('validating')
    result=build_review_issues('',records,checks,expected_rule_ids=list(BASE_IDS)+(['CR-01','CR-02'] if liability else []),additional_issues=issues)
    result.update(attachment_checks=checks,module_errors=errors,diagnostics={'attempts':trace,'elapsed_seconds':round(time.monotonic()-started,3),'source_block_ids':[b['id'] for b in all_blocks],'policy_version':policy_version,'raw_extractions':raw_extractions,'liability_batches':batch_coverage})
    return result
