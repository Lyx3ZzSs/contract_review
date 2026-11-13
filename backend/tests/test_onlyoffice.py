import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from test_backend import docx

@pytest.fixture
def editor(tmp_path,monkeypatch):
    monkeypatch.setenv('RIXIN_ONLYOFFICE_ENABLED','1')
    monkeypatch.setenv('RIXIN_ONLYOFFICE_SECRET','test-only-secret')
    app=create_app(tmp_path/'oo.db'); c=TestClient(app)
    cid=c.post('/api/v1/contracts',json={'title':'编辑验证','contract_type':'数据服务','our_party':'乙方','stage':'pre_sign','data_purpose':'test'}).json()['id']
    v=c.post(f'/api/v1/contracts/{cid}/versions',files={'file':('test.docx',docx('第一版'))}).json()
    response=c.post(f'/api/v1/contracts/{cid}/editor-sessions',json={'expected_version_id':v['id'],'client_instance_id':'one','idempotency_key':'open-one'})
    assert response.status_code==201,response.text
    return c,cid,v,response.json(),app

def save(c,s,key='save1'):
    return c.post(f"/api/v1/editor-sessions/{s['id']}/save-requests",json={'idempotency_key':key,'expected_head_version_id':s['head_version_id'],'purpose':'review'})

def callback(c,s,r,data,monkeypatch):
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'download_document',lambda *_:data)
    body={'key':s['document_key'],'status':6,'forcesavetype':0,'userdata':r['id'],'url':'http://127.0.0.1:18083/cache/output.docx'}
    return c.post(f"/api/v1/onlyoffice/callback/{s['id']}",json=body,headers={'Authorization':'Bearer '+oo.sign(body)})

def test_session_single_writer_and_stable_key(editor):
    c,cid,v,s,_=editor
    again=c.post(f'/api/v1/contracts/{cid}/editor-sessions',json={'expected_version_id':v['id'],'client_instance_id':'one','idempotency_key':'open-one'})
    assert again.json()['id']==s['id']
    viewer=c.post(f'/api/v1/contracts/{cid}/editor-sessions',json={'expected_version_id':v['id'],'client_instance_id':'two','idempotency_key':'open-two'})
    assert viewer.status_code==201
    assert viewer.json()['state']=='view'
    assert c.post(f'/api/v1/contracts/{cid}/versions',data={'expected_version_id':v['id']},files={'file':('test.docx',docx('外部覆盖'))}).status_code==409

def test_correlated_save_and_duplicate(editor,monkeypatch):
    c,cid,v,s,_=editor
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    r=save(c,s).json(); assert r['state']=='pending'
    assert c.get(f'/api/v1/contracts/{cid}').json()['current_document_version_id']==v['id']
    assert callback(c,s,r,docx('第二版'),monkeypatch).json()=={'error':0}
    receipt=c.get(f"/api/v1/editor-sessions/{s['id']}/save-requests/{r['id']}").json()
    assert receipt['state']=='committed' and receipt['document_version_id']!=v['id']
    assert callback(c,s,r,docx('第二版'),monkeypatch).json()=={'error':0}
    assert len(c.get(f'/api/v1/contracts/{cid}').json()['versions'])==2
    # A contradictory repeat must not replace the committed snapshot.
    callback(c,s,r,docx('错误迟到内容'),monkeypatch)
    assert len(c.get(f'/api/v1/contracts/{cid}').json()['versions'])==2

def test_same_bytes_receipt_and_no_changes_command(editor,monkeypatch):
    c,cid,v,s,_=editor
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    r=save(c,s).json();callback(c,s,r,docx('第一版'),monkeypatch)
    receipt=c.get(f"/api/v1/editor-sessions/{s['id']}/save-requests/{r['id']}").json()
    assert receipt['state']=='committed' and receipt['document_version_id']==v['id']
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':4})
    r2=save(c,s,'two').json(); assert r2['state']=='unconfirmed'

def test_signed_file_is_fixed_and_forged_callback_rejected(editor):
    c,cid,v,s,_=editor
    url=s['config']['document']['url'];from urllib.parse import urlsplit
    u=urlsplit(url)
    assert c.get(u.path+'?'+u.query).content==docx('第一版')
    assert c.get(u.path+'?token=invalid').status_code==403
    assert c.post(f"/api/v1/onlyoffice/callback/{s['id']}",json={'key':s['document_key'],'status':6}).status_code==403

def test_late_callback_after_closed_session_is_quarantined(editor,monkeypatch):
    c,cid,v,s,_=editor
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    r=save(c,s).json();callback(c,s,r,docx('第二版'),monkeypatch)
    receipt=c.get(f"/api/v1/editor-sessions/{s['id']}/save-requests/{r['id']}").json()
    assert c.post(f"/api/v1/editor-sessions/{s['id']}/close",json={'document_version_id':receipt['document_version_id']}).status_code==200
    callback(c,s,{**r,'id':'unrelated'},docx('迟到修改'),monkeypatch)
    assert c.get(f'/api/v1/contracts/{cid}').json()['current_document_version_id']==receipt['document_version_id']

def test_failed_callback_and_bad_urls_do_not_commit(editor,monkeypatch):
    c,cid,v,s,_=editor
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    r=save(c,s).json()
    body={'key':s['document_key'],'status':7}
    assert c.post(f"/api/v1/onlyoffice/callback/{s['id']}",json=body,headers={'Authorization':'Bearer '+oo.sign(body)}).json()=={'error':0}
    assert c.get(f"/api/v1/editor-sessions/{s['id']}/save-requests/{r['id']}").json()['state']=='failed'
    assert c.get(f'/api/v1/contracts/{cid}').json()['current_document_version_id']==v['id']
    for url in ['http://example.com/file','file:///etc/passwd','http://127.0.0.1:8011/api/v1/contracts']:
        with pytest.raises(ValueError):oo.download_document(url)

def test_expired_session_cannot_save_but_can_resume_heartbeat(editor,monkeypatch):
    c,cid,v,s,app=editor
    with app.state.store.connect() as db:db.execute('UPDATE editor_sessions SET lease_until=0 WHERE id=?',(s['id'],))
    assert save(c,s).status_code==409
    assert c.post(f"/api/v1/editor-sessions/{s['id']}/heartbeat").status_code==200

def test_unassociated_callback_is_recoverable_not_promoted(editor,monkeypatch):
    c,cid,v,s,app=editor
    data=docx('恢复副本')
    assert callback(c,s,{'id':'unknown'},data,monkeypatch).json()=={'error':0}
    assert c.get(f'/api/v1/contracts/{cid}').json()['current_document_version_id']==v['id']
    with app.state.store.connect() as db:
        row=db.execute('SELECT content,reason FROM editor_snapshot_candidates WHERE session_id=?',(s['id'],)).fetchone()
        assert row['content']==data and row['reason']=='stale_or_unassociated'

def test_save_timeout_retry_quarantines_late_callback(editor,monkeypatch):
    c,cid,v,s,app=editor
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    first=save(c,s).json()
    with app.state.store.connect() as db:
        first['created_at']='2000-01-01T00:00:00+00:00'
        db.execute('UPDATE editor_save_requests SET payload=? WHERE id=?',(json.dumps(first),first['id']))
    receipt=c.get(f"/api/v1/editor-sessions/{s['id']}/save-requests/{first['id']}").json()
    assert receipt['state']=='unconfirmed'
    second=save(c,s,'retry').json()
    assert second['state']=='pending'
    callback(c,s,first,docx('迟到的旧快照'),monkeypatch)
    assert c.get(f'/api/v1/contracts/{cid}').json()['current_document_version_id']==v['id']
    callback(c,s,second,docx('重试快照'),monkeypatch)
    assert c.get(f"/api/v1/editor-sessions/{s['id']}/save-requests/{second['id']}").json()['state']=='committed'

def test_finalize_closes_matching_session_atomically_and_reopen(editor):
    c,cid,v,s,app=editor
    run=c.post(f'/api/v1/contracts/{cid}/runs',json={'document_version_id':v['id'],'idempotency_key':'finalize'}).json()
    run=c.post(f"/api/v1/runs/{run['id']}/execute").json()
    body={'opinion':'测试流程','reservations':'仅验证系统，不构成法务意见','reviewer':'测试','editor_session_id':s['id']}
    # Failure must leave the session editable.
    assert c.post(f"/api/v1/runs/{run['id']}/results",json=body).status_code==409
    assert c.post(f"/api/v1/editor-sessions/{s['id']}/heartbeat").status_code==200
    for f in run['findings']:
        c.post(f"/api/v1/runs/{run['id']}/findings/{f['id']}/decisions",json={'action':'acknowledged','note':'测试闭环','actor':'测试'})
    assert c.post(f"/api/v1/runs/{run['id']}/results",json={**body,'editor_session_id':'wrong'}).status_code==409
    result=c.post(f"/api/v1/runs/{run['id']}/results",json=body)
    assert result.status_code==201,result.text
    assert c.post(f"/api/v1/editor-sessions/{s['id']}/heartbeat").status_code==409
    readonly=c.post(f'/api/v1/contracts/{cid}/editor-sessions',json={'expected_version_id':v['id'],'client_instance_id':'one','idempotency_key':'readonly'}).json()
    assert readonly['state']=='view'
    assert c.post(f'/api/v1/contracts/{cid}/editor-reopen').status_code==200
    reopened=c.post(f'/api/v1/contracts/{cid}/editor-sessions',json={'expected_version_id':v['id'],'client_instance_id':'one','idempotency_key':'reopen'}).json()
    assert reopened['state']=='open' and reopened['document_key']!=s['document_key']

def test_expired_session_recovery_keeps_candidates(editor,monkeypatch):
    c,cid,v,s,app=editor
    with app.state.store.connect() as db:db.execute('UPDATE editor_sessions SET lease_until=0 WHERE id=?',(s['id'],))
    callback(c,s,{'id':'unknown'},docx('未确认的恢复文件'),monkeypatch)
    recovery=c.get(f'/api/v1/contracts/{cid}/editor-recovery').json()
    assert recovery['session_id']==s['id'] and recovery['can_recover']
    candidate=recovery['candidates'][0]
    assert c.get(candidate['download_url']).content==docx('未确认的恢复文件')
    recovered=c.post(f"/api/v1/editor-sessions/{s['id']}/recover",json={'document_version_id':v['id']})
    assert recovered.status_code==200
    assert c.get(f'/api/v1/contracts/{cid}').json()['current_document_version_id']==v['id']
    again=c.post(f'/api/v1/contracts/{cid}/editor-sessions',json={'expected_version_id':v['id'],'client_instance_id':'two','idempotency_key':'recovered'})
    assert again.status_code==201
    assert c.post(f"/api/v1/editor-sessions/{again.json()['id']}/recover",json={'document_version_id':v['id']}).status_code==409


def test_viewers_are_isolated_and_can_reenter_after_writer_leaves(editor,monkeypatch):
    c,cid,v,s,app=editor
    original=c.get(f"/api/v1/versions/{v['id']}/file").content
    viewers=[]
    for client in ('two','three'):
        request={'expected_version_id':v['id'],'client_instance_id':client,'idempotency_key':client}
        response=c.post(f'/api/v1/contracts/{cid}/editor-sessions',json=request)
        assert response.status_code==201,response.text
        viewer=response.json();viewers.append(viewer)
        assert viewer['state']=='view'
        assert viewer['read_only_reason']=='occupied'
        assert viewer['document_key']!=s['document_key']
        assert viewer['config']['editorConfig']['mode']=='view'
        assert all(viewer['config']['document']['permissions'][p] is False for p in ('edit','review','comment'))
        assert c.post(f'/api/v1/contracts/{cid}/editor-sessions',json=request).json()['id']==viewer['id']
        assert save(c,viewer).status_code==409
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    r=save(c,s).json();callback(c,s,r,docx('已保存的新正文'),monkeypatch)
    head=c.get(f'/api/v1/contracts/{cid}').json()['current_document_version_id']
    assert head!=v['id']
    from urllib.parse import urlsplit
    u=urlsplit(viewers[0]['config']['document']['url'])
    assert c.get(u.path+'?'+u.query).content==original
    assert c.post(f"/api/v1/editor-sessions/{viewers[0]['id']}/close",json={'document_version_id':v['id']}).status_code==200
    assert c.post(f"/api/v1/editor-sessions/{s['id']}/heartbeat").json()['state']=='open'
    assert c.post(f"/api/v1/editor-sessions/{s['id']}/close",json={'document_version_id':head}).status_code==200
    reentered=c.post(f'/api/v1/contracts/{cid}/editor-sessions',json={'expected_version_id':head,'client_instance_id':'two','idempotency_key':'reenter'})
    assert reentered.status_code==201
    assert reentered.json()['state']=='open'
    assert reentered.json()['read_only_reason'] is None
    assert c.post(f"/api/v1/editor-sessions/{viewers[1]['id']}/heartbeat").json()['state']=='view'


def test_simultaneous_open_keeps_one_writer_and_allows_readers(editor):
    from concurrent.futures import ThreadPoolExecutor
    c,cid,v,s,app=editor
    assert c.post(f"/api/v1/editor-sessions/{s['id']}/close",json={'document_version_id':v['id']}).status_code==200
    def open_client(i):
        return c.post(f'/api/v1/contracts/{cid}/editor-sessions',json={'expected_version_id':v['id'],'client_instance_id':str(i),'idempotency_key':f'parallel-{i}'})
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses=list(pool.map(open_client,range(3)))
    assert all(r.status_code==201 for r in responses)
    assert sorted(r.json()['state'] for r in responses)==['open','view','view']
    assert len({r.json()['document_key'] for r in responses})==3
