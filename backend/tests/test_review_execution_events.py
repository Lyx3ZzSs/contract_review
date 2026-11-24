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


def test_reporter_drains_backlog_in_bounded_transactions_and_flushes_on_close(setup):
    from contextlib import contextmanager
    c,_,_,_,path=setup;run=queue(setup);store=Store(path)
    original=store.connect;transactions=[];writer_waiting=threading.Event()
    @contextmanager
    def counted():
        transactions.append(1);writer_waiting.set()
        with original() as db:yield db
    reporter=claim(store,run)
    store.connect=counted
    # Hold the write lock to reproduce a backlog without artificial sleeps.
    with original():
        reporter.emit('task_started',task_id='0')
        assert writer_waiting.wait(3)
        for n in range(1,101):reporter.emit('task_started',task_id=str(n))
    reporter.close()
    assert 4<=len(transactions)<=5
    with original() as db:
        state=read_state(db,run['id'])
        seqs=[r[0] for r in db.execute('SELECT seq FROM review_execution_events WHERE run_id=? ORDER BY seq',(run['id'],))]
    assert len(state['tasks'])==101 and state['seq']==102
    assert seqs==list(range(1,103))


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


def test_plan_survives_terminal_and_resets_with_attempt(setup):
    c,_,_,_,path=setup;run=queue(setup);store=Store(path)
    plan={'revision':1,'units':[{'id':'unit-1','source_order':0,'task_ids':['check-1']}],'scope':'候选筛查'}
    with store.connect() as db:
        append(db,run,'a','attempt_started',{})
        append(db,run,'a','plan_ready',{'plan':plan})
        append(db,run,'a','task_started',{'task_id':'check-1'})
        terminal=append(db,{**run,'status':'needs_input'},'a','run_completed',{})
        assert terminal['plan']==plan
        assert terminal['tasks']['check-1']['state']=='failed'
        retry=append(db,run,'b','attempt_started',{})
        assert 'plan' not in retry and retry['tasks']=={}
        with pytest.raises(ExtractionError):append(db,run,'a','plan_ready',{'plan':plan})


def test_draft_replay_revision_offsets_commit_and_terminal(setup):
    c,_,_,_,path=setup;run=queue(setup);store=Store(path)
    issue={'rule_id':'CR-01','subject_key':'stable','title':'责任边界','status':'flag','evidence':[]}
    with store.connect() as db:
        append(db,run,'a','attempt_started',{})
        s=append(db,run,'a','draft_started',{'issue':issue,'revision':1});iid=next(iter(s['drafts']))
        s=append(db,run,'a','draft_delta',{'issue':issue,'revision':1,'changes':[{'field':'explanation','offset':0,'text':'中文😀'}]})
        first=s['drafts'][iid]['first_seq']
        assert not s['issues']
        s=append(db,run,'a','draft_started',{'issue':issue,'revision':2})
        assert s['drafts'][iid]['fields']=={} and s['drafts'][iid]['first_seq']==first
        seq=s['seq']
        s=append(db,run,'a','draft_delta',{'issue':issue,'revision':1,'changes':[{'field':'explanation','offset':3,'text':'旧'}]})
        assert s['seq']==seq and not s['drafts'][iid]['fields']
        p={'id':'p','event_ids':['e'],'after_text':'已验证'}
        s=append(db,run,'a','issue_upserted',{'issue':issue,'proposals':[p]})
        assert not s['drafts'] and s['proposals']['p']==p and s['issues'][iid]['first_seq']==first
        s=append(db,{**run,'status':'needs_input','issues':[s['issues'][iid]],'revision_proposals':[p]},'a','run_completed',{})
        assert s['proposals']['p']==p
    saved=c.get(f"/api/v1/runs/{run['id']}/execution-state").json()
    assert saved['issues'][iid]['first_seq']==first and saved['proposals']['p']==p


def test_analysis_durable_unicode_retry_and_final_reconciliation(setup):
    c,_,_,_,path=setup;run=queue(setup);store=Store(path);reporter=claim(store,run)
    reporter.emit('phase_updated',phase={'id':'transaction','title':'交易理解','state':'running'})
    reporter.emit('analysis_started',artifact_id='a',title='交易分析',revision=1)
    reporter.emit('analysis_delta',artifact_id='a',revision=1,changes=[{'field':'section:0:text','offset':0,'text':'合同😀'}])
    reporter.close()
    state=c.get(f"/api/v1/runs/{run['id']}/execution-state").json()
    assert state['artifacts']['a']['fields']['section:0:text']=='合同😀'
    with store.connect() as db:
        append(db,run,'first','analysis_started',{'artifact_id':'a','title':'交易分析','revision':2})
        # An old model attempt must not corrupt the replacement artifact.
        before=read_state(db,run['id'])['seq']
        append(db,run,'first','analysis_delta',{'artifact_id':'a','revision':1,'changes':[{'field':'section:0:text','offset':3,'text':'旧'}]})
        assert read_state(db,run['id'])['seq']==before
        append(db,run,'first','analysis_delta',{'artifact_id':'a','revision':2,'changes':[{'field':'section:0:text','offset':0,'text':'新分析'}]})
        section={'title':'交易概况','text':'已核对','evidence':[]}
        append(db,run,'first','analysis_section',{'artifact_id':'a','revision':2,'section':section})
        append(db,run,'first','run_failed',{})
        final=read_state(db,run['id'])
        assert final['artifacts']['a']['state']=='failed' and not final['artifacts']['a']['fields']
        assert final['artifacts']['a']['sections']==[section]
        assert final['phases']['transaction']['state']=='failed'
