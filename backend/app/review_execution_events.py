"""Durable, attempt-scoped progress. A single writer owns events and heartbeats."""
import asyncio
import json
import queue
import threading
import time
from datetime import datetime
from hashlib import sha256
from fastapi import HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from .rule_registry import CONFIGURED_RULES_POLICY
from .review_jobs import now, dumps
from .llm import ExtractionError


def empty(run):
    return dict(schema_version=2, run_id=run['id'], document_version_id=run['document_version_id'],
                material_bundle_id=run.get('material_bundle_id'), attempt_id=None, seq=0,
                tasks={}, issues={}, drafts={}, proposals={}, phases={}, artifacts={}, status=run['status'])


def issue_identity(run, issue):
    rid=issue['rule_id'];key=issue.get('subject_key',rid)
    return 'issue-'+sha256(f"{run['id']}:{rid}:{key}".encode()).hexdigest()[:24]


def append(db, run, attempt, kind, data):
    row=db.execute('SELECT payload FROM review_execution_states WHERE run_id=?',(run['id'],)).fetchone()
    state=json.loads(row[0]) if row else empty(run)
    if kind=='attempt_started':
        state={**empty(run),'seq':state['seq'],'attempt_id':attempt,'status':'running'}
    elif state['attempt_id']!=attempt:
        raise ExtractionError('lease_lost','执行权已移交后台重试任务')
    state.setdefault('drafts',{});state.setdefault('proposals',{})
    state.setdefault('phases',{});state.setdefault('artifacts',{})
    if kind=='phase_updated':
        phase=dict(data['phase']);phase['updated_at']=now()
        previous=state['phases'].get(phase['id'],{})
        if phase['state']=='running' and previous.get('state')!='running':
            phase['started_at']=phase['updated_at']
        if phase['state'] in ('completed','failed'):
            phase['finished_at']=phase['updated_at']
            if previous.get('started_at'):
                phase['elapsed_seconds']=round((datetime.fromisoformat(phase['finished_at'])-datetime.fromisoformat(previous['started_at'])).total_seconds(),3)
        state['phases'][phase['id']]={**previous,**phase}
        data={'phase':state['phases'][phase['id']]}
    if kind=='coverage_updated':state['coverage']=data['coverage']
    if kind.startswith('analysis_'):
        aid=data['artifact_id'];revision=data['revision'];artifact=state['artifacts'].get(aid)
        if kind=='analysis_started':
            if artifact and revision<=artifact['revision']:return state
            artifact={'id':aid,'title':data['title'],'revision':revision,'state':'generating','fields':{},'sections':[],
                      'first_seq':(artifact or {}).get('first_seq',state['seq']+1)}
            state['artifacts'][aid]=artifact
        elif kind=='analysis_failed' and not artifact:
            artifact={'id':aid,'title':data['title'],'revision':revision,'state':'failed','fields':{},'sections':[]}
            state['artifacts'][aid]=artifact
        elif not artifact or artifact['revision']!=revision or artifact['state'] not in ('generating','validating'):
            return state
        if kind=='analysis_delta':
            for change in data['changes']:
                key=change['field'];old=artifact['fields'].get(key,'')
                if len(old)!=change['offset']:raise ExtractionError('stream_offset_mismatch','分析内容顺序校验失败')
                artifact['fields'][key]=old+change['text']
        if kind=='analysis_section':
            artifact['sections'].append(data['section'])
        if kind=='analysis_validating':
            artifact.update(state='validating',message=data.get('message',''))
        if kind=='analysis_completed':
            artifact.update(state='completed',sections=data['sections'],fields={})
            artifact.pop('message', None)
        if kind=='analysis_failed':artifact.update(state='failed',message=data['message'],fields={})
        # Incremental deltas stay small; full snapshots support refresh/reconnect.
        if kind=='analysis_started':data={**data,'artifact':artifact}
    if kind.startswith('draft_'):
        iid=issue_identity(run,data['issue']);revision=data['revision'];draft=state['drafts'].get(iid)
        if kind=='draft_started':
            if draft and revision<=draft['revision']:return state
            seed={**data['issue'],'id':iid,'run_id':run['id'],'status':'insufficient_evidence','explanation':'','suggested_text':None}
            first_seq=(draft or state['issues'].get(iid) or {}).get('first_seq',state['seq']+1)
            draft={'issue':seed,'revision':revision,'state':'generating','fields':{},'first_seq':first_seq}
            state['drafts'][iid]=draft
            data={'issue_id':iid,'draft':draft}
        else:
            if not draft or draft['revision']!=revision or draft['state'] not in ('generating','validating'):return state
            if kind=='draft_delta':
                for change in data['changes']:
                    key=change['field'];old=draft['fields'].get(key,'')
                    if len(old)!=change['offset']:raise ExtractionError('stream_offset_mismatch','生成内容顺序校验失败')
                    draft['fields'][key]=old+change['text']
            elif kind=='draft_validating':draft['state']='validating'
            elif kind=='draft_failed':draft.update(state='failed',message=data['message'])
            data={k:v for k,v in data.items() if k!='issue'}|{'issue_id':iid}
    if kind=='plan_ready':state['plan']=data['plan']
    if kind.startswith('task_'):
        task=state['tasks'].setdefault(data['task_id'], {'id':data['task_id'],'first_seq':state['seq']+1})
        task.update(data)
        task['state']={'task_discovered':'queued','task_started':'running','task_completed':'completed','task_failed':'failed'}[kind]
    if kind=='issue_upserted':
        issue=dict(data['issue'])
        issue.update(id=issue_identity(run,issue),
                     run_id=run['id'],document_version_id=run['document_version_id'])
        issue['first_seq']=(state['issues'].get(issue['id']) or state['drafts'].get(issue['id']) or {}).get('first_seq',state['seq']+1)
        issue['revision']=state['issues'].get(issue['id'],{}).get('revision',0)+1
        state['issues'][issue['id']]=issue
        state['drafts'].pop(issue['id'],None)
        proposals=data.get('proposals',[])
        for p in proposals:state['proposals'][p.get('proposal_id') or p['id']]=p
        data={'issue':issue,'proposals':proposals}
    if kind=='issue_retracted':
        state['issues'].pop(data['issue_id'],None);state['drafts'].pop(data['issue_id'],None)
    if kind.startswith('run_'):
        state['status']=run['status']
        # Final state is authoritative, including removal of provisional findings.
        previous=state['issues']
        state['issues']={i['id']:{**i,'first_seq':previous.get(i['id'],state['drafts'].get(i['id'],{})).get('first_seq',state['seq']+1)} for i in run.get('issues',run.get('findings',[]))}
        state['proposals']={p.get('proposal_id') or p['id']:p for p in run.get('revision_proposals',[])}
        for aid,artifact in run.get('analysis_artifacts',{}).items():
            state['artifacts'][aid]={**state['artifacts'].get(aid,{}),**artifact}
        if 'review_coverage' in run:state['coverage']=run['review_coverage']
        for artifact in state['artifacts'].values():
            if artifact['state'] in ('generating','validating'):
                artifact.update(state='failed',fields={},message='本项分析未完整结束，候选内容未采纳。')
        for phase in state['phases'].values():
            if phase['state'] in ('queued','running'):
                phase.update(state='failed',message='本阶段未完成。')
        for draft in state['drafts'].values():
            if draft['state']!='failed':draft.update(state='failed',message='本项生成未完成，未采纳候选文本。')
        for task in state['tasks'].values():
            if task['state'] in ('queued','running'):task.update(state='failed',message='本项未完成')
    state['seq']+=1;state['updated_at']=now()
    event={k:state.get(k) for k in ('schema_version','run_id','document_version_id','material_bundle_id','attempt_id','seq')}
    event.update(type=kind,created_at=state['updated_at'],payload=data)
    db.execute('INSERT INTO review_execution_events(run_id,seq,payload) VALUES(?,?,?)',(run['id'],state['seq'],dumps(event)))
    db.execute('INSERT INTO review_execution_states VALUES(?,?) ON CONFLICT(run_id) DO UPDATE SET payload=excluded.payload',(run['id'],dumps(state)))
    return state


class ExecutionReporter:
    def __init__(self,store,run,owner,lease_seconds):
        self.store,self.run,self.owner,self.lease_seconds=store,run,owner,lease_seconds
        self.events=queue.Queue(maxsize=256);self.error=None
        with store.connect() as db:
            self.check(db);append(db,run,owner,'attempt_started',{})
        self.thread=threading.Thread(target=self.work,daemon=True);self.thread.start()

    def check(self,db):
        job=db.execute('SELECT owner,state FROM jobs WHERE run_id=?',(self.run['id'],)).fetchone()
        if not job or job['owner']!=self.owner or job['state']!='running':
            raise ExtractionError('lease_lost','执行权已移交后台重试任务')

    def emit(self,kind,**data):
        if self.error:raise self.error
        # Detach mutable dictionaries before handing them to another thread.
        item=(kind,json.loads(dumps(data)))
        while True:
            if self.error:raise self.error
            try:self.events.put(item,timeout=.25);break
            except queue.Full:continue

    def work(self):
        while True:
            try:item=self.events.get(timeout=min(15,self.lease_seconds/3))
            except queue.Empty:item=('heartbeat',{})
            if item is None:return
            # Drain only already queued events: no deliberate display delay.
            # Keep transactions bounded so readers and checkpoints can proceed.
            batch=[item];stop=False
            while len(batch)<32:
                try:following=self.events.get_nowait()
                except queue.Empty:break
                if following is None:
                    stop=True;break
                batch.append(following)
            try:
                with self.store.connect() as db:
                    self.check(db)
                    db.execute('UPDATE jobs SET lease_until=? WHERE run_id=?',(time.time()+self.lease_seconds,self.run['id']))
                    for pending in batch:
                        if pending[0]!='heartbeat':append(db,self.run,self.owner,*pending)
            except Exception as exc:
                self.error=exc
                return
            if stop:return

    def close(self):
        while self.thread.is_alive():
            try:self.events.put(None,timeout=.25);break
            except queue.Full:continue
        self.thread.join()
        if self.error:raise self.error


def read_state(db,rid):
    row=db.execute('SELECT payload FROM runs WHERE id=?',(rid,)).fetchone()
    if not row:raise HTTPException(404,'审查任务不存在')
    run=json.loads(row[0]);row=db.execute('SELECT payload FROM review_execution_states WHERE run_id=?',(rid,)).fetchone()
    state=json.loads(row[0]) if row else empty(run)
    from .materials import is_stale
    return {**state,'status':run['status'],'stale':is_stale(db,run)}


def register(app,store):
    @app.post('/api/v1/runs/{run_id}/resume',status_code=202)
    def resume(run_id:str):
        from .materials import is_stale
        from .configured_review import implementation_hash
        from .review_jobs import enqueue_review, set_stage, schema_hash
        from .review_policy import prompt_hash
        from .models import ExtractionCreate
        from uuid import uuid4
        with store.connect() as db:
            row=db.execute('SELECT * FROM runs WHERE id=?',(run_id,)).fetchone()
            if not row:raise HTTPException(404,'审查任务不存在')
            run=json.loads(row['payload'])
            if run.get('mode') != 'model_review':
                raise HTTPException(409,'仅模型审查支持重试')
            if is_stale(db,run):raise HTTPException(409,'正文或资料已变化，请基于当前版本发起新审查')
            if row['status'] in ('running','queued'):return run
            if not run.get('module_errors') and row['status']!='failed':
                raise HTTPException(409,'本轮执行已完成，无需恢复')
            version = run.get('review_prompt_version')
            changed = (version != CONFIGURED_RULES_POLICY
                       or run.get('review_implementation_sha256') != implementation_hash()
                       or run.get('review_prompt_sha256') != prompt_hash(version)
                       or run.get('review_schema_sha256') != schema_hash(version))
            handled=db.execute('SELECT 1 FROM decisions WHERE run_id=?',(run_id,)).fetchone() or db.execute('SELECT 1 FROM proposal_operations WHERE run_id=?',(run_id,)).fetchone()
            if changed or handled:
                # Preserve historical results/decisions. Never pretend missing old
                # drafts are recovered, or mix receipts from different policies.
                return enqueue_review(db,row['contract_id'],ExtractionCreate(document_version_id=row['version_id'],idempotency_key=str(uuid4()),model=run['model']),parent_run_id=run_id)
            run.update(status='queued',recovery_count=run.get('recovery_count',0)+1)
            run.pop('finished_at',None);run.pop('error',None)
            set_stage(run,'queued')
            run['progress']='正在恢复未完成任务，已保存结果将继续使用'
            db.execute('UPDATE runs SET status=?,payload=? WHERE id=?',('queued',dumps(run),run_id))
            db.execute("UPDATE jobs SET state='queued',owner=NULL,lease_until=NULL,attempts=0 WHERE run_id=?",(run_id,))
            return run

    @app.get('/api/v1/runs/{run_id}/execution-state')
    def state(run_id:str):
        with store.connect() as db:return read_state(db,run_id)

    @app.get('/api/v1/runs/{run_id}/execution-events')
    def events(run_id:str,after:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=500)):
        with store.connect() as db:
            state=read_state(db,run_id)
            rows=[json.loads(r[0]) for r in db.execute('SELECT payload FROM review_execution_events WHERE run_id=? AND seq>? ORDER BY seq LIMIT ?',(run_id,after,limit))]
            return {'events':rows,'seq':state['seq'],'reset':after>state['seq'],'status':state['status'],'stale':state['stale']}

    @app.get('/api/v1/runs/{run_id}/execution-stream')
    async def stream(run_id:str,request:Request,after:int=Query(0,ge=0)):
        # Validate before streaming headers are sent. Read calls use short transactions.
        await asyncio.to_thread(state,run_id)
        try:cursor=max(after,int(request.headers.get('last-event-id','0')))
        except ValueError:raise HTTPException(400,'事件游标无效')
        from .auth import principal
        user = principal.get()
        async def generate():
            nonlocal cursor
            while not await request.is_disconnected():
                if user is not None and time.time() >= user.expires_at:
                    return
                batch=await asyncio.to_thread(events,run_id,cursor,100)
                if batch['reset']:
                    yield 'event: reset\ndata: {}\n\n';return
                for event in batch['events']:
                    cursor=event['seq']
                    yield f'id: {cursor}\ndata: {dumps(event)}\n\n'
                if batch['status'] not in ('queued','running') and cursor>=batch['seq']:return
                yield ': heartbeat\n\n'
                await asyncio.sleep(.2)
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
