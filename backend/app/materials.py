"""Received files and immutable material packages are distinct from attachment references."""
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from .parser import MAX_FILE, parse_docx


def now(): return datetime.now(timezone.utc).isoformat()
def encoded(value): return json.dumps(value,ensure_ascii=False,sort_keys=True)


def require_contract(db,cid):
    if not db.execute('SELECT id FROM contracts WHERE id=?',(cid,)).fetchone():
        raise HTTPException(404,'合同不存在')


def current_bundle(db,cid):
    row=db.execute('SELECT b.payload FROM material_bundles b JOIN active_material_bundles a ON b.id=a.bundle_id WHERE a.contract_id=?',(cid,)).fetchone()
    return json.loads(row['payload']) if row else None


def material(db,cid,mid):
    row=db.execute('SELECT payload FROM material_versions WHERE contract_id=? AND id=?',(cid,mid)).fetchone()
    if not row: raise HTTPException(404,'材料不存在或不属于此合同')
    return json.loads(row['payload'])


def save_bundle(db,cid,version_id,ids,assertions=None,links=None):
    ids=list(dict.fromkeys(ids))
    if len(ids)>20: raise HTTPException(413,'单份资料包最多20个文件')
    mats=[material(db,cid,mid) for mid in ids]
    if sum(m['size'] for m in mats)>100*1024*1024: raise HTTPException(413,'资料包超过100MB')
    content={'document_version_id':version_id,'material_version_ids':ids,'assertions':assertions or [],'links':links or []}
    value={**content,'id':str(uuid4()),'contract_id':cid,'content_hash':sha256(encoded(content).encode()).hexdigest(),'created_at':now()}
    db.execute('INSERT INTO material_bundles VALUES(?,?,?,?,?)',(value['id'],cid,version_id,encoded(value),value['created_at']))
    db.execute('INSERT INTO active_material_bundles VALUES(?,?) ON CONFLICT(contract_id) DO UPDATE SET bundle_id=excluded.bundle_id',(cid,value['id']))
    return value


def ensure_bundle(db,cid,version_id):
    old=current_bundle(db,cid)
    if old and old['document_version_id']==version_id: return old
    # Body anchors belong only to their original version; external-file links remain valid.
    return save_bundle(db,cid,version_id,old['material_version_ids'] if old else [],
                       old['assertions'] if old else [],[l for l in old['links'] if l.get('target_material_version_id')] if old else [])


def load_bundle(db,cid,bid):
    row=db.execute('SELECT payload FROM material_bundles WHERE contract_id=? AND id=?',(cid,bid)).fetchone()
    if not row: raise HTTPException(404,'资料包不存在')
    value=json.loads(row['payload'])
    value['materials']=[material(db,cid,mid) for mid in value['material_version_ids']]
    return value


def is_stale(db,value):
    row=db.execute('SELECT id FROM versions WHERE contract_id=? ORDER BY revision DESC LIMIT 1',(value['contract_id'],)).fetchone()
    if not row or row['id']!=value['document_version_id']: return True
    active=current_bundle(db,value['contract_id'])
    if active and active['document_version_id']==row['id'] and value.get('material_bundle_id')!=active['id']:
        return True
    if value.get('context_snapshot'):
        contract=json.loads(db.execute('SELECT payload FROM contracts WHERE id=?',(value['contract_id'],)).fetchone()[0])
        if value.get('review_prompt_version') in ('review-context-v1','review-events-v1','review-events-v2'):
            from .review_context import normalize_review_context
            saved=normalize_review_context(value['context_snapshot']);current=normalize_review_context(contract)
            if any(saved.get(k)!=current.get(k) for k in ('our_party_code','contract_type_declared','stage')):return True
        elif value['context_snapshot']!={k:contract[k] for k in ('contract_type','our_party','stage')}: return True
    return False


def register(app,store):
    @app.post('/api/v1/contracts/{cid}/materials',status_code=201)
    async def upload(cid:str,file:UploadFile=File(...),idempotency_key:str=Form(...,min_length=1,max_length=100)):
        name=Path((file.filename or '材料').replace('\\','/')).name[:300]
        data=await file.read(MAX_FILE+1)
        await file.close()
        if len(data)>MAX_FILE: raise HTTPException(413,'单份材料超过20MB')
        if not data: raise HTTPException(422,'材料内容为空')
        digest=sha256(data).hexdigest()
        fingerprint=sha256(encoded({'filename':name,'sha256':digest}).encode()).hexdigest()
        mid=str(uuid4())
        parsed={'blocks':[],'limitations':['此文件格式尚未解析，内容需人工核验。']}
        status='unsupported'
        if name.lower().endswith('.docx'):
            try:
                parsed=parse_docx(data)
                # Picture-bearing DOCX is readable only in part; do not certify completeness.
                status='partial' if parsed.get('image_block_ids') else 'parsed'
            except Exception as exc:
                if isinstance(exc,ValueError) and '超过限制' in str(exc):raise HTTPException(413,'DOCX解压内容超过限制') from exc
                status='failed'
                parsed={'blocks':[],'limitations':['DOCX解析失败，未把空内容视为已提供附件；请核对文件或另行转换。']}
        for b in parsed['blocks']: b['id']=mid+':'+b['id']
        value={'id':mid,'contract_id':cid,'filename':name,'sha256':digest,'size':len(data),
               'media_type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document' if status in ('parsed','partial') else 'application/octet-stream',
               'parse_status':status,'blocks':parsed['blocks'],'limitations':parsed['limitations'],'created_at':now()}
        with store.connect() as db:
            require_contract(db,cid)
            old=db.execute('SELECT request_hash,payload FROM material_versions WHERE contract_id=? AND idem=?',(cid,idempotency_key)).fetchone()
            if old:
                if old['request_hash']!=fingerprint: raise HTTPException(409,'幂等键已用于不同材料')
                return json.loads(old['payload'])
            db.execute('INSERT INTO material_versions VALUES(?,?,?,?,?,?,?)',(mid,cid,idempotency_key,fingerprint,data,encoded(value),value['created_at']))
        return value

    @app.get('/api/v1/contracts/{cid}/materials')
    def listing(cid:str):
        with store.connect() as db:
            require_contract(db,cid)
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM material_versions WHERE contract_id=? ORDER BY created_at',(cid,))]

    @app.get('/api/v1/contracts/{cid}/materials/{mid}/file')
    def download(cid:str,mid:str):
        with store.connect() as db:
            value=material(db,cid,mid)
            data=db.execute('SELECT content FROM material_versions WHERE id=?',(mid,)).fetchone()[0]
            return Response(data,media_type=value['media_type'],headers={'Content-Disposition':f'attachment; filename="{mid}.bin"'})

    @app.get('/api/v1/contracts/{cid}/material-bundles/{bid}')
    def bundle(cid:str,bid:str):
        with store.connect() as db: return load_bundle(db,cid,bid)
