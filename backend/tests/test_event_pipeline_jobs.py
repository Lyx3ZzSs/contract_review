from test_backend import setup
from app.worker import tick
from app.store import Store
from app.llm import Settings

def test_v2_business_route_normalizes_and_preserves_exact_proposal(setup,monkeypatch):
    import json
    import app.event_review_v2 as ep
    monkeypatch.setenv('RIXIN_REVIEW_POLICY','review-events-v2')
    c,cid,version,_,path=setup
    with Store(path).connect() as db:
        contract=json.loads(db.execute('SELECT payload FROM contracts WHERE id=?',(cid,)).fetchone()[0]);contract['our_party']='乙方 · 服务提供方'
        db.execute('UPDATE contracts SET payload=? WHERE id=?',(json.dumps(contract),cid))
    observed=[]
    def fake(settings,model,blocks,context,rules,**kw):
        observed.append((context,kw))
        return {'rule_results':[{'rule_id':r['id'],'status':'no_flag_for_target_rule','explanation':'已检查','evidence':[],'execution_state':'completed'} for r in rules], 'issues':[], 'revision_proposals':[{'proposal_id':'probe','state':'draft','operation':'delete','after_text':''}], 'module_errors':[], 'context_snapshot':context}
    monkeypatch.setattr(ep,'review_events_pipeline',fake)
    q=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'v2-business'})
    assert q.status_code==202,q.text
    assert q.json()['context_snapshot']['our_party_code']=='party_b'
    assert len(q.json()['rule_snapshot']['rules'])==7
    assert tick(Store(path),Settings('http://test','x'))
    result=c.get('/api/v1/runs/'+q.json()['id']).json()
    assert result['status']=='needs_input',result
    assert result['revision_proposals'][0]['after_text']==''
    assert not result['stale']
    assert 'case_guidance_snapshot' in observed[0][1]

def test_case_guidance_change_cannot_reuse_idempotency_key(setup,monkeypatch):
    import app.case_guidance as guidance
    monkeypatch.setenv('RIXIN_REVIEW_POLICY','review-events-v2')
    snapshot={'version':'first','entries':[]}
    monkeypatch.setattr(guidance,'freeze_runtime_guidance',lambda *a:dict(snapshot))
    c,cid,*_=setup
    assert c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'guidance'}).status_code==202
    snapshot['version']='second'
    assert c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'guidance'}).status_code==409


def test_v3_job_uses_real_ui_role_and_preserves_proposals(setup,monkeypatch):
    import json
    import app.event_review_pipeline as ep
    monkeypatch.setenv('RIXIN_REVIEW_POLICY','review-events-v1')
    c,cid,version,_,path=setup
    with Store(path).connect() as db:
        contract=json.loads(db.execute('SELECT payload FROM contracts WHERE id=?',(cid,)).fetchone()[0]);contract['our_party']='乙方 · 服务提供方'
        db.execute('UPDATE contracts SET payload=? WHERE id=?',(json.dumps(contract),cid))
    observed=[]
    def fake(settings,model,blocks,context,rules,**kw):
        observed.append(context)
        return {'rule_results':[{'rule_id':r['id'],'status':'no_flag_for_target_rule','explanation':'已检查','evidence':[],'execution_state':'completed'} for r in rules], 'issues':[], 'revision_proposals':[], 'module_errors':[], 'context_snapshot':context}
    monkeypatch.setattr(ep,'review_events_pipeline',fake)
    q=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'v3'})
    assert q.status_code==202,q.text
    assert q.json()['result_schema_version']=='interactive-review-v3'
    assert q.json()['context_snapshot']['our_party_code']=='party_b'
    assert tick(Store(path),Settings('http://test','x'))
    r=c.get('/api/v1/runs/'+q.json()['id']);assert r.status_code==200,r.text
    assert r.json()['module_errors']==[] and observed[0]['our_party']=='乙方'
    assert r.json()['stale'] is False
    assert r.json()['casebook_version']=='casebook-empty-v1'
