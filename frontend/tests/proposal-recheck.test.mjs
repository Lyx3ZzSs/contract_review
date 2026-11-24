import {test,before,after} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {createRequire} from 'node:module'
let dir,ui
before(async()=>{
 dir=await mkdtemp(join(tmpdir(),'rixin-recheck-'))
 await build({stdin:{contents:`import {createElement} from 'react';import {renderToStaticMarkup} from 'react-dom/server';import {ProposalRecheckNotice,submitProposalRecheck} from './src/proposal-actions';export {submitProposalRecheck};export const tree=p=>ProposalRecheckNotice(p);export const render=p=>renderToStaticMarkup(createElement(ProposalRecheckNotice,p));`,resolveDir:process.cwd()},bundle:true,platform:'node',format:'cjs',jsx:'automatic',outfile:join(dir,'test.cjs')})
 ui=createRequire(import.meta.url)(join(dir,'test.cjs'))
})
after(async()=>{await rm(dir,{recursive:true,force:true})})
const notice=(status,extra={})=>({value:{status,message:'关联付款条款发生变化',can_retry:status==='failed',document_version_id:'new'},busy:false,error:'',disabled:false,retry(){},...extra})
test('running and completed applicability checks do not display a notice',()=>{
 assert.equal(ui.render(notice('running')),'')
 assert.equal(ui.render(notice('required',{busy:true})),'')
 assert.equal(ui.render(notice('not_required')),'')
 assert.equal(ui.render(notice('completed')),'')
 assert.equal(ui.render(notice('blocked',{value:{status:'blocked',message:'审查尚未完成',can_retry:false,document_version_id:'v'}})),'')
})
test('failed check exposes explicit retry and blocked reason instead of a silent loop',()=>{
 const html=ui.render(notice('failed',{error:'网关超时',disabled:true}))
 assert.match(html,/网关超时/);assert.match(html,/重试局部复核/);assert.match(html,/disabled=""/)
 const blocked=ui.render(notice('blocked'))
 assert.match(blocked,/关联付款条款发生变化/);assert.doesNotMatch(blocked,/重试局部复核/)
})
test('recheck binds expected document version and refreshes after failure without replaying',async()=>{
 const calls=[]
 await ui.submitProposalRecheck({runId:'r',version:'v2',retry:true,current:()=>true,request:async(...args)=>{calls.push(args);throw Error('超时')},onError:x=>calls.push(x),onDone:async()=>calls.push('refresh')})
 assert.deepEqual(calls,[['/runs/r/proposal-rechecks',{expected_version_id:'v2',retry:true}],'超时','refresh'])
})
test('late results from another version or unmounted scope cannot replace current UI',async()=>{
 let reject,current=true;const calls=[]
 const task=ui.submitProposalRecheck({runId:'old',version:'v1',retry:false,current:()=>current,request:()=>new Promise((_,r)=>{reject=r}),onError:x=>calls.push(x),onDone:async()=>calls.push('refresh')})
 current=false;reject(Error('旧请求失败'));await task
 assert.deepEqual(calls,[])
})
