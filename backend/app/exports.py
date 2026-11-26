"""Immutable export snapshots with retryable, local document generation."""
from datetime import datetime
from zoneinfo import ZoneInfo
from hashlib import sha256
import json
import logging
import re
from typing import Literal
from urllib.parse import quote
from uuid import uuid4
from fastapi import HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from .export_content import changes, report_content, final_issues, clean

logger=logging.getLogger(__name__)
KINDS={'contract':'当前合同','changes':'本次修改说明','opinions':'完整审查意见书'}
class ExportRequest(BaseModel):
    kind:Literal['contract','changes','opinions']
    document_version_id:str
    run_id:str|None=None
    idempotency_key:str=Field(min_length=1,max_length=100)


def required(db,table,ident):
    row=db.execute(f'SELECT * FROM {table} WHERE id=?',(ident,)).fetchone()
    if row is None:raise HTTPException(404,'导出所需记录不存在')
    return dict(row)


def capture(db,cid,vid,rid):
    contract=json.loads(required(db,'contracts',cid)['payload']);current=required(db,'versions',vid)
    if current['contract_id']!=cid:raise HTTPException(409,'文档不属于当前合同')
    runrow=required(db,'runs',rid) if rid else None
    if runrow and runrow['contract_id']!=cid:raise HTTPException(409,'审查轮次不属于当前合同')
    run=json.loads(runrow['payload']) if runrow else None
    if run:run['status']=runrow['status']
    base=required(db,'versions',runrow['version_id']) if runrow else dict(db.execute('SELECT * FROM versions WHERE contract_id=? ORDER BY revision LIMIT 1',(cid,)).fetchone())
    decisions=[json.loads(r[0]) for r in db.execute('SELECT payload FROM decisions WHERE run_id=? ORDER BY id',(rid,))] if rid else []
    # Honor existing finalized snapshots when explicitly exporting that historical round.
    saved=db.execute('SELECT payload FROM results WHERE run_id=?',(rid,)).fetchone() if rid else None
    if saved:
        frozen=json.loads(saved[0]);run=frozen.get('review_snapshot') or run;decisions=frozen.get('decisions',decisions)
    elif run:
        from .review_jobs import restore_overview
        restore_overview(db,run)
    ops=[json.loads(r[0]) for r in db.execute('SELECT payload FROM proposal_operations WHERE contract_id=? ORDER BY created_at',(cid,))]
    now=datetime.now(ZoneInfo('Asia/Shanghai'))
    result={'contract_title':clean(contract.get('title') or current['filename']), 'position':clean(((run or {}).get('context_snapshot') or {}).get('our_party') or contract.get('our_party')),
        'contract_id':cid,'document_version_id':vid,'base_version_id':base['id'],'base_revision':base['revision'],'current_revision':current['revision'],
        'run':run,'decisions':decisions,'operations':ops,'created_at':now.isoformat(),'display_time':now.strftime('%Y年%m月%d日 %H:%M'),
        'document_sha256':current['sha256'],'base_sha256':base['sha256'],
        'round_number':db.execute('SELECT COUNT(*) FROM runs WHERE contract_id=? AND rowid<=(SELECT rowid FROM runs WHERE id=?)',(cid,rid)).fetchone()[0] if rid else None}
    from .subject_review import export_subjects
    result['subjects']=export_subjects(db,cid,vid)
    return result,base,current


def availability(snapshot,base,current):
    delta=changes(base,current,snapshot['operations'],snapshot['run'] or {})
    count=len(delta['modifications'])+len(delta['comments'])+len(delta['removed_comments'])+len(delta['other_changes'])
    run=snapshot['run'];reason='' if run and run.get('status') in ('completed','needs_input') else '本轮结果正在生成' if run and run.get('status') in ('queued','running') else '本轮暂无可导出的审查结果'
    return {'modifications':len(delta['modifications']),'comments':len(delta['comments']),'removed_comments':len(delta['removed_comments']),
        'other_changes':len(delta['other_changes']),'issues':len(final_issues(run)) if run else 0,'changes_available':count>0,'changes_reason':'' if count else '当前暂无正文、批注或其他文档变化',
        'opinions_available':not reason,'opinions_reason':reason,'base_revision':base['revision'],'current_revision':current['revision'],
        'round_number':snapshot['round_number'],'document_version_id':current['id'],'base_version_id':base['id']},delta


def public(row):
    snap=json.loads(row['snapshot'])
    return {'id':row['id'],'kind':snap['kind'],'state':row['state'],'filename':row['filename'],'created_at':snap['created_at'],
            'document_version_id':snap['document_version_id'],'base_version_id':snap['base_version_id'],'error':row['error'],
            'download_url':f"/api/v1/exports/{row['id']}/file" if row['state']=='ready' else None}


def register(app,store):
    @app.get('/api/v1/contracts/{cid}/export-options')
    def options(cid:str,document_version_id:str,run_id:str|None=None):
        with store.connect() as db:snapshot,base,current=capture(db,cid,document_version_id,run_id)
        return availability(snapshot,base,current)[0]

    @app.post('/api/v1/contracts/{cid}/exports',status_code=201)
    def prepare(cid:str,body:ExportRequest):
        fingerprint=sha256(json.dumps(body.model_dump(exclude={'idempotency_key'}),sort_keys=True).encode()).hexdigest()
        with store.connect() as db:
            existing=db.execute('SELECT * FROM document_exports WHERE contract_id=? AND idem=?',(cid,body.idempotency_key)).fetchone()
            if existing:
                if existing['request_hash']!=fingerprint:raise HTTPException(409,'导出请求已变化，请重新选择')
                return public(existing)
            snapshot,base,current=capture(db,cid,body.document_version_id,body.run_id)
            # Only snapshot source records in the transaction. Rendering runs after release.
        opts,delta=availability(snapshot,base,current)
        if body.kind=='changes' and not opts['changes_available']:raise HTTPException(409,opts['changes_reason'])
        if body.kind=='opinions' and not opts['opinions_available']:raise HTTPException(409,opts['opinions_reason'])
        eid=str(uuid4());snapshot.update(id=eid,kind=body.kind,changes=delta)
        snapshot['report']=report_content(snapshot,base,current) if body.kind!='contract' else {}
        name=re.sub(r'[\\/:*?"<>|\x00-\x1f]','_',snapshot['contract_title']).removesuffix('.docx')[:100]
        filename=f"{name}_{KINDS[body.kind]}_{datetime.fromisoformat(snapshot['created_at']).strftime('%Y%m%d_%H%M%S')}_{eid[:6]}.docx"
        content=current['content'] if body.kind=='contract' else None
        with store.connect() as db:
            # Concurrent identical requests have one immutable export identity.
            db.execute('INSERT OR IGNORE INTO document_exports(id,contract_id,idem,request_hash,snapshot,state,filename,content,error) VALUES(?,?,?,?,?,?,?,?,?)',
                       (eid,cid,body.idempotency_key,fingerprint,json.dumps(snapshot,ensure_ascii=False),'ready' if content else 'pending',filename,content,None))
            row=db.execute('SELECT * FROM document_exports WHERE contract_id=? AND idem=?',(cid,body.idempotency_key)).fetchone()
            if row['request_hash']!=fingerprint:raise HTTPException(409,'导出请求已变化，请重新选择')
            return public(row)

    @app.post('/api/v1/exports/{eid}/generate')
    def render(eid:str):
        with store.connect() as db:
            row=required(db,'document_exports',eid)
            if row['state']=='ready':return public(row)
            snapshot=json.loads(row['snapshot'])
        try:
            from .export_docx import generate
            content=generate(snapshot)
        except Exception:
            logger.exception('Export generation failed: %s',eid)
            with store.connect() as db:db.execute("UPDATE document_exports SET state='failed',error=? WHERE id=? AND state!='ready'",('文件生成失败，请重试',eid))
            raise HTTPException(500,'文件生成失败，请重试；本次导出版本已保留')
        with store.connect() as db:
            db.execute("UPDATE document_exports SET state='ready',content=?,error=NULL WHERE id=? AND state!='ready'",(content,eid))
            return public(required(db,'document_exports',eid))

    @app.get('/api/v1/exports/{eid}')
    def status(eid:str):
        with store.connect() as db:return public(required(db,'document_exports',eid))

    @app.get('/api/v1/exports/{eid}/file')
    def download(eid:str):
        with store.connect() as db:row=required(db,'document_exports',eid)
        if row['state']!='ready':raise HTTPException(409,'文件尚未生成，请重试生成')
        return Response(row['content'],media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            headers={'Content-Disposition':f"attachment; filename=export.docx; filename*=UTF-8''{quote(row['filename'])}", 'Cache-Control':'private, no-store'})
