"""Execute the frozen rule pack and generate targeted, validated drafts."""
import os
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from threading import Lock

from .transaction_display import stream_overview
from . import liability_limit
from .accurate_review import AccurateSchema, review_accurate as baseline_review
from .clause_structure import build_clauses, block_citations
from .llm import ExtractionError
from .models import Model
from .review_context import normalize_review_context
from .review_issues import build_review_issues, liability_clause_issues, liability_issues
from .review_evidence import ReviewEvidence
from .revision_proposals import (
    CONFIGURED_DRAFT_PROMPT, PATCH_DRAFT_PROMPT, SINGLE_DRAFT_PROMPT, ConfiguredDraftResults, DraftPatchReader, ProposalResults,
    SingleClauseDraft, configured_draft_targets, consolidate_configured_proposals, coordinated_draft_groups,
    detect_overlaps, draft_units, validate_configured_drafts, verify_combined_draft_effects,
)
from .rule_registry import CONFIGURED_RULES_POLICY
from .structured_review import extract_call, fail


class ConfiguredRulesSchema(Model):
    baseline: AccurateSchema
    liability: liability_limit.LimitFacts
    liability_group: liability_limit.ClauseFindings
    liability_perspective: liability_limit.PerspectiveCheck
    drafting: ConfiguredDraftResults
    single_draft: SingleClauseDraft


def implementation_hash():
    from .accurate_review import implementation_hash as base_hash

    root = Path(__file__).parent
    files = (
        'configured_review.py', 'liability_limit.py', 'liability_numbers.py',
        'review_execution_events.py', 'review_context.py',
        'review_transport.py', 'revision_proposals.py', 'clause_structure.py',
        'review_checkpoints.py', 'transaction_display.py', 'review_stream.py',
        'review_evidence.py', 'liability_schedule.py',
    )
    return sha256(base_hash().encode() + b''.join((root / name).read_bytes() for name in files)).hexdigest()


def review_configured(settings, model, blocks, context, rules, *, bundle=None, clauses=None,
                      execution_callback=None, document_version_id='', progress_callback=None,
                      model_call=None):
    if model.lower().startswith('deepseek-'):
        settings = replace(settings, thinking='disabled')
    arguments = dict(bundle=bundle, clauses=clauses, execution_callback=execution_callback,
                     document_version_id=document_version_id, progress_callback=progress_callback,
                     model_call=model_call)
    if not execution_callback:
        return _check_rules(settings, model, blocks, context, rules, **arguments)
    with ThreadPoolExecutor(max_workers=1) as pool:
        overview = pool.submit(stream_overview, settings, model, blocks, normalize_review_context(context)['our_party'],
                               model_call or extract_call, execution_callback)
        result = _check_rules(settings, model, blocks, context, rules, **arguments)
        artifact = overview.result()
        result['analysis_artifacts'] = {artifact['id']: artifact}
        if artifact['state'] == 'failed':
            result['module_errors'].append({'module':'transaction-overview', 'code':'overview_incomplete',
                                           'message':artifact['message']})
        return result


def _check_rules(settings, model, blocks, context, rules, *, bundle, clauses, execution_callback,
                 document_version_id, progress_callback, model_call):
    concurrency = max(1, min(8, int(os.getenv('RIXIN_REVIEW_CONCURRENCY', '8'))))
    with ThreadPoolExecutor(max_workers=min(4, concurrency)) as drafting_pool:
        return _run_rules(settings, model, blocks, context, rules, bundle, clauses,
                          execution_callback, document_version_id, progress_callback,
                          model_call, concurrency, drafting_pool)


def _run_rules(settings, model, blocks, context, rules, bundle, clauses, execution_callback,
               document_version_id, progress_callback, model_call, concurrency, drafting_pool):
    started = time.monotonic()
    snapshot = ReviewEvidence(blocks, bundle, document_version_id=document_version_id)
    sources = snapshot.main
    if clauses is None:
        clauses = build_clauses(document_version_id, list(sources.blocks.values()))
    citations = block_citations(clauses)
    context = normalize_review_context(context)
    emit = execution_callback or (lambda *args, **kwargs: None)
    checked_call = model_call or extract_call
    errors = []
    traces = []
    draft_jobs = []
    submitted = set()
    draft_lock = Lock()
    drafting_title = '配置规则局部拟稿'
    mandate = f'本次仅代表{context["our_party"]}拟稿。先比较修订前后的实际利益，不得扩大我方付款或赔偿责任、削弱我方已有保护。'

    def phase(key,title,state,**extra):
        emit('phase_updated',phase={'id':key,'title':title,'state':state,**extra})
    def error(module,exc):
        # Upstream exception text can contain request details; use safe known messages.
        item={'module':module,'code':getattr(exc,'code','rule_module_failed'),
              'message':exc.message if isinstance(exc,ExtractionError) else '本项执行失败，其他已完成结果已保留。'}
        errors.append(item);return item['message']

    def reviewed_issue(issue):
        return {**issue, 'review_state': 'reviewed',
                'evidence_sources': snapshot.provenance(issue),
                'provenance': issue.get('provenance') or {
                    'origin': 'configured_rule', 'rule_id': issue['rule_id'],
                }}

    def start_draft_batch(group, aligned, task_id):
        edits, problems, trace = draft_group(checked_call, settings, model, context['our_party'], mandate,
                                             group, aligned, sources, document_version_id, task_id, emit)
        missing = group.keys() - {eid for edit in edits for eid in edit['event_ids']}
        shared = coordinated_draft_groups(group)
        shared_events = {eid for ids in shared.values() for eid in ids}
        issues = {issue['event_id']: issue for issue in aligned}
        repairs = []
        for index, ids in enumerate(shared.values(), 1):
            if missing.intersection(ids):
                repair_targets = {eid:group[eid] for eid in ids}
                feedback = {eid:problems.get(eid, '同段意见需要统一改文。') for eid in ids}
                repairs.append(drafting_pool.submit(
                    draft_group, checked_call, settings, model, context['our_party'], mandate, repair_targets,
                    [issues[eid] for eid in ids], sources, document_version_id, f'{task_id}:retry-{index}',
                    emit, feedback=feedback,
                ))
        for eid in group:
            if eid in missing and eid not in shared_events:
                reason = problems.get(eid, '')
                if group[eid]['rule_id'] == liability_limit.RULE_ID and '交叉引用' in reason:
                    repairs.append(drafting_pool.submit(
                        draft_group, checked_call, settings, model, context['our_party'], mandate, {eid:group[eid]},
                        [issues[eid]], sources, document_version_id, task_id+':citation-'+eid, emit,
                        feedback={eid:reason+' 本次以义务内容指代其他条款，保留原文已有编号。'},
                    ))
                    continue
                repairs.append(drafting_pool.submit(
                    retry_draft, checked_call, settings, model, context['our_party'], mandate, group[eid],
                    issues[eid], sources, document_version_id, emit,
                    problems.get(eid, '此项缺少可定位的有效改文。'),
                ))
        return edits, problems, trace, repairs

    def submit_drafts(targets, issues):
        with draft_lock:
            ordered = {eid: target for eid, target in targets.items() if eid not in submitted}
            if ordered and not draft_jobs:
                phase('drafting', drafting_title, 'running')
            by_event = {issue['event_id']: issue for issue in issues if issue.get('event_id')}
            shared = {eid: ids for ids in coordinated_draft_groups(ordered).values() for eid in ids}
            batches = []
            batch = {}
            for eid in ordered:
                ids = shared.get(eid, [eid])
                if eid != ids[0]:
                    continue
                if batch and len(batch) + len(ids) > 3:
                    batches.append(batch)
                    batch = {}
                batch.update({key: ordered[key] for key in ids})
            if batch:
                batches.append(batch)
            for group in batches:
                aligned = [by_event[eid] for eid in group]
                for issue in aligned:
                    emit('issue_upserted', issue={**issue, 'revision_plan': {
                        'state': 'generating', 'message': '正在拟定本条改文。',
                    }})
                draft_jobs.append(drafting_pool.submit(
                    start_draft_batch, group, aligned, f'configured-drafting:{len(draft_jobs) + 1}',
                ))
                submitted.update(group)

    unresolved = sum(c.get('resolution_status') == 'unresolved' for c in clauses)
    parse_message = f'已解析 {len(sources.public)} 个正文段落，形成 {len(clauses)} 个结构节点，{unresolved} 处结构待核对'
    phase('parse', '合同解析', 'completed', message=parse_message + '；仅审查本次可读取材料。')
    phase('rules', '配置规则核查', 'queued')
    limit_rule = next((r for r in rules if r['id'] == liability_limit.RULE_ID), None)
    baseline_rules = [r for r in rules if r['id'] != liability_limit.RULE_ID]
    def baseline(pool):
        title = '配置规则核查'
        phase('rules',title,'running')
        limit_trace = []
        def check_limit():
            emit('task_started',task_id='base:liability-limit')
            emitted = set()
            liability_sources = {ref: block_id for ref, _, block_id, _, _ in snapshot.liability_rows}
            def limit_progress(key,title,kind,refs=()):
                states = {'started':'等待模型响应','receiving':'正在接收责任分析','validating':'正在校验原文',
                          'completed':'已完成核查','failed':'未取得有效结果'}
                if kind in states:
                    event = {'completed':'task_completed','failed':'task_failed'}.get(kind,'task_started')
                    evidence = [
                        {'block_id': liability_sources[ref], 'start': 0, 'end': len(snapshot.by_id[liability_sources[ref]]),
                         'quote': snapshot.by_id[liability_sources[ref]]}
                        for ref in dict.fromkeys(refs)
                    ] if refs and kind == 'started' else []
                    details = {'sections':[{'title':'', 'text':'本组核查原文', 'evidence':evidence}]} if evidence else {}
                    emit(event,task_id=f'base:liability-limit:{key}',title=title,message=states[kind],**details)
            def accept_group(record):
                issues = [reviewed_issue(issue) for issue in liability_clause_issues(record)]
                for issue in issues:
                    emit('issue_upserted', issue=issue)
                    emitted.add(issue['subject_key'])
                targets, _ = configured_draft_targets(issues, sources, citations)
                submit_drafts(targets, issues)

            try:
                record = liability_limit.run_limit(checked_call, settings, model, sources, bundle,
                                                    context, limit_rule, limit_trace, indexed_numbers=True,
                                                    clause_details=True, citations=citations, progress=limit_progress,
                                                    review_evidence=snapshot, on_group=accept_group)
            except Exception as exc:
                if getattr(exc,'code',None)!='lease_lost':
                    emit('task_failed',task_id='base:liability-limit',message='累计责任核查未完成。')
                raise
            failed = record.get('execution_state')=='failed'
            if failed:
                errors.append({'module':'liability_limit', 'code':record.get('review_reason', 'liability_group_failed'),
                               'message':record['explanation']})
            emit('task_failed' if failed else 'task_completed',task_id='base:liability-limit',
                 message=record['explanation'] if failed else '')
            for issue in liability_issues(record):
                if issue.get('subject_key', issue['rule_id']) not in emitted:
                    emit('issue_upserted',issue=reviewed_issue(issue))
            return record
        if limit_rule:
            emit('task_discovered',task_id='base:liability-limit',title='核查累计违约责任')
        limit_future = pool.submit(check_limit) if limit_rule else None
        published = set()
        publish_lock = Lock()
        def baseline_emit(kind,**data):
            if kind=='issue_upserted':
                issue = reviewed_issue(data['issue'])
                key = issue.setdefault('subject_key', issue['rule_id'])
                with publish_lock:
                    published.add(key)
                emit(kind, issue=issue)
                if issue['rule_id'] in ('RL-01', 'RL-02', 'RL-03') and issue['status'] == 'flag':
                    targets, _ = configured_draft_targets([issue], sources, citations)
                    submit_drafts(targets, [issue])
                return
            emit(kind,**data)

        try:
            result=baseline_review(settings,model,blocks,context,baseline_rules,bundle=bundle,policy_version=CONFIGURED_RULES_POLICY,retain_non_amount_facts=True,execution_callback=baseline_emit, model_call=model_call, review_evidence=snapshot)
            for issue in result['issues']:
                if issue.get('subject_key',issue['rule_id']) not in published:
                    baseline_emit('issue_upserted',issue=issue)

        except Exception as exc:
            error('baseline',exc)
            records=[{'rule_id':r['id'],'status':'insufficient_evidence','explanation':'本项核查未完成。','evidence':[],'execution_state':'failed','suggested_text':None} for r in baseline_rules]
            result = {'issues':[],'rule_results':records,'revision_proposals':[],'module_errors':[],'attachment_checks':[],'diagnostics':{}}
        represented = {issue['rule_id'] for issue in result['issues']}
        for record in result['rule_results']:
            if record['rule_id'] not in represented and record['rule_id'] not in published:
                baseline_emit('issue_upserted',issue=record)
        if limit_rule:
            try:
                record = limit_future.result()
            except Exception as exc:
                record = dict(rule_id=liability_limit.RULE_ID, title=liability_limit.TITLE,
                              status='insufficient_evidence', evidence=[], suggested_text=None,
                              execution_state='failed', explanation=error('liability_limit', exc))
                baseline_emit('issue_upserted',issue=record)
            traces.extend(limit_trace)
            record['provenance'] = {'origin':'configured_rule', 'rule_id':liability_limit.RULE_ID,
                                    'policy_version':limit_rule['version']}
            result['rule_results'].append(record)
        failed = any(r.get('execution_state') == 'failed' for r in result['rule_results'])
        for record in result['rule_results']:
            record['evidence_sources'] = snapshot.provenance(record)
        phase('rules',title,'failed' if failed or result.get('module_errors') else 'completed')
        return result

    if progress_callback:
        progress_callback('checking')
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        base = baseline(pool)
    proposals = []
    result = build_review_issues('', base['rule_results'], base['attachment_checks'],
                                 expected_rule_ids=[rule['id'] for rule in rules], additional_issues=[],split_liability=True)
    result['issues'] = [reviewed_issue(issue) for issue in result['issues']]
    targets, pending = configured_draft_targets(result['issues'],sources,citations)
    if targets or pending:
        if pending and not targets and not draft_jobs:
            phase('drafting',drafting_title,'running')
        by_event = {issue['event_id']:issue for issue in result['issues'] if issue.get('event_id')}

        submit_drafts(targets, result['issues'])
        rejections = dict(pending)
        source_text = {block['id']:block['text'] for block in blocks}
        owners = {}
        for eid, target in targets.items():
            for anchor in target['evidence']:
                block_id = sources.blocks[anchor['ref']]['id']
                owners.setdefault(block_id, set()).add(eid)

        accepted = []
        trace = []
        waiting = set(draft_jobs)
        order = {job:index for index, job in enumerate(draft_jobs)}
        while waiting:
            completed, waiting = wait(waiting, return_when=FIRST_COMPLETED)
            for job in sorted(completed, key=order.__getitem__):
                edits, problems, entries, *followups = job.result()
                if followups:
                    for repair in followups[0]:
                        order[repair] = len(order)
                    waiting.update(followups[0])
                edits = [edit for edit in edits if set(edit['event_ids']).issubset(targets)]
                accepted.extend(edits)
                rejections.update(problems)
                trace.extend(entries)
                per_block = Counter(edit['anchor']['block_id'] for edit in edits)
                for edit in edits:
                    block_id = edit['anchor']['block_id']
                    events = set(edit['event_ids'])
                    if per_block[block_id] != 1 or owners.get(block_id) != events:
                        continue
                    if any(sum(eid in item['event_ids'] for item in edits) != 1 for eid in events):
                        continue
                    for eid in edit['event_ids']:
                        ready = edit['state'] == 'draft'
                        plan = {'state':'ready' if ready else 'needs_confirmation',
                                'message':edit['rationale'] if ready else edit['message']}
                        emit('issue_upserted', issue={**by_event[eid], 'revision_plan':plan}, proposals=[edit])

        proposals, unresolved = consolidate_configured_proposals(accepted, source_text)
        rejections.update(unresolved)
        traces.extend(dict(entry,module='configured-drafting') for entry in trace)
        detect_overlaps(proposals)
        verify_combined_draft_effects(proposals, source_text)
        for proposal in proposals:
            if proposal['state'] in ('invalid', 'conflict'):
                rejections.update(dict.fromkeys(proposal['event_ids'], proposal['message']))
        related = {eid:p for p in proposals for eid in p['event_ids'] if p['state'] in ('draft','context_required')}
        required = set(targets)
        missing = required - set(related)
        if missing:
            errors.append({'module':'configured-drafting','code':'draft_missing',
                           'message':f'{len(missing)} 项意见尚缺少可用改文，详见对应意见。'})
        for issue in result['issues']:
            eid = issue.get('event_id')
            if eid in missing:
                issue['revision_plan'] = {'state':'failed','message':rejections.get(eid,'本条改文与其他修改位置冲突。')}
            elif eid in related and related[eid]['state']=='draft':
                issue['revision_plan'] = {'state':'ready','message':related[eid]['rationale']}
            elif eid in required or eid in pending:
                message = (related.get(eid,{}).get('message') or pending.get(eid) or '请核对本条改文的适用条件。')
                issue['revision_plan'] = {'state':'needs_confirmation','message':message}
        phase('drafting',drafting_title,'failed' if missing else 'completed',
              message=f'{len(required) + len(pending)} 条意见中，{len(related)} 条已有对应改文。'
                      + (f'另有 {len(missing) + len(pending)} 条待处理。' if missing or pending else ''))
    for issue in result['issues']:
        related = [p for p in proposals if issue.get('event_id') in p['event_ids']]
        if related or issue.get('revision_plan'):
            emit('issue_upserted',issue=issue,proposals=related)
    coverage = []
    for index, record in enumerate(result['rule_results'], 1):
        checks = record.get('coverage') or []
        state = record.get('execution_state')
        coverage.append({
            'rule_id': record['rule_id'], 'batch': index,
            'block_ids': list(dict.fromkeys([
                *(check['block_id'] for check in checks),
                *(anchor['block_id'] for anchor in record.get('evidence_sources', [])),
            ])),
            'state': state if state in ('failed', 'not_run') else record['status'],
            'items': checks,
        })
    emit('coverage_updated', coverage=coverage)
    result.update(revision_proposals=proposals, module_errors=errors + base['module_errors'],
                  attachment_checks=base['attachment_checks'], context_snapshot=context, review_coverage=coverage,
                  diagnostics={**base['diagnostics'], 'policy_version':CONFIGURED_RULES_POLICY,
                               'elapsed_seconds':round(time.monotonic()-started,3),
                               'attempts':base['diagnostics'].get('attempts', []) + traces})
    return result


def retry_draft(call, settings, model, role, mandate, target, issue, sources, version_id, emit, feedback):
    eid = target['event_id']
    anchor = target['evidence'][0]
    rejections = {eid: feedback}
    trace = []

    def validate(value):
        raw = ProposalResults(proposals=[dict(event_ids=[eid], ref=anchor['ref'], operation='replace',
            before_text=anchor['quote'], after_text=value.after_text, rationale=value.rationale,
            requires_context=bool(value.missing_context), missing_context=value.missing_context)])
        valid = validate_configured_drafts(raw, {eid:target}, sources, version_id, [issue], rejections=rejections)
        if not valid:
            raise fail(rejections[eid])
        return valid[0]

    emit('issue_upserted', issue={**issue, 'revision_plan':{'state':'generating','message':'正在根据原文单独补拟本条改文。'}})
    try:
        _, edit = call(replace(settings, max_output_tokens=8192, stream_callback=None), model,
            mandate + SINGLE_DRAFT_PROMPT, SingleClauseDraft,
            {'issue':target, 'target':anchor, 'our_party':role, 'validation_feedback':feedback},
            validate, time.monotonic() + 2 * settings.timeout, trace)
        emit('issue_upserted', issue={**issue, 'revision_plan':{'state':'generating',
             'message':'补拟改文已通过本条校验，等待核对跨条冲突。'}})
        return [edit], {}, trace
    except ExtractionError as exc:
        if exc.code == 'lease_lost':
            raise
        return [], {eid:rejections.get(eid) or exc.message}, trace


def draft_group(call, settings, model, role, mandate, targets, issues, sources, version_id, task_id, emit, *, feedback=None):
    title = '局部拟稿'
    messages = {'started':'等待模型响应','receiving':'正在接收候选改文','validating':'正在校验候选改文'}

    def update(kind, **_):
        if kind in messages:
            emit('task_started',task_id=task_id,title=title,message=messages[kind])

    options = replace(settings, max_output_tokens=8192, progress_only_stream=True, stream_callback=update)
    local_trace = []
    coordinated = coordinated_draft_groups(targets)
    payload = {'issues':list(targets.values()),'our_party':role}
    if coordinated:
        payload['coordinated_groups'] = [{'ref': ref, 'event_ids': ids} for ref, ids in coordinated.items()]
    if feedback:
        payload['validation_feedback'] = feedback

    def validate_output(output):
        reasons = {item.event_id:item.reason for item in output.pending if item.event_id in targets}
        edits = validate_configured_drafts(output,targets,sources,version_id,issues,rejections=reasons,coordinated=coordinated)
        missing = targets.keys() - {eid for edit in edits for eid in edit['event_ids']}
        if missing:
            local_trace.append({'stage':'draft_validation','status':'partial','unresolved':sorted(missing)})
        return edits, reasons

    prompt, reader = CONFIGURED_DRAFT_PROMPT, validate_output
    if all(target['rule_id'] == liability_limit.RULE_ID for target in targets.values()):
        units = draft_units(targets, coordinated)
        payload['draft_units'] = units
        prompt, reader = PATCH_DRAFT_PROMPT, DraftPatchReader(units, sources, validate_output)

    try:
        output, checked = call(options, model, mandate + prompt, ConfiguredDraftResults,
                         payload, reader,
                         time.monotonic() + 2 * settings.timeout, local_trace)
    except ExtractionError as exc:
        if exc.code == 'lease_lost':
            raise
        emit('task_failed', task_id=task_id, title=title, message=exc.message)
        return [], dict.fromkeys(targets,exc.message), local_trace
    edits, reasons = checked if checked is not None else validate_output(output)
    valid_ids = {eid for edit in edits for eid in edit['event_ids']}
    for issue in issues:
        message = '候选改文已通过本条校验，等待核对跨条冲突。' if issue['event_id'] in valid_ids else '本条候选改文待补核。'
        emit('issue_upserted', issue={**issue, 'revision_plan':{'state':'generating','message':message}})
    emit('task_completed', task_id=task_id, title=title, message=f'已核对 {len(targets)} 条意见的候选改文。')
    return edits, reasons, local_trace

