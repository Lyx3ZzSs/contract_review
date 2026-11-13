"""Durable, attempt-scoped progress. A single writer owns events and heartbeats."""
import asyncio
import json
import queue
import threading
import time
from hashlib import sha256
from fastapi import HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from .review_jobs import now, dumps
from .llm import ExtractionError


def empty(run):
    return dict(schema_version=1, run_id=run['id'], document_version_id=run['document_version_id'],
                material_bundle_id=run.get('material_bundle_id'), attempt_id=None, seq=0,
                tasks={}, issues={}, status=run['status'])


def append(db, run, attempt, kind, data):
    row=db.execute('SELECT payload FROM review_execution_states WHERE run_id=?',(run['id'],)).fetchone()
    state=json.loads(row[0]) if row else empty(run)
    if kind=='attempt_started':
        state={**empty(run),'seq':state['seq'],'attempt_id':attempt,'status':'running'}
    elif state['attempt_id']!=attempt:
        raise ExtractionError('lease_lost','执行权已移交后台重试任务')
    if kind.startswith('task_'):
        task=state['tasks'].setdefault(data['task_id'], {'id':data['task_id'],'first_seq':state['seq']+1})
        task.update(data)
        task['state']={'task_discovered':'queued','task_started':'running','task_completed':'completed','task_failed':'failed'}[kind]
    if kind=='issue_upserted':
        issue=dict(data['issue']);rid=issue['rule_id'];key=issue.get('subject_key',rid)
        issue.update(id='issue-'+sha256(f"{run['id']}:{rid}:{key}".encode()).hexdigest()[:24],
                     run_id=run['id'],document_version_id=run['document_version_id'])
        issue['first_seq']=state['issues'].get(issue['id'],{}).get('first_seq',state['seq']+1)
        issue['revision']=state['issues'].get(issue['id'],{}).get('revision',0)+1
        state['issues'][issue['id']]=issue;data={'issue':issue}
    if kind=='issue_retracted':state['issues'].pop(data['issue_id'],None)
    if kind.startswith('run_'):
        state['status']=run['status']
        # Final state is authoritative, including removal of provisional findings.
        state['issues']={i['id']:i for i in run.get('issues',run.get('findings',[]))}
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
        self.events=queue.Queue();self.error=None
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
        self.events.put((kind,json.loads(dumps(data))))

    def work(self):
        while True:
            try:item=self.events.get(timeout=min(15,self.lease_seconds/3))
            except queue.Empty:item=('heartbeat',{})
            if item is None:return
            try:
                with self.store.connect() as db:
                    self.check(db)
                    db.execute('UPDATE jobs SET lease_until=? WHERE run_id=?',(time.time()+self.lease_seconds,self.run['id']))
                    if item[0]!='heartbeat':append(db,self.run,self.owner,*item)
            except Exception as exc:
                self.error=exc
                return

    def close(self):
        self.events.put(None);self.thread.join()
        if self.error:raise self.error


def read_state(db,rid):
    row=db.execute('SELECT payload FROM runs WHERE id=?',(rid,)).fetchone()
    if not row:raise HTTPException(404,'审查任务不存在')
    run=json.loads(row[0]);row=db.execute('SELECT payload FROM review_execution_states WHERE run_id=?',(rid,)).fetchone()
    state=json.loads(row[0]) if row else empty(run)
    from .materials import is_stale
    return {**state,'status':run['status'],'stale':is_stale(db,run)}


def register(app,store):
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
        async def generate():
            nonlocal cursor
            while not await request.is_disconnected():
                batch=await asyncio.to_thread(events,run_id,cursor,100)
                if batch['reset']:
                    yield 'event: reset\ndata: {}\n\n';return
                for event in batch['events']:
                    cursor=event['seq']
                    yield f'id: {cursor}\ndata: {dumps(event)}\n\n'
                if batch['status'] not in ('queued','running') and cursor>=batch['seq']:return
                yield ': heartbeat\n\n'
                await asyncio.sleep(1)
        return StreamingResponse(generate(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
