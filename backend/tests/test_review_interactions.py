import json
import pytest
from test_backend import setup, docx
from test_materials import upload
from app.store import Store
from app.llm import Settings, ExtractionError
from app.worker import tick


def pipeline(settings,model,blocks,context,rules,bundle,**kwargs):
    from app.review_issues import build_review_issues
    fs=[{'rule_id':r['id'],'status':'no_flag_for_target_rule','explanation':'本次未见触发','evidence':[],'suggested_text':None} for r in rules]
    checks=[{'reference_name':n,'attachment_name':n,'subject_key':n,'status':'insufficient_evidence','explanation':'本次资料未见',
             'evidence':[],'match_state':'missing','material_bundle_id':bundle['id']} for n in ['技术协议','报价清单']]
    return build_review_issues('',fs,checks,expected_rule_ids=[r['id'] for r in rules]) | {'attachment_checks':checks}


@pytest.fixture
def interactive(setup,monkeypatch):
    monkeypatch.setenv('RIXIN_INTERACTIVE_REVIEW','1')
    c,cid,v,_,path=setup
    response=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'i1'})
    assert response.status_code==202,response.text
    rid=response.json()['id']
    tick(Store(path),Settings('http://test','fake'),pipeline)
    run=c.get(f'/api/v1/runs/{rid}').json()
    assert run.get('result_schema_version')=='interactive-review-v3',run
    return setup,run


def supplement(c,run,ids=None,key='s1',**extra):
    issue=next(i for i in run['issues'] if i['rule_id']=='RL-04')
    return c.post(f"/api/v1/runs/{run['id']}/issues/{issue['id']}/supplements",json={
        'idempotency_key':key,'expected_bundle_id':run['material_bundle_id'],
        'material_version_ids':ids,'statement':'补充核验','actor':'测试法务',**extra})


def test_supplement_is_atomic_idempotent_and_blocks_old_completion(interactive):
    (c,cid,v,_,path),run=interactive
    m=upload(c,cid).json()
    first=supplement(c,run,[m['id']]);assert first.status_code==202,first.text
    assert supplement(c,run,[m['id']]).json()==first.json()
    assert supplement(c,run,[],statement='不同内容').status_code==409
    assert supplement(c,run,[],key='outdated-tab').status_code==409
    assert c.get(f"/api/v1/runs/{run['id']}").json()['stale']
    assert c.post(f"/api/v1/runs/{run['id']}/results",json={'opinion':'完成','reservations':'无','reviewer':'测试'}).status_code==409
    new=c.get(f"/api/v1/runs/{first.json()['review_id']}").json()
    assert new['parent_run_id']==run['id'] and new['status']=='queued'
    with Store(path).connect() as db:
        assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]==2


def test_changed_bundle_is_frozen_and_removing_all_materials_creates_new_revision(interactive):
    (c,cid,_,_,path),run=interactive
    m=upload(c,cid).json()
    r=supplement(c,run,[m['id']]).json()
    tick(Store(path),Settings('http://test','fake'),pipeline)
    new=c.get(f"/api/v1/runs/{r['review_id']}").json()
    assert new['status']=='needs_input',new
    assert new['issues'][0]['id']!=run['issues'][0]['id']
    assert all(i['supersedes_issue_id'] for i in new['issues'])
    result=supplement(c,new,[],key='remove').json()
    old_bundle=c.get(f"/api/v1/contracts/{cid}/material-bundles/{r['bundle_id']}").json()
    now_bundle=c.get(f"/api/v1/contracts/{cid}/material-bundles/{result['bundle_id']}").json()
    assert old_bundle['material_version_ids']==[m['id']] and now_bundle['material_version_ids']==[]
    issue=next(i for i in new['issues'] if i['rule_id']=='RL-04')
    history=c.get(f"/api/v1/runs/{new['id']}/issues/{issue['id']}/history").json()
    assert len(history['items'])==2
    assert history['assertions'][0]['origin']=='user_statement'


def test_cross_contract_material_and_invalid_anchor_roll_back(interactive):
    (c,cid,v,_,path),run=interactive
    other=c.post('/api/v1/contracts',json={'title':'其他','our_party':'甲方','contract_type':'服务'}).json()['id']
    m=upload(c,other).json()
    assert supplement(c,run,[m['id']]).status_code==404
    assert supplement(c,run,[],linked_block_ids=['wrong']).status_code==422
    assert not c.get(f"/api/v1/runs/{run['id']}").json()['stale']
    with Store(path).connect() as db:
        assert db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0]==1


def test_worker_uses_context_snapshot_not_live_contract(interactive,monkeypatch):
    (c,cid,v,_,path),run=interactive
    r=supplement(c,run,[]).json()
    with Store(path).connect() as db:
        value=json.loads(db.execute('SELECT payload FROM contracts WHERE id=?',(cid,)).fetchone()[0])
        value['our_party']='changed'
        db.execute('UPDATE contracts SET payload=? WHERE id=?',(json.dumps(value),cid))
    def observe(settings,model,blocks,context,rules,bundle,**kwargs):
        assert context['our_party']=='乙方'
        return pipeline(settings,model,blocks,context,rules,bundle,**kwargs)
    tick(Store(path),Settings('http://test','fake'),observe)
    new=c.get(f"/api/v1/runs/{r['review_id']}").json()
    assert new['status']=='needs_input' and new['stale']


def test_failed_recheck_retains_previous_results_and_retries_same_bundle(interactive,monkeypatch):
    (c,cid,v,_,path),run=interactive
    next_run=supplement(c,run,[]).json()
    def fail(*args,**kwargs):raise ExtractionError('invalid_review','审查输出校验失败')
    tick(Store(path),Settings('http://test','fake'),fail)
    failed=c.get(f"/api/v1/runs/{next_run['review_id']}").json()
    assert failed['status']=='failed' and not failed['findings']
    assert c.get(f"/api/v1/runs/{run['id']}").json()['findings']==run['findings']
    retry=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'retry'})
    assert retry.status_code==202,retry.text
    assert retry.json()['material_bundle_id']==failed['material_bundle_id']


def test_same_snapshot_new_review_blocks_old_run_finalization(interactive):
    (c,cid,v,_,path),run=interactive
    for issue in run['issues']:
        assert c.post(f"/api/v1/runs/{run['id']}/issues/{issue['id']}/decisions",json={'action':'acknowledged','note':'已核验','actor':'测试'}).status_code==201
    response=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'recheck-same'})
    assert response.status_code==202,response.text
    assert c.post(f"/api/v1/runs/{run['id']}/results",json={'opinion':'完成','reservations':'无','reviewer':'测试'}).status_code==409


def test_same_snapshot_other_model_review_also_blocks_old_finalization(interactive):
    (c,cid,_,_,_),run=interactive
    for issue in run['issues']:
        c.post(f"/api/v1/runs/{run['id']}/issues/{issue['id']}/decisions",json={'action':'acknowledged','note':'已核验','actor':'测试'})
    model='glm-5.3-flash' if run['model']=='deepseek-v4-flash' else 'deepseek-v4-flash'
    assert c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'new-model','model':model}).status_code==202
    assert c.post(f"/api/v1/runs/{run['id']}/results",json={'opinion':'完成','reservations':'无','reviewer':'测试'}).status_code==409


def test_rule_center_matches_interactive_task_and_disable_is_effective(interactive,monkeypatch):
    (c,cid,v,_,path),run=interactive
    policy=c.get('/api/v1/rules').json()['execution_policy']
    assert policy['version']==run['review_prompt_version']
    assert c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'i1','document_version_id':'wrong'}).status_code==409
    monkeypatch.setenv('RIXIN_INTERACTIVE_REVIEW','0')
    assert c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'disabled'}).status_code==503


def test_explicit_empty_links_clear_previous_association(interactive):
    (c,cid,v,_,path),run=interactive
    response=supplement(c,run,[],linked_block_ids=[v['blocks'][0]['id']]).json()
    tick(Store(path),Settings('http://test','fake'),pipeline)
    run2=c.get(f"/api/v1/runs/{response['review_id']}").json()
    bundle=c.get(f"/api/v1/contracts/{cid}/material-bundles/{response['bundle_id']}").json()
    assert len(bundle['links'])==1
    response2=supplement(c,run2,[],key='clear-links',linked_block_ids=[]).json()
    assert c.get(f"/api/v1/contracts/{cid}/material-bundles/{response2['bundle_id']}").json()['links']==[]
