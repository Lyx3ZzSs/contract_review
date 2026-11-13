import json
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.store import Store
from app.worker import tick
from app.llm import Settings, ExtractionError
from test_backend import setup, docx
from test_jobs import fake, queue


def metadata(key='import-1'):
    return {'title':'隔离验证','contract_type':'服务','our_party':'中立审查','data_purpose':'test',
            'party_selection':{'manual_our_name':'我方公司','manual_counterparties':['对方公司']},
            'start_review':True,'idempotency_key':key}


def test_import_starts_once_and_rejects_changed_payload(setup):
    c,_,_,_,path=setup
    data=docx('双方合同正文')
    def send(body):
        return c.post('/api/v1/contracts/import',files={'file':('contract.docx',data)},data={'metadata':json.dumps(body)})
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=list(pool.map(lambda _:send(metadata()),range(2)))
    assert all(r.status_code==201 for r in responses),[r.text for r in responses]
    first=responses[0].json()
    assert first==responses[1].json()
    assert first['run']['status']=='queued'
    assert first['run']['document_version_id']==first['version']['id']
    assert send({**metadata(),'title':'不同内容'}).status_code==409
    with Store(path).connect() as db:
        assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]==1


def test_import_queue_failure_rolls_back_contract(setup,monkeypatch):
    from app import review_jobs
    c,*_=setup
    before=c.get('/api/v1/contracts?data_purpose=all').json()
    def fail(*args,**kwargs):raise RuntimeError('test queue failure')
    monkeypatch.setattr(review_jobs,'enqueue_review',fail)
    with pytest.raises(RuntimeError):
        c.post('/api/v1/contracts/import',files={'file':('contract.docx',docx())},data={'metadata':json.dumps(metadata())})
    assert c.get('/api/v1/contracts?data_purpose=all').json()==before


def test_live_stages_and_failed_stage_persist(setup):
    c,_,_,_,path=setup;run=queue(setup)
    def reviewer(*args,progress_callback,**kwargs):
        progress_callback('extracting')
        live=c.get(f"/api/v1/runs/{run['id']}").json()
        assert live['stage']=='extracting' and live['started_at']
        progress_callback('checking')
        raise ExtractionError('gateway_timeout','模型调用超时')
    assert tick(Store(path),Settings('http://test','fake'),reviewer)
    result=c.get(f"/api/v1/runs/{run['id']}").json()
    assert result['status']=='failed' and result['stage']=='checking'
    assert [s['stage'] for s in result['stage_history']]==['queued','preparing','extracting','checking']
    assert result['finished_at']


@pytest.mark.parametrize('resolution',['false_positive','exception_recorded'])
def test_pending_business_confirmation_blocks_completion(setup,resolution):
    c,_,_,_,path=setup;run=queue(setup)
    tick(Store(path),Settings('http://test','fake'),fake)
    result=c.get(f"/api/v1/runs/{run['id']}").json()
    for f in result['findings']:
        response=c.post(f"/api/v1/runs/{run['id']}/findings/{f['id']}/decisions",json={'action':'acknowledged','note':'已核对','actor':'测试'})
        assert response.status_code==201
    f=result['findings'][0]
    path=f"/api/v1/runs/{run['id']}/findings/{f['id']}/decisions"
    c.post(path,json={'action':'needs_business_confirmation','note':'仍需业务确认','actor':'测试'})
    body={'opinion':'已复核','reservations':'无','reviewer':'测试'}
    assert c.post(f"/api/v1/runs/{run['id']}/results",json=body).status_code==409
    assert c.post(path,json={'action':resolution,'note':'法务确认处理结论','actor':'测试'}).status_code==201
    assert c.post(f"/api/v1/runs/{run['id']}/results",json=body).status_code==201


def test_structured_pipeline_reports_real_stages(monkeypatch):
    from test_structured_review import responses,facts,other
    from app.structured_review import review_structured
    stages=[]
    responses(monkeypatch,[facts(),other()])
    result=review_structured(Settings('http://test','fake'),'deepseek-v4-flash',[{'id':'p','text':'合同正文'}],{},[],progress_callback=stages.append)
    assert stages==['extracting','checking','validating']
    assert len(result)==5


def test_reclaimed_worker_cannot_overwrite_progress(setup):
    c,_,_,_,path=setup;run=queue(setup);store=Store(path)
    def reclaimed(*args,progress_callback,**kwargs):
        with store.connect() as db:
            db.execute("UPDATE jobs SET owner='successor' WHERE id=?",(run['id'],))
        progress_callback('extracting')
        raise AssertionError('lost lease must stop the reviewer')
    assert tick(store,Settings('http://test','fake'),reclaimed)
    current=c.get(f"/api/v1/runs/{run['id']}").json()
    assert current['stage']=='preparing' and current['status']=='running'
    assert not current['error']


def test_stale_launch_and_duplicate_active_run_rejected(setup):
    c,cid,v,_,_=setup
    assert c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'wrong-version','document_version_id':'old'}).status_code==409
    run=queue(setup)
    assert c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'second-tab','document_version_id':v['id']}).status_code==409
    assert c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'async-1'}).json()['id']==run['id']
    other_model='glm-5.3-flash' if run['model']=='deepseek-v4-flash' else 'deepseek-v4-flash'
    # The internal calibration API can still compare different models.
    assert c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'calibration','model':other_model}).status_code==202
