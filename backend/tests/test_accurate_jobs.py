import pytest
from test_backend import setup
from app.worker import tick
from app.store import Store
from app.llm import Settings


def test_candidate_refuses_missing_rule_coverage(setup,monkeypatch):
    import app.review_jobs as jobs
    import app.accurate_review as accurate
    monkeypatch.setattr(jobs,'active_version',lambda:'review-liability-v1')
    c,cid,version,_,path=setup
    queued=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'accurate'} )
    assert queued.status_code==202,queued.text
    run=queued.json()
    assert run['result_schema_version']=='interactive-review-v2'
    assert len(run['rule_snapshot']['rules'])==7
    def fail(*a,**kw):
        return {'findings':[],'issues':[],'rule_results':[], 'module_errors':[{'module':'facts','code':'invalid_quote'}], 'diagnostics':{'trace':[]}}
    monkeypatch.setattr(accurate,'review_accurate',fail)
    assert tick(Store(path),Settings('http://test','fake'))
    result=c.get(f"/api/v1/runs/{run['id']}")
    assert result.status_code==200,result.text
    data=result.json()
    assert data['status']=='failed'
    assert data['stage']!='done'


def test_actual_candidate_extraction_failure_survives_api(setup,monkeypatch):
    import app.review_jobs as jobs
    import app.accurate_review as accurate
    from app.llm import ExtractionError
    monkeypatch.setattr(jobs,'active_version',lambda:'review-liability-v1')
    def failed(*a,**kw):
        raise ExtractionError('invalid_quote','证据校验失败')
    monkeypatch.setattr(accurate,'extract_call',failed)
    c,cid,_,_,path=setup
    response=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'real-partial'})
    assert response.status_code==202,response.text
    assert tick(Store(path),Settings('http://test','fake'))
    response=c.get(f"/api/v1/runs/{response.json()['id']}")
    assert response.status_code==200,response.text
    run=response.json()
    assert run['status']=='needs_input'
    assert len(run['rule_results'])==7
    assert all(r['execution_state']=='failed' for r in run['rule_results'])
    assert run['module_errors']
    assert run['stage']=='partial'
    assert [i['id'] for i in run['issues']]==[i['id'] for i in run['findings']]
    issue=run['issues'][0]
    response=c.post(f"/api/v1/runs/{run['id']}/issues/{issue['id']}/decisions",json={'action':'acknowledged','note':'保留未完成状态','actor':'test'})
    assert response.status_code==201,response.text


def test_candidate_keeps_policy_with_interactive_and_rejects_hash_drift(setup,monkeypatch):
    import json
    import app.review_jobs as jobs
    monkeypatch.setattr(jobs,'active_version',lambda:'review-grounded-v1')
    monkeypatch.setenv('RIXIN_INTERACTIVE_REVIEW','1')
    c,cid,_,_,path=setup
    response=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'drift'})
    assert response.status_code==202,response.text
    run=response.json()
    assert run['review_prompt_version']=='review-grounded-v1'
    assert run['result_schema_version']=='interactive-review-v2'
    with Store(path).connect() as db:
        run['review_implementation_sha256']='old'
        db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(run),run['id']))
    assert tick(Store(path),Settings('http://test','fake'))
    result=c.get(f"/api/v1/runs/{run['id']}").json()
    assert result['status']=='failed'
    assert result['error']['code']=='review_policy_mismatch'


@pytest.mark.parametrize('interactive',[False,True])
def test_candidate_worker_preserves_unreadable_inline_images_without_bundle(setup,monkeypatch,interactive):
    import json
    import app.review_jobs as jobs
    import app.accurate_review as accurate
    monkeypatch.setattr(jobs,'active_version',lambda:'review-grounded-v1')
    monkeypatch.setenv('RIXIN_INTERACTIVE_REVIEW','1' if interactive else '0')
    c,cid,version,_,path=setup
    with Store(path).connect() as db:
        parsed=json.loads(db.execute('SELECT parsed FROM versions WHERE id=?',(version['id'],)).fetchone()[0])
        parsed['blocks']=[{'id':'v:p1','text':'合同应遵守《附件技术规范》要求。'},{'id':'v:p2','text':'设备运行温度应为零下十度至五十度。'}]
        parsed['image_block_ids']=['v:image1']
        db.execute('UPDATE versions SET parsed=? WHERE id=?',(json.dumps(parsed),version['id']))
    seen=[]
    def fake(settings,model,prompt,schema,payload,validate,deadline,trace):
        seen.append(payload)
        if schema.__name__=='GroundedFacts':
            raw={'attachments':[{'name':'附件技术规范','references':['b1'],'technical_refs':['b1'],'pricing_refs':[]}],'calculations':[],'missing_prices':[],'fields':[]}
        elif schema.__name__=='AssignmentFacts':raw={'clauses':[]}
        elif schema.__name__=='AttachmentResults':raw={'checks':[{'name':'附件技术规范','state':'matched','content_refs':['b2'],'basis_refs':['b1'],'explanation':'正文已包含技术内容'}]}
        else:raw={'findings':[{'rule_id':r,'status':'no_flag_for_target_rule','explanation':'未触发','refs':[]} for r in ['RL-01','RL-04']]}
        value=schema.model_validate(raw)
        return value,validate(value)
    monkeypatch.setattr(accurate,'extract_call',fake)
    response=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'image-case'})
    assert response.status_code==202,response.text
    run=response.json()
    assert bool(run.get('material_bundle_id')) is interactive
    assert tick(Store(path),Settings('http://test','fake'))
    result=c.get(f"/api/v1/runs/{run['id']}")
    assert result.status_code==200,result.text
    data=result.json()
    assert bool(data.get('material_bundle_id')) is interactive
    assert data['coverage']==('parsed_material_bundle' if interactive else 'parsed_document_only')
    assert data['attachment_checks'][0]['attachment_state']=='unreadable'
    assert next(r for r in data['rule_results'] if r['rule_id']=='RL-04')['status']=='insufficient_evidence'
    assert not data['module_errors']
    assert any(p.get('document_contains_unreadable_images') for p in seen)


def test_default_policy_is_verified_accuracy_release(setup,monkeypatch):
    from app.review_policy import active_version
    monkeypatch.delenv('RIXIN_REVIEW_POLICY',raising=False)
    assert active_version()=='review-events-v2'
    c,cid,*_=setup
    response=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'default-release'})
    assert response.status_code==202,response.text
    assert response.json()['review_prompt_version']=='review-events-v2'
    assert len(response.json()['rule_snapshot']['rules'])==7
