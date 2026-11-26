import json,time
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from app.main import create_app
from app.store import Store
from app.worker import tick
from app.llm import Settings
from test_backend import setup,docx


def fake(settings,model,blocks,context,rules,**kwargs):
    records = [{'rule_id': r['id'], 'status': 'insufficient_evidence', 'explanation': '需补资料',
                'evidence': [], 'suggested_text': None} for r in rules]
    return {'rule_results': records, 'issues': []}


def queue(setup):
    c,cid,*_=setup
    r=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'async-1'})
    assert r.status_code==202,r.text
    return r.json()


def test_durable_queue_and_worker(setup):
    c,cid,v,_,path=setup
    run=queue(setup);assert run['status']=='queued'
    assert c.post(f"/api/v1/runs/{run['id']}/execute").status_code==409
    c=TestClient(create_app(path));store=Store(path)
    assert c.get(f"/api/v1/runs/{run['id']}").json()['status']=='queued'
    with ThreadPoolExecutor(max_workers=2) as pool:
        done=list(pool.map(lambda _:tick(store,Settings('http://test','fake'),fake),range(2)))
    assert sum(done)==1
    result=c.get(f"/api/v1/runs/{run['id']}").json()
    assert result['status']=='needs_input' and len(result['findings'])==6
    assert result['mode']=='model_review' and result['findings'][0]['scope']=='model_candidate'


def test_worker_marks_stale_completion(setup):
    c,cid,v,_,path=setup;run=queue(setup)
    def changing(*args,**kwargs):
        assert c.post(f'/api/v1/contracts/{cid}/versions',data={'expected_version_id':v['id']},files={'file':('new.docx',docx('new'))}).status_code==201
        return fake(*args,**kwargs)
    assert tick(Store(path),Settings('http://test','fake'),changing)
    assert c.get(f"/api/v1/runs/{run['id']}").json()['stale']


def test_interrupted_lease_recovered(setup):
    _,_,_,_,path=setup;run=queue(setup);store=Store(path)
    with store.connect() as db:db.execute("UPDATE jobs SET state='running',attempts=1,lease_until=?",(time.time()-1,))
    with ThreadPoolExecutor(max_workers=2) as pool:
        settled=list(pool.map(lambda _:tick(store,Settings('http://test','fake'),fake),range(2)))
    assert sorted(settled)==[False,True]
    with store.connect() as db:
        assert json.loads(db.execute('SELECT payload FROM runs WHERE id=?',(run['id'],)).fetchone()[0])['recovery_count']==1
    with store.connect() as db:assert db.execute('SELECT attempts FROM jobs WHERE id=?',(run['id'],)).fetchone()[0]==2


def test_draft_state_and_identical_bytes_do_not_create_version(setup):
    c,cid,v,file,_=setup
    r=c.post(f'/api/v1/contracts/{cid}/versions',data={'expected_version_id':v['id'],'draft_state':json.dumps({'edited':True})},files={'file':('test.docx',file)})
    assert r.status_code==201 and r.json()['id']==v['id']
    assert c.get(f'/api/v1/contracts/{cid}/draft-state').json()=={'edited':True}


def test_exhausted_interruption_invalidates_old_owner(setup):
    c,_,_,_,path=setup;run=queue(setup);store=Store(path)
    from app.review_execution_events import append
    with store.connect() as db:
        db.execute("UPDATE jobs SET state='running',attempts=2,owner='old-worker',lease_until=?",(time.time()-1,))
        append(db,run,'old-worker','attempt_started',{})
        append(db,run,'old-worker','task_started',{'task_id':'unfinished'})
    assert not tick(store,Settings('http://test','fake'),fake)
    with store.connect() as db:
        job=db.execute('SELECT * FROM jobs').fetchone()
        assert job['state']=='failed' and job['owner'] is None
    result=c.get(f"/api/v1/runs/{run['id']}").json()
    assert result['status']=='failed' and result['error']['code']=='worker_interrupted'
    state=c.get(f"/api/v1/runs/{run['id']}/execution-state").json()
    assert state['status']=='failed' and state['tasks']['unfinished']['state']=='failed'
    events=c.get(f"/api/v1/runs/{run['id']}/execution-events").json()['events']
    assert events[-1]['type']=='run_failed' and events[-1]['attempt_id']=='old-worker'


def test_worker_rejects_retired_policy_and_retry_creates_linked_batch(setup):
    from app.review_policy import active_version,prompt_hash
    c,_,_,_,path=setup;run=queue(setup);store=Store(path);seen=[]
    assert run['review_prompt_version']==active_version()
    assert run['review_prompt_sha256']==prompt_hash(active_version())
    # A previously queued v1 task must not silently switch to v2.
    with store.connect() as db:
        payload=json.loads(db.execute('SELECT payload FROM runs WHERE id=?',(run['id'],)).fetchone()[0])
        payload['review_prompt_version']='review-agent-v4'
        db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(payload),run['id']))
    def recorder(*args,**kwargs):
        seen.append(True);return fake(*args,**kwargs)
    assert tick(store,Settings('http://test','fake'),recorder)
    assert not seen
    old = c.get(f"/api/v1/runs/{run['id']}").json()
    assert old['error']['code'] == 'review_policy_retired'
    response = c.post(f"/api/v1/runs/{run['id']}/resume")
    assert response.status_code == 202, response.text
    assert response.json()['parent_run_id'] == old['id']
    assert response.json()['review_prompt_version'] == active_version()
    assert c.get(f"/api/v1/runs/{run['id']}").json() == old


def test_changed_prompt_hash_stops_execution(setup):
    c,_,_,_,path=setup;run=queue(setup);store=Store(path)
    with store.connect() as db:
        p=json.loads(db.execute('SELECT payload FROM runs WHERE id=?',(run['id'],)).fetchone()[0]);p['review_prompt_sha256']='invalid'
        db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(p),run['id']))
    def must_not_call(*args,**kwargs):raise AssertionError('must not call model')
    assert tick(store,Settings('http://test','fake'),must_not_call)
    result=c.get(f"/api/v1/runs/{run['id']}").json()
    assert result['status']=='failed' and result['error']['code']=='review_policy_mismatch'


def test_editor_state_snapshot_tracks_saved_version_and_state(setup):
    c,cid,v,data,_=setup
    response=c.get(f'/api/v1/contracts/{cid}/editor-state')
    assert response.status_code==200
    assert response.json()=={'document_version_id':v['id'],'draft_state':None,'results':[]}
    state={'edited':True,'review':{'completed':False}}
    newer=c.post(f'/api/v1/contracts/{cid}/versions',files={'file':('new.docx',docx('新的合同正文'))},
                 data={'expected_version_id':v['id'],'draft_state':json.dumps(state)}).json()
    loaded=c.get(f'/api/v1/contracts/{cid}/editor-state').json()
    assert loaded['document_version_id']==newer['id']
    assert loaded['draft_state']==state
    assert c.get('/api/v1/contracts/absent/editor-state').status_code==404


def test_new_document_without_state_does_not_inherit_old_review(setup):
    c,cid,v,data,_=setup
    c.post(f'/api/v1/contracts/{cid}/versions',files={'file':('same.docx',data)},
           data={'expected_version_id':v['id'],'draft_state':json.dumps({'review':{'completed':True}})})
    newer=c.post(f'/api/v1/contracts/{cid}/versions',files={'file':('new.docx',docx('新版本'))},
                 data={'expected_version_id':v['id']})
    assert newer.status_code==201
    assert c.get(f'/api/v1/contracts/{cid}/draft-state').json() is None


def test_worker_runs_different_contracts_in_parallel_and_drains_on_stop(setup):
    from threading import Event, Thread
    from app.worker import serve

    c, cid, version, _, path = setup
    store = Store(path)
    first = queue(setup)
    def enqueue(contract, title, previous=None):
        response = c.post(f'/api/v1/contracts/{contract}/versions',
                          data={'expected_version_id':previous} if previous else {},
                          files={'file':('test.docx',docx(title))})
        response.raise_for_status()
        run = c.post(f'/api/v1/contracts/{contract}/reviews',json={'idempotency_key':title})
        run.raise_for_status()
        return run.json()

    second_version = enqueue(cid, 'same contract, second version', version['id'])
    def new_contract(title):
        response = c.post('/api/v1/contracts', json={
            'title':title,'contract_type':'服务','our_party':'乙方','stage':'pre_sign'})
        return enqueue(response.json()['id'], title)

    second = new_contract('second contract')
    third = new_contract('third contract')
    runs = [first, second_version, second, third]
    started = {r['document_version_id']:Event() for r in runs}
    release = {vid:Event() for vid in started}
    def review(*args, document_version_id, **kwargs):
        started[document_version_id].set()
        assert release[document_version_id].wait(12)
        return fake(*args, **kwargs)

    stop = Event()
    thread = Thread(target=serve,args=(store,Settings('http://test','fake'),stop,2,1,review))
    thread.start()
    try:
        assert started[version['id']].wait(5)
        assert started[second['document_version_id']].wait(5)
        # Another consumer of the same queue cannot exceed its admission limit.
        assert not tick(store, Settings('http://test','fake'), review, job_limit=2)
        assert c.get(f"/api/v1/runs/{second_version['id']}").json()['status']=='queued'
        assert c.get(f"/api/v1/runs/{third['id']}").json()['status']=='queued'
        release[second['document_version_id']].set()
        assert started[third['document_version_id']].wait(5)
        stop.set()
    finally:
        stop.set()
        for event in release.values():
            event.set()
        thread.join(8)
    assert not thread.is_alive()
    assert not started[second_version['document_version_id']].is_set()
    assert tick(store, Settings('http://test','fake'), fake)
    with store.connect() as db:
        assert [(r['state'],r['attempts']) for r in db.execute('SELECT * FROM jobs')]==[('done',1)]*4
    for run in runs:
        final = c.get(f"/api/v1/runs/{run['id']}").json()
        assert final['status']=='needs_input' and final['document_version_id']==run['document_version_id']


def test_model_capacity_preserves_deadlines_and_releases_on_failure():
    from threading import Event
    from app.worker import limited_model_call
    from app.llm import ExtractionError
    import pytest

    entered, release = Event(), Event()
    def invoke(settings, model, prompt, schema, payload, validate, deadline, trace):
        if prompt=='hold':
            entered.set()
            assert release.wait(5)
            raise RuntimeError('test failure')
        return prompt

    limited = limited_model_call(invoke, 1)
    def call(prompt, timeout):
        return limited(None,None,prompt,None,None,None,time.monotonic()+timeout,[])
    with ThreadPoolExecutor(max_workers=2) as pool:
        busy = pool.submit(call, 'hold', 5)
        try:
            assert entered.wait(2)
            with pytest.raises(ExtractionError) as exc:
                call('waiting', .05)
            assert exc.value.code=='model_capacity_timeout'
        finally:
            release.set()
        with pytest.raises(RuntimeError):
            busy.result()
        assert call('next', 2)=='next'


def test_admitted_request_keeps_its_gateway_budget():
    from app.worker import limited_model_call
    from threading import Event
    entered,release=Event(),Event()
    def invoke(settings, model, prompt, schema, payload, validate, deadline, trace):
        if prompt=='hold':
            entered.set()
            assert release.wait(3)
        return deadline-time.monotonic()
    limited=limited_model_call(invoke,1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        busy=pool.submit(limited,None,None,'hold',None,None,None,time.monotonic()+3,[])
        assert entered.wait(2)
        started=time.monotonic()
        next_call=pool.submit(limited,None,None,'next',None,None,None,started+1,[])
        time.sleep(.2)
        release.set()
        busy.result()
        assert next_call.result()>.87
