import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from app.store import Store
from app.review_execution_events import ExecutionReporter, append, read_state
from app.llm import ExtractionError, Settings
from app.worker import tick
from test_backend import setup, docx
from test_jobs import queue, fake


def claim(store,run,owner='first'):
    with store.connect() as db:
        db.execute("UPDATE jobs SET owner=?,state='running',lease_until=? WHERE run_id=?",(owner,time.time()+30,run['id']))
    return ExecutionReporter(store,run,owner,30)


def test_incremental_atomic_snapshot_and_order(setup):
    c,_,_,_,path=setup;run=queue(setup);store=Store(path);reporter=claim(store,run)
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n:reporter.emit('task_started',task_id=str(n),title=f'任务 {n}'),range(12)))
    issue={'rule_id':'CR-01','subject_key':'stable','title':'责任边界','status':'insufficient_evidence','evidence':[]}
    reporter.emit('issue_upserted',issue=issue);reporter.emit('issue_upserted',issue=issue|{'explanation':'更新'})
    reporter.close()
    state=c.get(f"/api/v1/runs/{run['id']}/execution-state").json()
    assert state['seq']==15 and len(state['tasks'])==12 and len(state['issues'])==1
    assert next(iter(state['issues'].values()))['revision']==2
    batch=c.get(f"/api/v1/runs/{run['id']}/execution-events?after=10&limit=3").json()
    assert [e['seq'] for e in batch['events']]==[11,12,13]
    assert c.get(f"/api/v1/runs/{run['id']}/execution-events?after=99").json()['reset']
    assert c.get('/api/v1/runs/missing/execution-state').status_code==404
    assert c.get(f"/api/v1/runs/{run['id']}/execution-events?after=-1").status_code==422


def test_attempt_reset_and_late_owner_rejected(setup):
    c,_,_,_,path=setup;run=queue(setup);store=Store(path);first=claim(store,run)
    first.emit('task_started',task_id='old');first.close()
    second=claim(store,run,'second');second.emit('task_started',task_id='new');second.close()
    state=c.get(f"/api/v1/runs/{run['id']}/execution-state").json()
    assert state['attempt_id']=='second' and list(state['tasks'])==['new']
    with store.connect() as db:
        with pytest.raises(ExtractionError):first.check(db)


def test_terminal_reconciliation_stream_and_stale(setup):
    c,cid,v,_,path=setup;run=queue(setup)
    tick(Store(path),Settings('http://test','fake'),fake)
    state=c.get(f"/api/v1/runs/{run['id']}/execution-state").json()
    assert state['status']=='needs_input'
    final=c.get(f"/api/v1/runs/{run['id']}").json()
    assert set(state['issues'])=={i['id'] for i in final['findings']}
    stream=c.get(f"/api/v1/runs/{run['id']}/execution-stream",headers={'Last-Event-ID':str(state['seq']-1)})
    assert 'run_completed' in stream.text and 'attempt_started' not in stream.text
    assert c.post(f'/api/v1/contracts/{cid}/versions',data={'expected_version_id':v['id']},files={'file':('new.docx',docx('新正文'))}).status_code==201
    assert c.get(f"/api/v1/runs/{run['id']}/execution-state").json()['stale']


def test_pipeline_publishes_fast_event_before_slow_one(monkeypatch):
    from app import event_review_v2 as pipeline
    from app.rule_registry import resolve_rules
    events=[];release=threading.Event()
    def assessment(settings,model,prompt,schema,payload,validate,deadline,trace):
        if payload['event']['ref']=='b1':
            assert release.wait(3), 'fast event was held behind slow event'
        # Deliberate extraction failure isolates scheduling from model semantics.
        raise ExtractionError('probe','隔离验证失败')
    def baseline(*args,**kwargs):
        return {'issues':[],'rule_results':[{'rule_id':f'RL-0{i}','status':'no_flag_for_target_rule','explanation':'未触发','evidence':[]} for i in range(1,6)],'module_errors':[]}
    def emit(kind,**data):
        events.append((kind,data))
        if kind=='task_failed' and data['task_id'].startswith(fast_id):release.set()
    blocks=[{'id':'a','text':'9.1 乙方每次违约扣款100元。'},{'id':'b','text':'9.2 乙方每次违约扣款200元。'}]
    from app.structured_review import Sources
    from app.review_events import indexed_events,validate_events,EventResults
    issues=validate_events(EventResults(events=indexed_events(Sources(blocks))),Sources(blocks),{'document_version_id':'v'})
    assert len(issues)>=2
    fast_id=next(i['event_id'] for i in issues if i['event_anchor']['block_id']=='b')
    monkeypatch.setattr(pipeline,'extract_call',assessment);monkeypatch.setattr(pipeline,'review_accurate',baseline)
    pipeline.review_events_pipeline(Settings('test','x'),'m',blocks,{'our_party':'乙方'},resolve_rules('review-events-v2'),document_version_id='v',execution_callback=emit)
    finished=[data['task_id'] for kind,data in events if kind=='task_failed']
    assert finished[0].startswith(fast_id)
