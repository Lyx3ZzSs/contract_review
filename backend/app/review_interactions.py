"""Supplement → immutable snapshot → queued recheck, committed atomically."""
import json
from pathlib import Path
from hashlib import sha256
from uuid import uuid4
from fastapi import HTTPException
from pydantic import Field
from .models import Model,ExtractionCreate
from .materials import encoded,now,material,current_bundle,ensure_bundle,save_bundle,is_stale


def implementation_hash():
    root=Path(__file__).parent
    return sha256(b''.join((root/name).read_bytes() for name in ('interactive_review.py','attachment_review.py','review_issues.py','structured_review.py','reference_index.py','amount_review.py','field_review.py'))).hexdigest()


class Supplement(Model):
    idempotency_key: str = Field(min_length=1,max_length=100)
    expected_bundle_id: str | None = None
    material_version_ids: list[str] | None = Field(default=None,max_length=20)
    linked_block_ids: list[str] | None = Field(default=None,max_length=200)
    statement: str = Field(default='',max_length=5000)
    actor: str = Field(min_length=1,max_length=100)


def get_issue(db,rid,iid):
    row=db.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
    if not row: raise HTTPException(404,'审查批次不存在')
    run=json.loads(row['payload'])
    issue=next((i for i in run.get('issues',run['findings']) if i['id']==iid),None)
    if not issue: raise HTTPException(404,'审查事项不存在')
    return run,issue


def register(app,store):
    @app.post('/api/v1/runs/{rid}/issues/{iid}/supplements',status_code=202)
    def supplement(rid:str,iid:str,body:Supplement):
        from .review_jobs import enqueue_review
        with store.connect() as db:
            run,issue=get_issue(db,rid,iid)
            cid=run['contract_id']
            fingerprint=sha256(encoded({'run_id':rid,'issue_id':iid,**body.model_dump()}).encode()).hexdigest()
            old=db.execute('SELECT * FROM supplement_requests WHERE contract_id=? AND idem=?',(cid,body.idempotency_key)).fetchone()
            if old:
                if old['request_hash']!=fingerprint: raise HTTPException(409,'提交标识已用于不同补充内容')
                return json.loads(old['payload'])
            if is_stale(db,run): raise HTTPException(409,'正文或资料包已变化，请刷新后补充')
            if run['status'] not in ('completed','needs_input'): raise HTTPException(409,'本轮尚无可补充的审查结果')
            active=current_bundle(db,cid)
            if body.expected_bundle_id!=(active['id'] if active else None): raise HTTPException(409,'资料包已变化，请刷新后补充')
            bundle=active or ensure_bundle(db,cid,run['document_version_id'])
            ids=body.material_version_ids if body.material_version_ids is not None else bundle['material_version_ids']
            mats=[material(db,cid,mid) for mid in ids]
            doc=db.execute('SELECT parsed FROM versions WHERE id=?',(run['document_version_id'],)).fetchone()
            main_blocks=json.loads(doc['parsed'])['blocks']
            block_owners={b['id']:None for b in main_blocks}
            block_owners.update({b['id']:m['id'] for m in mats for b in m['blocks']})
            if any(b not in block_owners for b in body.linked_block_ids or []): raise HTTPException(422,'关联段落不属于当前正文或所选材料')
            assertions=list(bundle['assertions'])
            if body.statement:
                assertions.append({'id':str(uuid4()),'origin':'user_statement','statement':body.statement,'actor':body.actor,
                                   'issue_id':iid,'subject_key':issue.get('subject_key',issue['rule_id']),'created_at':now()})
            if len(assertions)>200: raise HTTPException(413,'补充说明过多，请整理资料后发起新审查')
            links=[l for l in bundle['links'] if not l.get('target_material_version_id') or l['target_material_version_id'] in ids]
            name=issue.get('attachment_name') or issue.get('reference_name')
            if body.linked_block_ids and not name: raise HTTPException(422,'仅具体附件问题支持关联附件内容')
            if body.linked_block_ids is not None and name:
                links=[l for l in links if l['reference_name']!=name]
                for owner in dict.fromkeys(block_owners[b] for b in body.linked_block_ids):
                    links.append({'reference_name':name,'target_material_version_id':owner,
                                  'target_block_ids':[b for b in body.linked_block_ids if block_owners[b]==owner],
                                  'origin':'user_candidate','actor':body.actor})
            new=save_bundle(db,cid,run['document_version_id'],ids,assertions,links)
            queued=enqueue_review(db,cid,ExtractionCreate(document_version_id=run['document_version_id'],idempotency_key='supplement:'+new['id'],model=run.get('model')),
                                  bundle=new,parent_run_id=rid,interactive=True)
            result={'bundle_id':new['id'],'review_id':queued['id'],'parent_run_id':rid}
            db.execute('INSERT INTO supplement_requests VALUES(?,?,?,?)',(cid,body.idempotency_key,fingerprint,encoded(result)))
            return result

    @app.get('/api/v1/runs/{rid}/issues/{iid}/history')
    def history(rid:str,iid:str):
        with store.connect() as db:
            run,issue=get_issue(db,rid,iid)
            key=issue.get('subject_key')
            items=[]
            for row in db.execute('SELECT payload FROM runs WHERE contract_id=? AND created_at<=? ORDER BY created_at',(run['contract_id'],run['created_at'])):
                previous=json.loads(row['payload'])
                matches=[i for i in previous.get('issues',previous['findings']) if (key and i.get('subject_key')==key and i['rule_id']==issue['rule_id']) or i['id']==iid]
                # Ambiguous matches never imply automatic continuity.
                if len(matches)!=1: continue
                from .issue_presentation import enrich_run_presentation
                found=enrich_run_presentation({'findings':[matches[0]]})['findings'][0]
                decisions=[json.loads(d[0]) for d in db.execute('SELECT payload FROM decisions WHERE run_id=? AND finding_id=? ORDER BY id',(previous['id'],found['id']))]
                items.append({'run_id':previous['id'],'issue':found,'created_at':previous['created_at'],'decisions':decisions})
            assertions=[]
            if run.get('material_bundle_id'):
                bundle=json.loads(db.execute('SELECT payload FROM material_bundles WHERE id=?',(run['material_bundle_id'],)).fetchone()[0])
                assertions=[a for a in bundle['assertions'] if a.get('subject_key')==key]
            return {'items':items,'assertions':assertions}
