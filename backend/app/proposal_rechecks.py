"""Version-bound, read-only applicability receipts. Never rewrite review findings."""
import json
import time
from hashlib import sha256
from uuid import uuid4
from fastapi import HTTPException
from pydantic import BaseModel
from .document_versions import current
from .materials import current_bundle
from .review_context import normalize_review_context
from .llm import Settings, ExtractionError
from .proposal_recheck_model import verify_applicability


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def semantics(parsed):
    # Version-scoped IDs are not semantic identity. Numbering and table placement are.
    return [{k:v for k,v in b.items() if k != 'id'} for b in parsed['blocks']]


def operation_base(previous, rid, head):
    edges = {}
    for op in previous:
        if op['run_id'] != rid or op['state'] not in ('applied', 'reverted'):
            continue
        if op.get('after_version_id'):
            edges[op['after_version_id']] = op['before_version_id']
        if op.get('reverted_version_id'):
            edges[op['reverted_version_id']] = op['before_version_id']
    seen = set()
    while head in edges and head not in seen:
        seen.add(head)
        head = edges[head]
    return head


def context_key(db, row, value, source):
    contract = json.loads(db.execute('SELECT payload FROM contracts WHERE id=?', (row['contract_id'],)).fetchone()[0])
    context = normalize_review_context(contract)
    original = normalize_review_context(value.get('context_snapshot') or contract)
    reason = ''
    if any(context.get(k) != original.get(k) for k in ('our_party_code', 'stage')):
        reason = '审查立场或履约阶段已变化，请重新审查'
    active = current_bundle(db, row['contract_id'])
    saved = db.execute('SELECT payload FROM material_bundles WHERE id=? AND contract_id=?',
                       (value.get('material_bundle_id'), row['contract_id'])).fetchone()
    original_bundle = json.loads(saved[0]) if saved else None
    def contents(bundle):
        return {k:(bundle or {}).get(k, []) for k in ('material_version_ids', 'assertions', 'links')}
    if contents(active) != contents(original_bundle):
        reason = '审查资料或补充说明已变化，请重新审查'
    frozen = {k:value.get(k) for k in ('revision_proposals','issues','findings','context_snapshot',
        'material_bundle_id','case_guidance_snapshot','model','review_prompt_version')}
    data = {'review':frozen,'context':{k:context.get(k) for k in ('our_party_code','stage')},'materials':contents(active)}
    # Earlier checks skipped plain insert drafts. Recheck affected reviews once
    # with the anchor quote available to the reviewer.
    if any(p.get('operation') == 'insert' and not p.get('after_text', '').startswith(('\n', '\r\n'))
           for p in value.get('revision_proposals', [])):
        data['insert_anchor_version'] = 2
    table_ids = {b['id'] for b in source['blocks'] if b.get('table_location')}
    if any((p.get('anchor') or {}).get('block_id') in table_ids for p in value.get('revision_proposals', [])):
        data['table_anchor_version'] = 1
    return sha256(encoded(data).encode()).hexdigest(), reason


def assessment(db, row, head, value, previous):
    base = operation_base(previous,row['id'],head['id'])
    source = json.loads(db.execute('SELECT parsed FROM versions WHERE id=?',(row['version_id'],)).fetchone()[0])
    key, blocked = context_key(db,row,value,source)
    baseline = json.loads(db.execute('SELECT parsed FROM versions WHERE id=?',(base,)).fetchone()[0])
    result = {'status':'not_required','message':'','can_retry':False,'document_version_id':head['id'],
              'base_version_id':base,'context_hash':key,'results':[]}
    if row['status'] not in ('completed','needs_input'):
        blocked = '审查尚未完成'
    if blocked:
        return {**result,'status':'blocked','message':blocked}
    if base == row['version_id'] or semantics(source) == semantics(baseline):
        return result
    found = db.execute('SELECT payload FROM proposal_rechecks WHERE run_id=? AND version_id=? AND context_hash=?',
                       (row['id'],base,key)).fetchone()
    if not found:
        return {**result,'status':'required','message':'正文已更新，将复核现有建议在当前条款中的适用性'}
    receipt = json.loads(found[0])
    result.update({k:receipt[k] for k in ('status','message','results')})
    result['check_id'] = receipt['id']
    if result['status']=='running' and receipt['lease_until'] < time.time():
        result.update(status='failed',message='局部复核已超时或服务中断，可重试；未自动放开旧建议')
    result['can_retry'] = result['status']=='failed'
    return result


def public_assessment(value):
    return {k:v for k,v in value.items() if k not in ('context_hash','results','base_version_id')}


def per_proposal(check, proposal, completed):
    if completed['revision'] or proposal.get('state') not in ('draft','context_required'):
        return {'status':'not_required','reason':''}
    if check['status']=='completed':
        result = next((r for r in check['results'] if r['proposal_id']==(proposal.get('proposal_id') or proposal['id'])), None)
        if result:
            return {'status':result['status'],'reason':result['reason']}
        return {'status':'needs_revision','reason':'该建议的目标原文无法复用，请核对当前条款后更新建议'}
    return {'status':check['status'],'reason':check['message']}


class RecheckRequest(BaseModel):
    expected_version_id: str
    retry: bool = False


def register(app, store):
    @app.post('/api/v1/runs/{rid}/proposal-rechecks')
    def recheck(rid: str, body: RecheckRequest):
        # Read and reserve under a short transaction, then release SQLite while the model runs.
        from .proposal_operations import operations, progress, locate_target, action_reasons
        with store.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
            if not row:
                raise HTTPException(404,'审查不存在')
            row = dict(row)
            head = current(db,row['contract_id'])
            if head['id'] != body.expected_version_id:
                raise HTTPException(409,'正文版本已变化，请使用当前保存版本复核')
            value = json.loads(row['payload'])
            previous = operations(db,row['contract_id'])
            check = assessment(db,row,head,value,previous)
            if check['status'] in ('not_required','completed','running','blocked') or (check['status']=='failed' and not body.retry):
                return public_assessment(check)
            if any(o['state']=='prepared' for o in previous):
                raise HTTPException(409,'请先确认上一操作的保存结果，再复核当前建议')
            source = json.loads(db.execute('SELECT parsed FROM versions WHERE id=?',(row['version_id'],)).fetchone()[0])
            parsed = json.loads(head['parsed'])
            proposals = []
            issues = value.get('issues') or value.get('findings') or []
            for p in value.get('revision_proposals',[]):
                pid = p.get('proposal_id') or p['id']
                completed = progress(previous,rid,pid)
                if completed['revision'] or action_reasons(value,p)['MODIFY']:
                    continue
                try:
                    target = locate_target(p,source['blocks'],parsed['blocks'],row['version_id'])
                except HTTPException:
                    continue
                related = [i for i in issues if i.get('event_id') in p.get('event_ids',[])]
                proposals.append({**{k:p.get(k) for k in ('before_text','after_text','rationale','message','state')},
                    'operation':p.get('operation'),'anchor_quote':target['block']['text'][target['start']:target['end']],
                    'proposal_id':pid,'target_ref':f"c{target['index']+1}",
                    'requirements':[r for i in related for r in (i.get('revision_requirements') or [])],
                    'related_findings':[{k:i.get(k) for k in ('title','explanation','rule_id')} for i in related]})
            baseline = db.execute('SELECT * FROM versions WHERE id=?',(check['base_version_id'],)).fetchone()
            # New known operations are included in current_blocks, but cannot authorize other unadopted edits.
            payload = {'previous_blocks':[{'id':f's{i+1}',**{k:v for k,v in b.items() if k!='id'}} for i,b in enumerate(source['blocks'])],
                'current_blocks':[{'id':f'c{i+1}',**{k:v for k,v in b.items() if k!='id'}} for i,b in enumerate(parsed['blocks'])],
                'proposals':proposals,'context':value.get('context_snapshot') or {},'confirmed_case_guidance':[],
                'expired_case_guidance':value.get('case_guidance_snapshot') or None}
            settings = Settings.load()
            receipt = {'id':str(uuid4()),'status':'running','message':'正在核对正文变化对现有建议的影响',
                       'results':[],'source_version_id':row['version_id'],'evaluated_version_id':head['id'],
                       'base_version_id':baseline['id'],'context_hash':check['context_hash'],
                       'lease_until':time.time()+2*settings.timeout+30,'created_at':time.time()}
            db.execute('INSERT INTO proposal_rechecks VALUES(?,?,?,?,?) ON CONFLICT(run_id,version_id,context_hash) DO UPDATE SET id=excluded.id,payload=excluded.payload',
                       (receipt['id'],rid,check['base_version_id'],check['context_hash'],encoded(receipt)))
        try:
            results, trace = verify_applicability(settings,value.get('model') or settings.model,payload) if proposals else ([],[])
            receipt.update(status='completed',message='当前建议适用性复核完成；原审查结论与待确认事项保持不变',results=results,trace=trace)
        except ExtractionError as exc:
            receipt.update(status='failed',message=exc.message,code=exc.code,trace=getattr(exc,'attempts',[]))
        except Exception:
            receipt.update(status='failed',message='局部复核未完成，可重试；未自动放开旧建议',code='recheck_failed')
        receipt['finished_at'] = time.time()
        with store.connect() as db:
            # Only the current lease owner can publish; late old attempts cannot overwrite a retry.
            db.execute('UPDATE proposal_rechecks SET payload=? WHERE id=?',(encoded(receipt),receipt['id']))
            latest = db.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
            head = current(db,row['contract_id'])
            result = assessment(db,latest,head,json.loads(latest['payload']),operations(db,row['contract_id']))
            return public_assessment(result)
