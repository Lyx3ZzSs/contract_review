import {test,before,after} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {pathToFileURL} from 'node:url'
let dir,reduceExecution
before(async()=>{dir=await mkdtemp(join(tmpdir(),'review-execution-'));await build({entryPoints:['src/review-execution.ts'],bundle:true,platform:'node',format:'esm',outfile:join(dir,'module.mjs')});({reduceExecution}=await import(pathToFileURL(join(dir,'module.mjs'))))})
after(async()=>{await rm(dir,{recursive:true,force:true})})
const state=()=>({schema_version:1,run_id:'r',document_version_id:'v',seq:1,attempt_id:'a',status:'running',tasks:{},issues:{}})
const event=(seq,type,payload={})=>({run_id:'r',document_version_id:'v',attempt_id:'a',seq,type,payload})
test('duplicate delivery is idempotent and gaps require a snapshot',()=>{const s=state(),e=event(2,'task_started',{task_id:'t',title:'核查付款'}),next=reduceExecution(s,e);assert.equal(next.tasks.t.state,'running');assert.equal(reduceExecution(next,e),next);assert.equal(reduceExecution(s,event(3,'task_completed',{task_id:'t'})),null);assert.deepEqual(s.tasks,{})})
test('retry clears old tasks and issues; old attempt cannot write',()=>{const s={...state(),tasks:{old:{id:'old'}},issues:{old:{id:'old'}}};const next=reduceExecution(s,{...event(2,'attempt_started'),attempt_id:'b'});assert.deepEqual(next.tasks,{});assert.deepEqual(next.issues,{});assert.equal(reduceExecution(next,event(3,'task_started',{task_id:'old'})),null)})
test('wrong run/version ignored; final event reconciles with server',()=>{const s=state();assert.equal(reduceExecution(s,{...event(2,'task_started'),run_id:'other'}),s);assert.equal(reduceExecution(s,{...event(2,'task_started'),document_version_id:'old'}),s);assert.equal(reduceExecution(s,event(2,'run_completed')),null)})
test('opinion revision replaces instead of appending; retraction clears it',()=>{let s=reduceExecution(state(),event(2,'issue_upserted',{issue:{id:'i',explanation:'初步'}}));s=reduceExecution(s,event(3,'issue_upserted',{issue:{id:'i',explanation:'校验更新'}}));assert.deepEqual(Object.keys(s.issues),['i']);assert.equal(s.issues.i.explanation,'校验更新');assert.deepEqual(reduceExecution(s,event(4,'issue_retracted',{issue_id:'i'})).issues,{})})

test('plan event persists a complete directory and a retry drops obsolete unit anchors',()=>{
 const plan={revision:1,units:[{id:'v:u1',source_order:0}],scope:'limited'}
 const next=reduceExecution(state(),event(2,'plan_ready',{plan}));assert.deepEqual(next.plan,plan)
 assert.equal(reduceExecution(next,event(3,'attempt_started')).plan,undefined)
})

test('stream draft Unicode deltas, atomic commit and recovery',()=>{
 const draft={issue:{id:'i',title:'核查'},revision:1,state:'generating',fields:{},first_seq:2}
 let s=reduceExecution(state(),event(2,'draft_started',{issue_id:'i',draft}))
 s=reduceExecution(s,event(3,'draft_delta',{issue_id:'i',revision:1,changes:[{field:'explanation',offset:0,text:'中文😀'}]}))
 assert.deepEqual(s.issues,{})
 assert.equal(s.drafts.i.fields.explanation,'中文😀')
 assert.deepEqual(draft.fields,{})
 s=reduceExecution(s,event(4,'draft_delta',{issue_id:'i',revision:1,changes:[{field:'explanation',offset:3,text:'风险'}]}))
 assert.equal(s.drafts.i.fields.explanation,'中文😀风险')
 assert.equal(reduceExecution(s,event(5,'draft_delta',{issue_id:'i',revision:1,changes:[{field:'explanation',offset:0,text:'重复'}]})),null)
 const final=reduceExecution(s,event(5,'issue_upserted',{issue:{id:'i',explanation:'完整校验结果'},proposals:[{id:'p',after_text:'建议'}]}))
 assert.deepEqual(final.drafts,{})
 assert.equal(final.proposals.p.after_text,'建议')
 assert.equal(final.issues.i.explanation,'完整校验结果')
})
test('generation retry resets partial fields, and wrong revision resyncs',()=>{
 let s=reduceExecution(state(),event(2,'draft_started',{issue_id:'i',draft:{issue:{id:'i'},revision:1,state:'generating',fields:{explanation:'旧'}}}))
 s=reduceExecution(s,event(3,'draft_started',{issue_id:'i',draft:{issue:{id:'i'},revision:2,state:'generating',fields:{}}}))
 assert.equal(reduceExecution(s,event(4,'draft_delta',{issue_id:'i',revision:1,changes:[]})),null)
 s=reduceExecution(s,event(4,'draft_failed',{issue_id:'i',revision:2,message:'未完成'}))
 assert.equal(s.drafts.i.state,'failed')
 assert.deepEqual(s.issues,{})
})

test('analysis increments recover Unicode offsets, complete atomically, and clear on retry',()=>{
 let s=reduceExecution(state(),event(2,'phase_updated',{phase:{id:'transaction',title:'交易理解',state:'running'}}))
 const artifact={id:'a',title:'交易分析',revision:1,state:'generating',fields:{},sections:[]}
 s=reduceExecution(s,event(3,'analysis_started',{artifact_id:'a',artifact}))
 s=reduceExecution(s,event(4,'analysis_delta',{artifact_id:'a',revision:1,changes:[{field:'section:0:text',offset:0,text:'合同😀'}]}))
 assert.equal(s.artifacts.a.fields['section:0:text'],'合同😀')
 assert.equal(reduceExecution(s,event(5,'analysis_delta',{artifact_id:'a',revision:1,changes:[{field:'section:0:text',offset:4,text:'错'}]})),null)
 s=reduceExecution(s,event(5,'analysis_completed',{artifact_id:'a',revision:1,sections:[{title:'交易概况',text:'已核对',evidence:[]}]}))
 assert.equal(s.artifacts.a.state,'completed');assert.deepEqual(s.artifacts.a.fields,{})
 assert.deepEqual(artifact.fields,{})
 const reset=reduceExecution(s,event(6,'attempt_started'))
 assert.deepEqual(reset.artifacts,{});assert.deepEqual(reset.phases,{})
})

test('analysis streaming preserves unrelated risk-card references',()=>{
 const s={...state(),drafts:{},proposals:{},artifacts:{a:{id:'a',revision:1,state:'generating',fields:{},sections:[]}}}
 const n=reduceExecution(s,event(2,'analysis_delta',{artifact_id:'a',revision:1,changes:[{field:'section:0:text',offset:0,text:'交易概况'}]}))
 assert.equal(n.issues,s.issues);assert.equal(n.tasks,s.tasks);assert.equal(n.drafts,s.drafts);assert.equal(n.proposals,s.proposals)
 assert.notEqual(n.artifacts,s.artifacts);assert.equal(s.artifacts.a.fields['section:0:text'],undefined)
})
