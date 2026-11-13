"""Single-writer Docs API integration; document versions remain business-owned."""
import base64
import hmac
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from urllib.parse import urlsplit
from typing import Literal
import httpx
from pydantic import BaseModel, Field
from fastapi import HTTPException, Request
from fastapi.responses import Response
from .parser import parse_docx, MAX_FILE
from .document_versions import current, commit_version

BUILD='10.0.0-labesign9'
def now(): return datetime.now(timezone.utc).isoformat()
def dump(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def secret():
    value=os.getenv('RIXIN_ONLYOFFICE_SECRET','')
    path=os.getenv('RIXIN_ONLYOFFICE_SECRET_FILE','')
    if not value and path: value=Path(path).read_text().strip().split('=',1)[-1]
    if not value: raise HTTPException(503,'文档服务密钥未配置')
    return value.encode()
def b64(b): return base64.urlsafe_b64encode(b).rstrip(b'=').decode()
def sign(data):
    msg=b64(b'{"alg":"HS256","typ":"JWT"}')+'.'+b64(dump(data).encode())
    return msg+'.'+b64(hmac.new(secret(),msg.encode(),hashlib.sha256).digest())
def verify(token):
    try:
        head,body,sig=token.split('.')
        header=json.loads(base64.urlsafe_b64decode(head+'='*(-len(head)%4)))
        if header.get('alg')!='HS256': raise ValueError()
        expected=b64(hmac.new(secret(),(head+'.'+body).encode(),hashlib.sha256).digest())
        if not hmac.compare_digest(expected,sig): raise ValueError()
        claims=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
        if claims.get('exp',time.time()+1)<time.time(): raise ValueError()
        return claims
    except (ValueError,KeyError,TypeError): raise HTTPException(403,'文档服务签名无效或已过期')
def docs_url(): return os.getenv('RIXIN_ONLYOFFICE_INTERNAL_URL','http://127.0.0.1:18083').rstrip('/')
def send_command(body):
    r=httpx.post(docs_url()+'/coauthoring/CommandService.ashx',json={**body,'token':sign(body)},timeout=15)
    r.raise_for_status(); return r.json()
def download_document(url):
    base=urlsplit(docs_url()); target=urlsplit(url)
    if (target.scheme,target.netloc)!=(base.scheme,base.netloc) or target.username or target.password:
        raise ValueError('回调文件地址不属于指定文档服务')
    with httpx.stream('GET',url,timeout=30,follow_redirects=False) as response:
        response.raise_for_status(); data=bytearray()
        for chunk in response.iter_bytes():
            data.extend(chunk)
            if len(data)>MAX_FILE: raise ValueError('DOCX超过20MB')
    return bytes(data)
def get_session(db,sid):
    s=db.execute('SELECT * FROM editor_sessions WHERE id=?',(sid,)).fetchone()
    if not s: raise HTTPException(404,'编辑会话不存在')
    return dict(s)
def finalized(db,cid,vid):
    result=db.execute('SELECT results.payload FROM results JOIN runs ON runs.id=results.run_id WHERE runs.contract_id=? AND runs.version_id=? ORDER BY results.created_at DESC LIMIT 1',(cid,vid)).fetchone()
    if not result:return False
    state=db.execute('SELECT payload FROM draft_states WHERE contract_id=?',(cid,)).fetchone()
    reopened=(json.loads(state[0]).get('review',{}).get('reopenedAt','') if state else '')
    return reopened<=json.loads(result[0])['created_at']
def candidate(db,sid,data,reason):
    db.execute('INSERT OR IGNORE INTO editor_snapshot_candidates VALUES(?,?,?,?,?,?)',(str(uuid4()),sid,hashlib.sha256(data).hexdigest(),data,reason,now()))
def put_request(db,r): db.execute('UPDATE editor_save_requests SET payload=? WHERE id=?',(dump(r),r['id']))
def reconcile_request(db,r):
    if r['state']=='pending' and time.time()-datetime.fromisoformat(r['created_at']).timestamp()>60:
        r.update(state='unconfirmed',error_code='callback_timeout');put_request(db,r)
    return r

class OpenSession(BaseModel):
    expected_version_id:str
    client_instance_id:str=Field(min_length=1,max_length=100)
    idempotency_key:str=Field(min_length=1,max_length=100)
class SaveRequest(BaseModel):
    idempotency_key:str=Field(min_length=1,max_length=100)
    expected_head_version_id:str
    purpose:Literal['review','export','leave','finalize','autosave']='review'
class CloseSession(BaseModel):
    document_version_id:str

def present(db,s):
    v=db.execute('SELECT filename,sha256 FROM versions WHERE id=?',(s['base_version_id'],)).fetchone()
    internal=os.getenv('RIXIN_ONLYOFFICE_APP_URL','http://host.docker.internal:8011').rstrip('/')
    readonly=s['state']=='view'
    config={'documentType':'word','type':'desktop','width':'100%','height':'100%',
      'document':{'fileType':'docx','key':s['document_key'],'title':v['filename'],
       'url':internal+f"/api/v1/editor-sessions/{s['id']}/file?token="+sign({'sid':s['id'],'vid':s['base_version_id'],'exp':time.time()+86400}),
       'permissions':{'edit':not readonly,'review':not readonly,'comment':not readonly,'download':True,'chat':False}},
      'editorConfig':{'lang':'zh-CN','mode':'view' if readonly else 'edit','callbackUrl':internal+f"/api/v1/onlyoffice/callback/{s['id']}",
       'user':{'id':s['client_id'],'name':'法务审阅员'},
       'customization':{'forcesave':False,'autosave':True,'feedback':False,'help':False,'compactHeader':True,'compactToolbar':False,'toolbarHideFileName':True,'hideRulers':True,'hideRightMenu':True,'labSingleToolbar':True,'uiTheme':'theme-light','zoom':100,'review':{'trackChanges':True}}}}
    config['token']=sign(config)
    return {**s,'read_only_reason':('finalized' if finalized(db,s['contract_id'],s['base_version_id']) else 'occupied') if readonly else None,'config':config,'script_url':os.getenv('RIXIN_ONLYOFFICE_PUBLIC_URL','http://127.0.0.1:18083').rstrip('/')+'/'+BUILD+'/web-apps/apps/api/documents/api.js','build_id':BUILD,'capabilities':{'locateEvidence':True,'applyTrackedSuggestion':False,'externalRevisionList':False,'externalCommentList':False}}

def register(app,store):
    @app.get('/api/v1/editor-config')
    def settings():
        enabled=os.getenv('RIXIN_ONLYOFFICE_ENABLED')=='1'
        return {'onlyoffice_enabled':enabled,'default_engine':'onlyoffice' if enabled else None}

    @app.post('/api/v1/contracts/{cid}/editor-reopen')
    def reopen(cid:str):
        with store.connect() as db:
            v=current(db,cid)
            if not v:raise HTTPException(404,'合同不存在')
            if db.execute("SELECT id FROM editor_sessions WHERE contract_id=? AND state IN ('open','closing')",(cid,)).fetchone():raise HTTPException(409,'请先保存并关闭编辑会话')
            db.execute("UPDATE editor_sessions SET state='closed' WHERE contract_id=? AND state='view'",(cid,))
            row=db.execute('SELECT payload FROM draft_states WHERE contract_id=?',(cid,)).fetchone()
            state=json.loads(row[0]) if row else {}
            review=state.setdefault('review',{'version':1,'decisions':{},'activity':[]})
            review.update(completed=False,reopenedAt=now())
            db.execute('INSERT OR REPLACE INTO draft_states VALUES(?,?)',(cid,dump(state)))
            return {'document_version_id':v['id'],'review':review}

    @app.get('/api/v1/contracts/{cid}/editor-recovery')
    def recovery(cid:str):
        with store.connect() as db:
            if not current(db,cid):raise HTTPException(404,'合同不存在')
            active=db.execute("SELECT * FROM editor_sessions WHERE contract_id=? AND state IN ('open','closing')",(cid,)).fetchone()
            rows=db.execute('SELECT c.id,c.sha256,c.reason,c.created_at FROM editor_snapshot_candidates c JOIN editor_sessions s ON s.id=c.session_id WHERE s.contract_id=? ORDER BY c.created_at DESC',(cid,)).fetchall()
            return {'session_id':active['id'] if active else None,'can_recover':bool(active and active['lease_until']<time.time()),'candidates':[{**dict(r),'download_url':f"/api/v1/contracts/{cid}/editor-candidates/{r['id']}/file"} for r in rows]}

    @app.get('/api/v1/contracts/{cid}/editor-candidates/{candidate_id}/file')
    def recovery_file(cid:str,candidate_id:str):
        with store.connect() as db:
            row=db.execute('SELECT c.content FROM editor_snapshot_candidates c JOIN editor_sessions s ON s.id=c.session_id WHERE c.id=? AND s.contract_id=?',(candidate_id,cid)).fetchone()
            if not row:raise HTTPException(404,'恢复副本不存在')
            return Response(row['content'],media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':'attachment; filename="unconfirmed-recovery.docx"','Cache-Control':'no-store'})

    @app.post('/api/v1/editor-sessions/{sid}/recover')
    def recover_session(sid:str,body:CloseSession):
        with store.connect() as db:
            s=get_session(db,sid)
            if s['state'] not in ('open','closing') or s['lease_until']>=time.time():raise HTTPException(409,'原窗口仍在线，请在原窗口保存并关闭')
            if current(db,s['contract_id'])['id']!=body.document_version_id:raise HTTPException(409,'正文已变化，请刷新后重试')
            db.execute("UPDATE editor_sessions SET state='closed' WHERE id=?",(sid,))
            for row in db.execute('SELECT payload FROM editor_save_requests WHERE session_id=?',(sid,)):
                r=json.loads(row[0])
                if r['state'] in ('pending','unconfirmed'):r.update(state='superseded');put_request(db,r)
            return {'state':'closed','document_version_id':body.document_version_id}

    @app.post('/api/v1/contracts/{cid}/editor-sessions',status_code=201)
    def open_session(cid:str,body:OpenSession):
        if os.getenv('RIXIN_ONLYOFFICE_ENABLED')!='1':raise HTTPException(503,'文档编辑服务尚未启用，请配置 ONLYOFFICE')
        with store.connect() as db:
            old=db.execute('SELECT * FROM editor_sessions WHERE contract_id=? AND idem=?',(cid,body.idempotency_key)).fetchone()
            if old:
                if old['client_id']!=body.client_instance_id or old['base_version_id']!=body.expected_version_id:raise HTTPException(409,'会话请求标识冲突')
                if old['state'] not in ('open','view'):raise HTTPException(409,'会话已关闭，请重新打开')
                db.execute('UPDATE editor_sessions SET lease_until=? WHERE id=?',(time.time()+120,old['id']))
                return present(db,dict(old))
            v=current(db,cid)
            if not v or v['id']!=body.expected_version_id:raise HTTPException(409,'正文版本已变化')
            active=db.execute("SELECT * FROM editor_sessions WHERE contract_id=? AND state IN ('open','closing')",(cid,)).fetchone()
            # Readers use independent, immutable snapshots; only one session may write.
            sid=str(uuid4());state='view' if active or finalized(db,cid,v['id']) else 'open'
            db.execute('INSERT INTO editor_sessions VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,cid,body.client_instance_id,body.idempotency_key,'rixin-'+sid,v['id'],v['id'],state,time.time()+120,now()))
            return present(db,get_session(db,sid))

    @app.get('/api/v1/editor-sessions/{sid}/file')
    def file(sid:str,token:str):
        claims=verify(token)
        with store.connect() as db:
            s=get_session(db,sid)
            if claims.get('sid')!=sid or claims.get('vid')!=s['base_version_id']:raise HTTPException(403,'文件签名与版本不一致')
            v=db.execute('SELECT content FROM versions WHERE id=?',(s['base_version_id'],)).fetchone()
            return Response(v['content'],media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Cache-Control':'no-store'})

    @app.post('/api/v1/editor-sessions/{sid}/heartbeat')
    def heartbeat(sid:str):
        with store.connect() as db:
            s=get_session(db,sid)
            if s['state'] not in ('open','view'):raise HTTPException(409,'编辑会话已结束')
            db.execute('UPDATE editor_sessions SET lease_until=? WHERE id=?',(time.time()+120,sid))
            return {'state':s['state'],'head_version_id':s['head_version_id']}

    @app.post('/api/v1/editor-sessions/{sid}/save-requests',status_code=202)
    def save_request(sid:str,body:SaveRequest):
        with store.connect() as db:
            s=get_session(db,sid)
            old=db.execute('SELECT payload FROM editor_save_requests WHERE session_id=? AND idem=?',(sid,body.idempotency_key)).fetchone()
            if old:
                r=json.loads(old[0])
                if r['request']!=body.model_dump():raise HTTPException(409,'保存请求标识冲突')
                return r
            if s['state']!='open' or s['lease_until']<time.time():raise HTTPException(409,'会话不可写或已过期，请重新连接')
            if s['head_version_id']!=body.expected_head_version_id or current(db,s['contract_id'])['id']!=s['head_version_id']:raise HTTPException(409,'正文版本冲突')
            previous=[reconcile_request(db,json.loads(row[0])) for row in db.execute('SELECT payload FROM editor_save_requests WHERE session_id=?',(sid,))]
            if any(r['state']=='pending' for r in previous):raise HTTPException(409,'上一保存请求仍待确认，请稍后重试')
            # Once a retry starts, an older uncertain callback may only be recovered,
            # never promoted over the retry's snapshot.
            for prior in previous:
                if prior['state']=='unconfirmed':prior.update(state='superseded');put_request(db,prior)
            rid=str(uuid4());r={'id':rid,'state':'pending','session_id':sid,'request':body.model_dump(),'created_at':now()}
            db.execute('INSERT INTO editor_save_requests VALUES(?,?,?,?)',(rid,sid,body.idempotency_key,dump(r)))
        try:
            response=send_command({'c':'forcesave','key':s['document_key'],'userdata':rid})
            error=response.get('error',-1)
        except Exception: error=-1
        with store.connect() as db:
            r=json.loads(db.execute('SELECT payload FROM editor_save_requests WHERE id=?',(rid,)).fetchone()[0])
            if r['state']=='pending' and error:
                r.update(state='unconfirmed' if error in (4,-1) else 'failed',error_code=error);put_request(db,r)
            return r

    @app.get('/api/v1/editor-sessions/{sid}/save-requests/{rid}')
    def receipt(sid:str,rid:str):
        with store.connect() as db:
            row=db.execute('SELECT payload FROM editor_save_requests WHERE id=? AND session_id=?',(rid,sid)).fetchone()
            if not row:raise HTTPException(404,'保存请求不存在')
            return reconcile_request(db,json.loads(row[0]))

    @app.post('/api/v1/editor-sessions/{sid}/close')
    def close(sid:str,body:CloseSession):
        with store.connect() as db:
            s=get_session(db,sid)
            if s['head_version_id']!=body.document_version_id:raise HTTPException(409,'关闭前保存版本不一致')
            if any(json.loads(r[0])['state']=='pending' for r in db.execute('SELECT payload FROM editor_save_requests WHERE session_id=?',(sid,))):raise HTTPException(409,'仍有待确认的保存')
            db.execute("UPDATE editor_sessions SET state='closed' WHERE id=?",(sid,))
            return {'state':'closed','document_version_id':body.document_version_id}

    @app.post('/api/v1/onlyoffice/callback/{sid}')
    async def callback(sid:str,request:Request):
        body=await request.json()
        claims=verify(request.headers.get('authorization','').removeprefix('Bearer ') or body.get('token',''))
        signed=claims.get('payload',claims)
        if any(signed.get(k)!=v for k,v in body.items() if k!='token'):raise HTTPException(403,'回调与签名不一致')
        status=body.get('status')
        with store.connect() as db:
            s=get_session(db,sid)
            if body.get('key')!=s['document_key']:raise HTTPException(403,'回调会话不一致')
        if status not in (2,6):
            if status in (3,7):
                with store.connect() as db:
                    for row in db.execute('SELECT payload FROM editor_save_requests WHERE session_id=?',(sid,)):
                        r=json.loads(row[0])
                        if r['state']=='pending':r.update(state='failed',error_code=status);put_request(db,r)
            if status==4:
                with store.connect() as db:db.execute("UPDATE editor_sessions SET state='closed' WHERE id=?",(sid,))
            return {'error':0}
        try:
            # Network I/O is outside the SQLite transaction and outside the event loop.
            from starlette.concurrency import run_in_threadpool
            data=await run_in_threadpool(download_document,body.get('url',''))
            parsed=await run_in_threadpool(parse_docx,data)
        except Exception:return {'error':1}
        digest=hashlib.sha256(data).hexdigest()
        with store.connect() as db:
            s=get_session(db,sid);rid=body.get('userdata','')
            row=db.execute('SELECT payload FROM editor_save_requests WHERE id=? AND session_id=?',(rid,sid)).fetchone()
            r=json.loads(row[0]) if row else None
            db.execute('INSERT INTO editor_callback_receipts(session_id,payload_hash,content_sha,status,created_at) VALUES(?,?,?,?,?)',(sid,hashlib.sha256(dump(body).encode()).hexdigest(),digest,status,now()))
            if r and r['state']=='committed':
                if r['sha256']!=digest:candidate(db,sid,data,'contradictory_duplicate')
                return {'error':0}
            eligible=s['state']=='open' and s['lease_until']>=time.time() and not finalized(db,s['contract_id'],s['head_version_id'])
            expected=r['request']['expected_head_version_id'] if r else s['head_version_id']
            eligible=eligible and current(db,s['contract_id'])['id']==expected and s['head_version_id']==expected
            if not eligible or (status==6 and (not r or r['state'] not in ('pending','unconfirmed'))):
                candidate(db,sid,data,'stale_or_unassociated')
                if r and r['state'] in ('pending','unconfirmed'):r.update(state='conflict');put_request(db,r)
                return {'error':0}
            filename=db.execute('SELECT filename FROM versions WHERE id=?',(s['base_version_id'],)).fetchone()[0]
            v=commit_version(db,s['contract_id'],data,filename,parsed,expected,session_id=sid)
            db.execute('UPDATE editor_sessions SET head_version_id=?,state=? WHERE id=?',(v['id'],'closed' if status==2 else 'open',sid))
            if r:r.update(state='committed',document_version_id=v['id'],sha256=digest,committed_at=now());put_request(db,r)
        return {'error':0}
