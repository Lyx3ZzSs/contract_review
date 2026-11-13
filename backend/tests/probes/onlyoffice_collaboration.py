"""Explicitly isolated, real Document Server collaboration capability probe."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from app import onlyoffice as oo
from app.store import Store


def create_probe(output: Path, database: Path, fixture: Path, port: int):
    if database.exists():
        raise ValueError('Probe requires a new, explicitly isolated database')
    output.mkdir(parents=True, exist_ok=True)
    store = Store(database)
    key = 'collaboration-probe-' + str(uuid4())
    content = fixture.read_bytes()
    with store.connect() as db:
        db.execute('CREATE TABLE probe_events(sequence INTEGER PRIMARY KEY, timestamp REAL, payload TEXT)')
        db.execute('CREATE TABLE probe_files(sequence INTEGER PRIMARY KEY, sha256 TEXT, content BLOB)')
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5175'], allow_methods=['GET','POST'])

    def event(payload):
        with store.connect() as db:
            db.execute('INSERT INTO probe_events(timestamp,payload) VALUES(?,?)', (time.time(), json.dumps(payload)))

    @app.get('/file')
    def file(token: str):
        if oo.verify(token).get('key') != key:
            raise HTTPException(403)
        return Response(content, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

    @app.get('/config/{user}')
    def config(user: str, role: str = 'collaborator'):
        if user not in ('alice', 'bob', 'carol') or role not in ('lead', 'collaborator', 'viewer'):
            raise HTTPException(400)
        permissions = {'edit':role == 'lead', 'review':role != 'viewer', 'comment':role != 'viewer',
                       'reviewGroups': ['lead', 'collaborator', ''] if role == 'lead' else [], 'download':True}
        cfg = {'documentType':'word','type':'desktop','width':'100%','height':'100%',
               'document':{'fileType':'docx','key':key,'title':'隔离协作验证.docx',
                           'url':f'http://host.docker.internal:{port}/file?token='+oo.sign({'key':key,'exp':time.time()+3600}),
                           'permissions':permissions},
               'editorConfig':{'lang':'zh-CN','mode':'view' if role=='viewer' else 'edit',
                               'callbackUrl':f'http://host.docker.internal:{port}/callback',
                               'user':{'id':user,'name':'测试 '+user,'group':role},
                               'coEditing':{'mode':'fast','change':False},
                               'customization':{'review':{'trackChanges':True},'forcesave':False,'autosave':True}}}
        return {**cfg,'token':oo.sign(cfg)}

    @app.get('/', response_class=HTMLResponse)
    def page(user: str = 'alice', role: str = 'lead'):
        if user not in ('alice', 'bob', 'carol') or role not in ('lead', 'collaborator', 'viewer'):
            raise HTTPException(400)
        return '''<!doctype html><html><head><meta charset="utf-8"><style>html,body,#editor{height:100%;margin:0}</style></head><body><div id="editor"></div>
<script src="http://127.0.0.1:18083/'''+oo.BUILD+'''/web-apps/apps/api/documents/api.js"></script><script>
window.probeEvents=[];fetch('/config/'''+user+'?role='+role+'''').then(r=>r.json()).then(config=>{
config.events={onDocumentReady:()=>{window.probeReady=true},onDocumentStateChange:e=>probeEvents.push({type:'change',data:e.data}),onError:e=>probeEvents.push({type:'error',data:e.data})};
window.editor=new DocsAPI.DocEditor('editor',config)});</script></body></html>'''

    # Served by the existing Vite test origin so the pinned bridge's origin
    # allowlist remains unchanged. This HTML carries no secret or signed config.
    html = page().replace("fetch('/config/alice?role=lead')", "fetch('http://127.0.0.1:"+str(port)+"/config/'+(new URLSearchParams(location.search).get('user')||'alice')+'?role='+(new URLSearchParams(location.search).get('role')||'lead'))")
    (output/'browser.html').write_text(html)

    @app.post('/callback')
    async def callback(request: Request):
        body = await request.json()
        claims = oo.verify(request.headers.get('authorization','').removeprefix('Bearer ') or body.get('token',''))
        signed = claims.get('payload',claims)
        if any(signed.get(k)!=v for k,v in body.items() if k!='token') or body.get('key')!=key:
            raise HTTPException(403)
        event({k:v for k,v in body.items() if k not in ('token','url','changesurl','history')})
        if body.get('status') in (2,6):
            from starlette.concurrency import run_in_threadpool
            data = await run_in_threadpool(oo.download_document,body['url'])
            with store.connect() as db:
                cursor = db.execute('INSERT INTO probe_files(sha256,content) VALUES(?,?)',(hashlib.sha256(data).hexdigest(),data))
                name = f"snapshot-{cursor.lastrowid}.docx"
            (output/name).write_bytes(data)
        return {'error':0}

    @app.post('/command/{command}')
    def command(command: str):
        if command not in ('forcesave','drop','info'):
            raise HTTPException(400)
        request = {'c':command,'key':key}
        if command=='forcesave':request['userdata']=str(uuid4())
        result = oo.send_command(request)
        event({'command':command,'result':result})
        return result

    @app.get('/evidence')
    def evidence():
        with store.connect() as db:
            result = {'events':[dict(r) | {'payload':json.loads(r['payload'])} for r in db.execute('SELECT * FROM probe_events')],
                      'files':[dict(r) for r in db.execute('SELECT sequence,sha256 FROM probe_files')]}
        (output/'events.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        return result

    return app


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--fixture',type=Path,required=True)
    parser.add_argument('--port',type=int,default=18085)
    args=parser.parse_args()
    if not os.getenv('RIXIN_ONLYOFFICE_SECRET_FILE'):
        parser.error('Set RIXIN_ONLYOFFICE_SECRET_FILE; secret is never printed')
    import uvicorn
    uvicorn.run(create_probe(args.output,args.database,args.fixture,args.port),host='0.0.0.0',port=args.port,access_log=False)
