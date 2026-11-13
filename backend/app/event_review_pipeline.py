"""Candidate v3 workflow: factual baseline + event review + exact draft proposals."""
import json,time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from .models import Model
from .accurate_review import review_accurate,AccurateSchema,VERSION_PROMPT as BASE_PROMPT
from .review_context import contextualize
from .review_events import EventResults,EVENT_PROMPT,validate_events,indexed_events
from .revision_proposals import ProposalResults,PROPOSAL_PROMPT,validate_proposals
from .structured_review import Sources,extract_call,unique_evidence
from .review_issues import build_review_issues,summarize_rule_status
from .rule_registry import resolve_rules
from .llm import ExtractionError

POLICY='review-events-v1'
VERSION_PROMPT=BASE_PROMPT+'\n---\n'+EVENT_PROMPT+'\n---\n'+PROPOSAL_PROMPT
class EventPipelineSchema(Model):
    baseline:AccurateSchema
    events:EventResults
    proposals:ProposalResults


def implementation_hash():
    from .accurate_review import implementation_hash as baseline_hash
    root=Path(__file__).parent
    files=('event_review_pipeline.py','review_context.py','review_events.py','revision_proposals.py','legal_casebook.py','case_retrieval.py','worker.py','review_jobs.py','models.py','materials.py','llm.py','case_guidance.py')
    return sha256(baseline_hash().encode()+b''.join((root/f).read_bytes() for f in files)).hexdigest()


def review_events_pipeline(settings,model,blocks,context,rules,*,bundle=None,policy_version=POLICY,progress_callback=None,document_version_id='',casebook=None,casebook_version=None,excluded_family_ids=(),retrieval_snapshot=None,case_guidance_snapshot=None):
    from dataclasses import replace
    started=time.monotonic();deadline=started+min(settings.timeout+30,120)
    blocks=[b for b in blocks if b['text'].strip()]
    context=contextualize(context,blocks);context['document_version_id']=document_version_id;context['document_sha256']=(retrieval_snapshot or {}).get('document_sha256');sources=Sources(blocks)
    trace=[];errors=[];raw={};retrieval={'casebook_version':casebook_version,'hits':[],'reason':'no_confirmed_casebook'}
    def progress(stage):
        if progress_callback:progress_callback(stage)
    progress('extracting')
    def events_call():
        seeds=indexed_events(sources);accepted=[];rejected=[]
        semantic_rejections={'event_stacking_unsupported','event_fee_exposure_unsupported','event_noncash_unsupported','event_software_protection_unsupported','event_payment_remedy_unsupported','event_cap_already_present'}
        def validate(value):
            nonlocal accepted
            raw['events']=value.model_dump(mode='json');good=[];technical=[]
            for event in value.events:
                try:
                    validate_events(EventResults(events=[event]),sources,context);good.append(event)
                except ExtractionError as exc:
                    reason=exc.diagnostics[0].get('reason','') if getattr(exc,'diagnostics',None) else exc.code
                    rejected.append({'rule_id':event.rule_id,'ref':event.ref,'reason':reason})
                    if reason not in semantic_rejections:technical.append(exc)
            # Source-indexed mechanisms are observable facts, not inferred policy limits.
            for seed in seeds:
                if not any(g.ref==seed.ref and g.rule_id==seed.rule_id and ''.join(seed.quote.split()) in ''.join(g.quote.split()) for g in good):good.append(seed)
            accepted=validate_events(EventResults(events=good),sources,context)
            if technical:raise technical[0]
            return accepted
        try:
            _,issues=extract_call(settings,model,EVENT_PROMPT,EventResults,{'blocks':sources.public,'context':context,'candidate_events':[s.model_dump() for s in seeds]},validate,deadline,trace)
            raw['rejected_candidates']=rejected
            return issues,None
        except ExtractionError as exc:
            raw['rejected_candidates']=rejected
            return accepted,{'module':'events','code':exc.code,'message':exc.message}
    with ThreadPoolExecutor(max_workers=2) as pool:
        baseline=pool.submit(review_accurate,settings,model,blocks,context,resolve_rules('review-grounded-v1'),bundle=bundle,policy_version='review-grounded-v1',retain_non_amount_facts=True)
        event_future=pool.submit(events_call)
        result=baseline.result();issues,error=event_future.result()
    errors.extend(result.get('module_errors',[]))
    if error:errors.append(error)
    progress('checking')
    records=result['rule_results']
    for rid in [r['id'] for r in rules if r['id'].startswith('CR-')]:
        values=[i for i in issues if i['rule_id']==rid]
        records.append(dict(rule_id=rid,status='insufficient_evidence' if error else summarize_rule_status([i['status'] for i in values]) if values else 'no_flag_for_target_rule',
            explanation='本项事件检查未完成。' if error else '发现需法务核对的事件或保护事项。' if values else '本次已解析正文未识别到本项案例提示，不代表全文无风险。',
            execution_state='failed' if error else 'completed',execution_mode='case_advisory',evidence=unique_evidence([e for i in values for e in i['evidence']]),suggested_text=None))
    proposals=[];basis=[]
    if casebook is not None:
        retrieval['reason']='no_scoped_match'
        for i in issues:
            hits=casebook.retrieve_cases({'event_type':i['review_reason'],'text':i['event_anchor']['quote']},context,set(excluded_family_ids),casebook_version,excluded_source_hashes=(retrieval_snapshot or {}).get('excluded_source_hashes',()))
            retrieval['hits'].extend({'event_id':i['event_id'],'case_id':h['case_id'],'version':h.get('version'),'content_digest':h['content_digest']} for h in hits)
            basis.extend(h for h in hits if h not in basis)
        if basis:retrieval['reason']='matched'
        elif context.get('business_scope_state')!='matched':retrieval['reason']='scope_unconfirmed'
    from .case_guidance import bind_guidance
    guidance=bind_guidance(case_guidance_snapshot,blocks,context,document_version_id)
    basis.extend(guidance)
    if issues:
        ref_by_block={b['id']:ref for ref,b in sources.blocks.items()}
        # A whole event stays together: refund and extra damages may require two
        # edits. Small batches avoid asking one completion to rewrite every event.
        draft_events=[{**{k:i.get(k) for k in ('event_id','rule_id','mechanisms','explanation','clause_number')},
                       'ref':ref_by_block[i['event_anchor']['block_id']],
                       'quote':i['event_anchor']['quote'],
                       'related_refs':list(dict.fromkeys(ref_by_block[e['block_id']] for e in i['evidence'] if e['block_id'] in ref_by_block))} for i in issues]
        combined=[];draft_deadline=time.monotonic()+2*settings.timeout
        raw['proposal_batches']=[]
        for offset in range(0,len(draft_events),2):
            batch=draft_events[offset:offset+2];batch_ids={e['event_id'] for e in batch}
            batch_issues=[i for i in issues if i['event_id'] in batch_ids]
            batch_trace=[];record={'event_ids':sorted(batch_ids),'state':'started'}
            raw['proposal_batches'].append(record)
            try:
                def validate(value):
                    record['output']=value.model_dump(mode='json')
                    return validate_proposals(value,sources,document_version_id,batch_issues,basis)
                value,_=extract_call(replace(settings,max_output_tokens=4096),model,PROPOSAL_PROMPT,ProposalResults,
                    {'blocks':sources.public,'context':context,'events':batch,'basis':basis},validate,
                    min(draft_deadline,time.monotonic()+settings.timeout),batch_trace)
                combined.extend(value.proposals);record['state']='completed'
            except ExtractionError as exc:
                record.update(state='failed',code=exc.code)
                errors.append({'module':'proposals','code':exc.code,'message':exc.message,'event_ids':sorted(batch_ids)})
            finally:
                for item in batch_trace:item['event_ids']=sorted(batch_ids)
                trace.extend(batch_trace)
        raw['proposals']={'proposals':[p.model_dump(mode='json') for p in combined]}
        # Validate overlaps across successful batches as well, preserving partial work.
        proposals=validate_proposals(ProposalResults(proposals=combined),sources,document_version_id,issues,basis)
        if any(p['state']=='invalid' for p in proposals):errors.append({'module':'proposals','code':'invalid_proposal','message':'部分修改建议未通过原文或依据校验，不能直接应用。'})
    progress('validating')
    out=build_review_issues('',records,result.get('attachment_checks',[]),expected_rule_ids=[r['id'] for r in rules],additional_issues=issues)
    for i in out['issues']:
        i['display_group']='context' if i['rule_id']=='RL-05' or i.get('review_reason')=='role_unknown' else 'legal_issue'
    out.update(result_schema_version='interactive-review-v3',revision_proposals=proposals,context_snapshot=context,module_errors=errors,attachment_checks=result.get('attachment_checks',[]),
        diagnostics={'baseline':result.get('diagnostics',{}),'attempts':trace,'raw_extractions':raw,'elapsed_seconds':round(time.monotonic()-started,3),'retrieval':retrieval,'excluded_family_ids':sorted(excluded_family_ids),
                     'review_mode':'case_guided_review' if case_guidance_snapshot is not None else 'independent_review',
                     'case_guidance':{'requested':case_guidance_snapshot is not None,'matches':guidance},
                     'context_warnings':(['合同类型标签与正文业务范围不一致，请核对。'] if context['business_scope_state']=='conflict' else [])+['金额检查仅校验可核验的明确算式；跨表格单元合计和税额换算尚未全面核验。']})
    return out


def known_family_ids(blocks):
    """Exclude known near-duplicate development families from live case retrieval."""
    import re
    def grams(items):
        text=re.sub(r'\s+','',''.join(b['text'] for b in items))
        return {text[i:i+16] for i in range(0,max(0,len(text)-15))}
    query=grams(blocks);matches=set()
    root=Path(__file__).resolve().parents[2]/'analysis/legal-corpus/alignment-v1'
    for path in root.glob('S*/inputs.jsonl'):
        for line in path.read_text().splitlines():
            case=json.loads(line);other=grams(case['blocks'])
            if query and other and len(query&other)/min(len(query),len(other))>=0.8:
                matches.add(case['family_id'])
    return matches
