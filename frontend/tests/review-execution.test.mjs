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
