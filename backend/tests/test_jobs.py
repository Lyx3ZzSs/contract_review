import json,time
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from app.main import create_app
from app.store import Store
from app.worker import tick
from app.llm import Settings
from test_backend import setup,docx


def fake(settings,model,blocks,context,rules,**kwargs):
    return [{'rule_id':r['id'],'status':'insufficient_evidence','explanation':'需补资料','evidence':[],'suggested_text':None} for r in rules]


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
    assert result['status']=='needs_input' and len(result['findings'])==5
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
    assert tick(store,Settings('http://test','fake'),fake)
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


def test_worker_uses_queued_prompt_version(setup):
    from app.review_policy import active_version,prompt_hash
    c,_,_,_,path=setup;run=queue(setup);store=Store(path);seen=[]
    assert run['review_prompt_version']==active_version()
    assert run['review_prompt_sha256']==prompt_hash(active_version())
    # A previously queued v1 task must not silently switch to v2.
    with store.connect() as db:
        payload=json.loads(db.execute('SELECT payload FROM runs WHERE id=?',(run['id'],)).fetchone()[0])
        payload['review_prompt_version']='redlines-v1';payload['review_prompt_sha256']=prompt_hash('redlines-v1');payload.pop('review_schema_sha256',None)
        db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(payload),run['id']))
    def recorder(*args,**kwargs):
        seen.append(kwargs['prompt_version']);return fake(*args,**kwargs)
    assert tick(store,Settings('http://test','fake'),recorder)
    assert seen==['redlines-v1']


def test_changed_prompt_hash_stops_execution(setup):
    c,_,_,_,path=setup;run=queue(setup);store=Store(path)
    with store.connect() as db:
        p=json.loads(db.execute('SELECT payload FROM runs WHERE id=?',(run['id'],)).fetchone()[0]);p['review_prompt_sha256']='invalid'
        db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(p),run['id']))
    def must_not_call(*args,**kwargs):raise AssertionError('must not call model')
    assert tick(store,Settings('http://test','fake'),must_not_call)
    result=c.get(f"/api/v1/runs/{run['id']}").json()
    assert result['status']=='failed' and result['error']['code']=='review_policy_mismatch'


def test_calibrated_observations_survive_worker_and_api(setup,monkeypatch):
    from test_review_output import respond
    monkeypatch.setenv('RIXIN_REVIEW_POLICY','redlines-v5')
    c,_,v,_,path=setup;run=queue(setup)
    e={'block_id':v['blocks'][0]['id'],'start':0,'end':1,'quote':'合同金额【待填写】'}
    findings=[{'rule_id':f'RL-0{i}','status':'insufficient_evidence','explanation':'需核实','evidence':[e],'suggested_text':None} for i in range(1,6)]
    findings[1].update(status='no_flag_for_target_rule',amount_checks=[{'issue':'no_comparison','evidence':[]}])
    findings[4]['field_checks']=[{'name':'合同金额','value_state':'placeholder','timing':'unknown','evidence':[e],'requirement_evidence':[]}]
    respond(monkeypatch,{'findings':findings})
    assert tick(Store(path),Settings('http://test','fake'))
    result=c.get(f"/api/v1/runs/{run['id']}").json()
    assert result['status']=='needs_input' and result['review_prompt_version']=='redlines-v5'
    assert result['review_schema_sha256']
    assert result['findings'][1]['status']=='no_flag_for_target_rule'
    assert result['findings'][4]['model_proposed_status']=='insufficient_evidence'
    assert result['findings'][4]['field_checks'][0]['timing']=='unknown'


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
