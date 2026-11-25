import json
import time
import pytest
from app.store import Store
from app.llm import Settings, ExtractionError
from app.review_checkpoints import checkpointed_call
from app.revision_proposals import SingleClauseDraft
from test_backend import setup
from test_jobs import queue


def test_receipts_survive_restart_invalidate_inputs_and_reject_old_owner(setup):
    run = queue(setup)
    store = Store(setup[-1])
    with store.connect() as db:
        db.execute("UPDATE jobs SET state='running',owner='one' WHERE run_id=?", (run['id'],))
    calls = []
    def generate(*args):
        calls.append(args[4])
        value = SingleClauseDraft(after_text='修改草稿', rationale='修改依据', missing_context='')
        return value, args[5](value)
    def invoke(wrapper, payload, prompt='prompt'):
        trace = []
        value, _ = wrapper(Settings('test','secret'), 'model', prompt, SingleClauseDraft, payload,
                           lambda v:v, time.monotonic()+10, trace)
        return value, trace
    first = checkpointed_call(store, run, 'one', generate)
    invoke(first, {'text':'原文'})
    with store.connect() as db:
        db.execute("UPDATE jobs SET owner='two' WHERE run_id=?", (run['id'],))
    second = checkpointed_call(store, run, 'two', generate)
    _, trace = invoke(second, {'text':'原文'})
    assert len(calls)==1 and trace[0]['status']=='restored'
    invoke(second, {'text':'新原文'})
    invoke(second, {'text':'原文'}, 'new prompt')
    assert len(calls)==3
    with pytest.raises(ExtractionError, match='执行权'):
        invoke(first, {'text':'原文'})
    with store.connect() as db:
        saved=[json.loads(r[0]) for r in db.execute('SELECT payload FROM review_checkpoints')]
    assert len(saved)==3 and all('secret' not in json.dumps(r) for r in saved)


def test_resume_reuses_run_but_preserves_history_when_implementation_changes(setup):
    client,cid,*_=setup
    run=client.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'recovery'}).json()
    store=Store(setup[-1])
    def fail_run():
        run.update(status='failed',error={'code':'gateway_timeout','message':'超时'})
        with store.connect() as db:
            db.execute('UPDATE runs SET status=?,payload=? WHERE id=?',('failed',json.dumps(run),run['id']))
            db.execute("UPDATE jobs SET state='failed',attempts=2 WHERE run_id=?",(run['id'],))
    fail_run()
    reply=client.post(f"/api/v1/runs/{run['id']}/resume")
    assert reply.status_code==202,reply.text
    assert reply.json()['id']==run['id'] and reply.json()['recovery_count']==1
    assert client.post(f"/api/v1/runs/{run['id']}/resume").json()['id']==run['id']
    run['review_implementation_sha256']='old'
    fail_run()
    reply=client.post(f"/api/v1/runs/{run['id']}/resume")
    assert reply.status_code==202,reply.text
    assert reply.json()['id']!=run['id'] and reply.json()['parent_run_id']==run['id']
    assert client.get(f"/api/v1/runs/{run['id']}").json()['status']=='failed'


def test_liability_resume_only_reissues_the_group_without_a_valid_receipt(setup):
    from collections import Counter
    from app.liability_limit import LimitFacts,ClauseFindings,run_limit,rule_definition
    from app.structured_review import Sources,fail
    run=queue(setup);store=Store(setup[-1])
    with store.connect() as db:
        db.execute("UPDATE jobs SET state='running',owner='worker' WHERE run_id=?", (run['id'],))
    blocks=[dict(id=f'p{i}',text=f'乙方须承担第{i}项损失。') for i in range(1,5)]
    calls=Counter()
    def generate(settings,model,prompt,schema,payload,validate,deadline,trace):
        key=tuple(payload.get('target_refs',[]))
        calls[key]+=1
        if key==('b4',) and calls[key]==1:
            raise fail('invalid_anchor')
        value=(LimitFacts(supplier='乙方',role_refs=['b1'],candidate_refs=['b1','b2','b3','b4'],scenarios=[],uncertainties=[])
               if schema is LimitFacts else ClauseFindings(clause_exposures=[], excluded=[
                   {'ref':ref, 'quote':blocks[int(ref[1:])-1]['text'], 'reason':'需根据具体损失另行确定'}
                   for ref in key
               ]))
        return value,validate(value)
    def invoke(trace):
        return run_limit(checkpointed_call(store,run,'worker',generate),Settings('test','secret'),'model',
                         Sources(blocks),{},dict(our_party='乙方'),rule_definition(),trace,
                         indexed_numbers=True,clause_details=True)
    with pytest.raises(ExtractionError):invoke([])
    trace=[]
    assert invoke(trace)['execution_state']=='completed'
    assert calls=={():1,('b1','b2','b3'):1,('b4',):2}
    assert {e['unit'] for e in trace if e.get('status')=='restored'}=={'facts','group-1'}
