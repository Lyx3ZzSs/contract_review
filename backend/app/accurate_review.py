"""Versioned review with independently validated modules and explicit partial failure."""
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from hashlib import sha256
from typing import Literal
from pydantic import Field
from .models import Model
from . import structured_review as legacy
from .structured_review import Sources,extract_call
from .fact_grounding import GroundedFacts,GROUNDING_PROMPT,validate_calculation
from .assignment_review import AssignmentFacts,ASSIGNMENT_PROMPT,validate_assignment,assignment_payload,termination_transfer_facts
from .liability_review import LiabilityFacts,LiabilityEvent,LIABILITY_PROMPT,validate_liability,liability_candidate_payload,liability_batches
from .amount_review import classify as classify_amount
from .field_review import classify as classify_field
from .reference_index import index_references
from .review_issues import build_review_issues,summarize_rule_status
from .attachment_review import AttachmentResults,ATTACHMENT_PROMPT,index_attachment_contents,evaluate_attachment_references
from .interactive_review import reference_candidates,model_source_payload
from .llm import ExtractionError
from .rule_registry import BASE_IDS
from .rule_registry import CONFIGURED_RULES_POLICY
from .review_evidence import ReviewEvidence, normalized_text


class DeadlineObservation(Model):
    ref: str
    subject_quote: str = Field(min_length=2, max_length=120)
    start_quote: str = Field(min_length=2, max_length=120)
    duration_quote: str = Field(min_length=2, max_length=40)


class BasicFinding(Model):
    rule_id:Literal['RL-01','RL-04']
    status:Literal['flag','no_flag_for_target_rule','insufficient_evidence','not_applicable']
    explanation:str=Field(min_length=1,max_length=1000)
    refs:list[str]=Field(max_length=50)
    deadlines: list[DeadlineObservation] = Field(default_factory=list, max_length=2)
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
CONFIGURED_FACT_SCOPE = ('\nRL-02区分合同总价、单笔付款及付款本身的比例。“付清剩余100%质保款”指付清该笔质保款，'
                         '不能把100%当合同总价比例，也不能自行推导其占合同总价的比例或认定冲突。'
                         '分期比例由程序从原文核算，calculations仅返回explicit_formula，禁止返回instalment_percentages。'
                         'RL-05提取必填依据时引用要求在当前阶段确定该字段的原文，禁止把字段标题或占位符当作必填依据。')
CONFIGURED_BASIC_SCOPE = ('\nRL-01只有同一事项、期限类型和起算事件下的明确期限无法同时成立才flag。'
                          '固定起止日期与自签署起的相同期间可以并存。日期留空时只说明缺哪个日期，'
                          '不可同时断言期限冲突。空白本身由RL-05处理。'
                          'flag必须在deadlines中逐项引用两个期限的事项类型subject_quote、起算事件start_quote、'
                          '有单位的纯时长duration_quote与ref；三个引文必须逐字来自同一个ref。否则填insufficient_evidence。')


_DURATION = re.compile(r'(\d+(?:\.\d+)?)个?([年月]|工作日|自然日|日|天|小时)')
_PERIOD_TYPES = re.compile(r'部署|上线|交付|试运行|服务|验收|质保|保修|付款|结算|合同|保密|续约')
_DEADLINE_LIMIT = re.compile(r'以内|之内|日内|天内|月内|年内|小时内|之前|以后|之后|不超过|不得超过|不迟于|最迟|不得早于|不少于|至少|可延长|另行|为准|除非')
_MANDATORY_FIELD = re.compile(r'(?:必须|应当|应|须)[^。；]{0,32}(?:填写|填列|填妥|补齐|补充|明确|提供|确定|约定)')


def verify_deadlines(finding, sources):
    periods = []
    for item in finding.deadlines:
        if item.ref not in finding.refs:
            return False
        text = sources.text([item.ref])
        subject, start, duration = map(normalized_text,
                                      (item.subject_quote, item.start_quote, item.duration_quote))
        match = _DURATION.fullmatch(duration)
        if not match:
            return False
        # A shared term alone cannot join two distinct obligations in the same paragraph.
        statements = [part for source in re.split(r'[。；;\n]', text)
                      if (part := normalized_text(source))
                      if all(q in part for q in (subject, start, duration))]
        if len(statements) != 1 or _DEADLINE_LIMIT.search(statements[0]):
            return False
        if not re.search(r'(?<![\d.])' + re.escape(duration) + r'(?![\d.])', statements[0]):
            return False
        periods.append((subject, start, set(_PERIOD_TYPES.findall(statements[0])),
                        {'天':'日','自然日':'日'}.get(match[2], match[2]), match[1]))
    if len(periods) != 2:
        return False
    left, right = periods
    return left[:4] == right[:4] and Decimal(left[-1]) != Decimal(right[-1])


def _has_current_field_requirement(field):
    if field.timing != 'current_required':
        return False
    name = normalized_text(field.name)
    return any(name in normalized_text(statement) and _MANDATORY_FIELD.search(normalized_text(statement))
               for evidence in field.requirement_evidence
               for statement in re.split(r'[。；;，,\n]', evidence.quote))


def implementation_hash():
    from pathlib import Path
    names=('accurate_review.py','fact_grounding.py','assignment_review.py','liability_review.py','rule_registry.py','review_issues.py','reference_index.py','amount_review.py','field_review.py','structured_review.py','interactive_review.py','attachment_review.py')
    root=Path(__file__).parent
    return sha256(b''.join((root/n).read_bytes() for n in names)).hexdigest()


def _fact_sections(attachments, amounts, fields):
    sections = [
        {'title': '附件引用', 'text': f'正文引用《{a["name"]}》。', 'evidence': a['reference_evidence']}
        for a in attachments
    ]
    operators = {'sum': ' + ', 'product': ' × ', 'percentage': ' × '}
    for amount in amounts:
        if amount.issue != 'calculation':
            continue
        expression = operators[amount.operation].join(amount.operands)
        if amount.operation == 'percentage':
            expression += '%'
        sections.append({'title': '金额核算依据', 'text': f'核算式 {expression}，对照值 {amount.stated_total}。',
                         'evidence': [e.model_dump() for e in amount.evidence]})
    field_states = {'filled': '已填写', 'blank': '空白', 'placeholder': '有占位内容', 'unavailable': '内容无法确认'}
    sections.extend({'title': '关键字段', 'text': f'{field.name} · {field_states[field.value_state]}',
                     'evidence': [e.model_dump() for e in field.evidence]} for field in fields)
    return sections or [{'title': '', 'text': '本次可读内容中未提取到金额计算关系、附件引用或关键字段。', 'evidence': []}]


def review_accurate(settings,model,blocks,context,rules,*,bundle=None,policy_version='review-liability-v1',progress_callback=None,retain_non_amount_facts=False,execution_callback=None,model_call=None,review_evidence=None):
    model_call = model_call or extract_call
    configured = policy_version == CONFIGURED_RULES_POLICY
    started=time.monotonic();deadline=started+min(120,settings.timeout)
    review_evidence = review_evidence or ReviewEvidence(list(blocks), bundle)
    sources, main_sources = review_evidence.reviews, review_evidence.main
    all_blocks = list(sources.blocks.values())
    materials = (bundle or {}).get('materials', [])
    main_refs = set(main_sources.blocks)
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
    def basic_record(f):
        return dict(rule_id=f.rule_id,status=f.status,explanation=f.explanation,
                    evidence=sources.evidence(f.refs),suggested_text=None,execution_state='completed')
    def call(name,prompt,schema,content,validate):
        titles={'facts':'提取金额、附件和关键字段','basic':'核查合同基础规则','assignment':'核查合同转让条款','attachments':'核验附件材料','liability':'核查责任条款'}
        if execution_callback:
            execution_callback('task_discovered',task_id='base:'+name,title=titles.get(name,name))
            scope, sections = {}, []
            if configured and name == 'basic':
                scope['RL-01'] = f'从本轮 {len(content["blocks"])} 个可读段落中核对同一事项的期限表述。'
            if configured and name == 'facts':
                scope['RL-02'] = f'已索引 {len(plans)} 组分期比例候选，同时检查原文列明的算式。'
                scope['RL-04'] = f'正文初筛得到 {len(seeds)} 项附件引用候选，正在核对是否明确引用。'
            if configured and name == 'assignment':
                refs = content['candidate_refs']
                scope['RL-03'] = f'从原文筛出 {len(refs)} 个候选段落，核对转让方、同意方和许可范围。'
                if refs:
                    sections = [{'title':'转让候选段落','text':'','evidence':sources.evidence(refs[:3])}]
            if configured and name == 'attachments':
                count = len(content['attachment_references'])
                scope['RL-04'] = f'将正文引用的 {count} 项附件与本轮材料逐项核对。'
            execution_callback('task_started',task_id='base:'+name,**({'rule_scope':scope} if scope else {}),
                               **({'sections':sections} if sections else {}))
        result,error,attempts=call_inner(name,prompt,schema,content,validate)
        if execution_callback:
            details = {}
            if configured and not error and name == 'facts':
                (_, normalized, _), _ = result[1]
                attachments, amounts, fields = normalized
                details['sections'] = _fact_sections(*normalized)
                calculations = sum(a.issue == 'calculation' for a in amounts)
                gaps = sum(f.value_state in ('blank','placeholder') for f in fields)
                required = sum(_has_current_field_requirement(f) and f.value_state in ('blank','placeholder') for f in fields)
                details['rule_observations'] = {
                    'RL-02': f'提取到 {calculations} 项可复算关系，{sum(a.issue == "missing_basis" for a in amounts)} 项计价依据缺失候选。',
                    'RL-04': f'事实提取识别到 {len(attachments)} 项正文附件引用。',
                    'RL-05': f'识别到 {gaps} 处空白或占位，其中 {required} 处有当前应填写的原文依据。',
                }
            if configured and not error and name == 'assignment':
                details['rule_observations'] = {'RL-03': f'提取到 {len(result[0].clauses)} 条转让约定。'}
            if configured and not error and name == 'basic':
                details['rule_observations'] = {f.rule_id: f'初查结果引用了 {len(set(f.refs))} 个原文段落。'
                                                for f in result[0].findings}
            execution_callback('task_failed' if error else 'task_completed',
                               task_id='base:'+name,message=error['message'] if error else '',**details)
            if configured and not error:
                early = []
                if name=='assignment':
                    early = [result[1]]
                elif name=='basic':
                    # Attachment findings depend on the later materials check.
                    early = [basic_record(f) for f in result[0].findings if f.rule_id=='RL-01']
                for issue in early:
                    execution_callback('issue_upserted',issue={**issue,'execution_mode':'confirmed_rule'})
        return result,error,attempts
    def call_inner(name,prompt,schema,content,validate):
        attempts=[]
        try:
            def record_and_validate(value):
                raw_extractions.setdefault(name,[]).append(value.model_dump(mode='json'))
                return validate(value)
            if name == 'assignment':
                facts = termination_transfer_facts(sources, content['candidate_refs'])
                if facts is not None:
                    try:
                        result = validate(facts)
                    except ExtractionError:
                        # Keep the regular evidence reader for unresolved source combinations.
                        pass
                    else:
                        raw_extractions.setdefault(name, []).append(facts.model_dump(mode='json'))
                        attempts.append({'stage':'AssignmentFacts', 'status':'validated', 'source':'termination_clause_pair'})
                        return (facts, result), None, attempts
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
                            parsed,_=model_call(settings,model,prompt,schema,batch,validate_batch,deadline,batch_attempts)
                            events.extend(parsed.events);coverage['state']='completed'
                        except ExtractionError:
                            coverage['state']='failed'
                            raise
                        finally:
                            attempts.extend(a|{'batch':index,'total_batches':len(batches)} for a in batch_attempts)
                    combined=LiabilityFacts().model_copy(update={'events':events})
                    return (combined,validate(combined)),None,attempts
            result=model_call(settings,model,prompt,schema,content,record_and_validate,deadline,attempts)
            return result,None,attempts
        except ExtractionError as exc:
            return None,{'module':name,'code':exc.code,'message':exc.message},attempts
    def norm(facts):
        for a in facts.attachments:
            if not set(a.references+a.technical_refs+a.pricing_refs).issubset(main_refs):raise legacy.fail('material_title_is_not_main_reference')
        # Indexed instalments are applied below regardless of what the model
        # emits. A duplicate token or a guessed schedule cannot block RL-02.
        if configured:
            facts = facts.model_copy(update={'calculations':[c for c in facts.calculations
                                                             if c.relation_kind != 'instalment_percentages']})
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
            if configured and f.rule_id == 'RL-01' and f.status == 'flag' and not verify_deadlines(f, sources):
                f.status = 'insufficient_evidence'
                f.explanation = '期限冲突的事项、起算点或时长尚无法从所引原文共同核实。'
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

    def check_attachments(attachments):
        def validate(value):
            if sorted(c.name for c in value.checks) != sorted(a['name'] for a in attachments):
                raise legacy.fail('attachment_coverage_mismatch')
            by_name = {c.name: c.model_dump(exclude={'name'}) for c in value.checks}
            return evaluate_attachment_references(
                [a | {'observation': by_name[a['name']]} for a in attachments],
                bundle, sources, require_identity=configured,
            )

        content = payload | {
            'assertions': bundle.get('assertions', []), 'candidate_links': bundle.get('links', []),
            'attachment_references': attachments,
            'attachment_content_candidates': index_attachment_contents(attachments, bundle, sources),
        }
        return call('attachments', ATTACHMENT_PROMPT, AttachmentResults,
                    model_source_payload(content, sources), validate)

    def field_record(fields):
        actionable = [f for f in fields if _has_current_field_requirement(f)] if configured else fields
        status, note = classify_field(actionable)
        if configured and not actionable:
            note = '本轮未识别到有明确原文依据、当前应填而未填的事项。'
        return dict(rule_id='RL-05', status=status, explanation=note,
                    evidence=legacy.unique_evidence([e.model_dump() for f in actionable
                                                     for e in f.evidence + f.requirement_evidence]),
                    field_checks=[f.model_dump() for f in actionable], execution_state='completed',
                    execution_mode='confirmed_rule', suggested_text=None)

    def amount_record(amounts, grounding):
        status, note, computed = classify_amount(amounts)
        record = dict(rule_id='RL-02', status=status, explanation=note,
                      evidence=legacy.unique_evidence([e.model_dump() for a in amounts for e in a.evidence]),
                      amount_checks=[a.model_dump() for a in amounts], computed_calculations=computed,
                      numeric_grounding=grounding, execution_state='completed',
                      execution_mode='confirmed_rule', suggested_text=None)
        if retain_non_amount_facts and any(v['state'] != 'verified' for v in grounding):
            record.update(status='insufficient_evidence', execution_state='failed',
                          explanation='部分计算关系未通过原文核验，金额检查未完成；其余字段与附件继续核验。')
        return record

    tasks={
        'facts':(FACT_PROMPT + (CONFIGURED_FACT_SCOPE if configured else ''),GroundedFacts,payload|{'attachment_reference_candidates':seeds,'normalized_instalment_candidates':plans},norm),
        'basic':(BASIC_PROMPT + (CONFIGURED_BASIC_SCOPE if configured else ''),BasicResults,payload|{'rules':[r for r in rules if r['id'] in ('RL-01','RL-04')]},norm_basic),
        'assignment':(ASSIGNMENT_PROMPT,AssignmentFacts,assignment_payload(sources)|{'context':context},lambda f:validate_assignment(f,sources,context,require_bilateral_protection=next((r.get('require_bilateral_protection',True) for r in rules if r['id']=='RL-03'),True))),
    }
    liability=policy_version=='review-liability-v1'
    if liability:tasks['liability']=(LIABILITY_PROMPT,LiabilityFacts,liability_candidate_payload(sources)|{'context':context},norm_liability)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(call,name,*args):name for name,args in tasks.items()}
        outputs={}
        attachments_future = None
        for future in as_completed(futures):
            name = futures[future]
            result,error,attempts=future.result();trace.extend([a|{'module':name} for a in attempts])
            if error:errors.append(error)
            else:outputs[name]=result
            if name == 'facts' and not error:
                (facts, (attachments, amounts, fields), _), grounding = result[1]
                if configured and execution_callback:
                    execution_callback('issue_upserted', issue=field_record(fields))
                    depends_on_attachment = attachments and bundle is not None and any(
                        price.kind == 'pricing_attachment' for price in facts.missing_prices
                    )
                    if not depends_on_attachment:
                        execution_callback('issue_upserted', issue=amount_record(amounts, grounding))
                if attachments and bundle is not None:
                    attachments_future = pool.submit(check_attachments, attachments)
    if progress_callback:progress_callback('checking')
    def failed(rid,module):
        return dict(rule_id=rid,status='insufficient_evidence',execution_state='failed',review_reason='module_failed',explanation='本项抽取或证据校验未完成，请重试；不能据此判断未发现问题。',evidence=[],suggested_text=None,module=module)
    if 'basic' in outputs:
        records.extend(basic_record(f) for f in outputs['basic'][0].findings)
    else:records.extend(failed(r,'basic') for r in ('RL-01','RL-04'))
    records.append(outputs['assignment'][1] if 'assignment' in outputs else failed('RL-03','assignment'))
    if 'facts' in outputs:
        (facts,(attachments,amounts,fields),normalization),grounding=outputs['facts'][1]
        if attachments_future is not None:
            value,error,attempts=attachments_future.result()
            trace.extend([a|{'module':'attachments'} for a in attempts])
            if error:
                errors.append(error);records=[r for r in records if r['rule_id']!='RL-04']+[failed('RL-04','attachments')]
            else:
                checks=value[1]
                covered = {c['reference_name']: c for c in checks
                           if c['attachment_state']=='matched' or (configured and c['status']=='insufficient_evidence')}
                def price_reference(m):
                    name = m.attachment_name or ''
                    return name.strip('《》「」') if configured else name
                if configured:
                    for name in {price_reference(m) for m in facts.missing_prices if m.kind=='pricing_attachment'} & covered.keys():
                        check = covered[name]
                        if check['status']=='insufficient_evidence':
                            check['explanation'] += '。补齐或核对该附件后，可一并核对相关计价依据。'
                facts.missing_prices=[m for m in facts.missing_prices if not(m.kind=='pricing_attachment' and price_reference(m) in covered)]
                _,amounts,fields=legacy.normalize_facts(facts,sources)
        records.append(amount_record(amounts, grounding))
        if records[-1]['execution_state'] == 'failed':
            errors.append({'module':'amounts','code':'ungrounded_calculation','message':'计算关系无法核验，未采纳；其他事实保留。'})
        records.append(field_record(fields))
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
