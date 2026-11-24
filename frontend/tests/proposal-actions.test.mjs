import {test,before,after} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {createRequire} from 'node:module'
let dir,ui
before(async()=>{
 dir=await mkdtemp(join(tmpdir(),'rixin-proposal-actions-'))
 await build({stdin:{contents:`import {createElement} from 'react';import {renderToStaticMarkup} from 'react-dom/server';import {ProposalActionControls,PreviousProposalRecovery,proposalCompletion} from './src/proposal-actions';export {proposalCompletion};export const recoveryTree=props=>PreviousProposalRecovery(props);export const recovery=props=>renderToStaticMarkup(createElement(PreviousProposalRecovery,props));export const tree=props=>ProposalActionControls(props);export const render=props=>renderToStaticMarkup(createElement(ProposalActionControls,props));`,resolveDir:process.cwd()},bundle:true,platform:'node',format:'cjs',jsx:'automatic',outfile:join(dir,'test.cjs')})
 ui=createRequire(import.meta.url)(join(dir,'test.cjs'))
})
after(async()=>{await rm(dir,{recursive:true,force:true})})
const op=(mode,state='applied')=>({id:mode,proposal_id:'p',mode,state,before_version_id:'v',can_undo:true})
const props=(extra={})=>({mode:'ALL',setMode(){},processing:false,disabled:false,allowed:()=>true,reason:()=>'',completed:{comment:false,revision:false},execute(){},confirm(){},undo(){},...extra})
function buttons(node){if(!node||typeof node!=='object')return [];if(Array.isArray(node))return node.flatMap(buttons);return [...(node.type==='button'?[node]:[]),...buttons(node.props?.children)]}
test('completion counts both operations independently and excludes undone or cancelled history',()=>{
 assert.deepEqual(ui.proposalCompletion([op('COMMENT')],'p'),{comment:true,revision:false})
 assert.deepEqual(ui.proposalCompletion([op('COMMENT'),op('MODIFY')],'p'),{comment:true,revision:true})
 assert.deepEqual(ui.proposalCompletion([op('COMMENT'),op('MODIFY','reverted'),op('ALL','cancelled')],'p'),{comment:true,revision:false})
 assert.deepEqual(ui.proposalCompletion([op('ALL')],'other'),{comment:false,revision:false})
})
test('comment followed by revision keeps apply and undo separate',()=>{
 const calls=[]
 const p=props({op:op('COMMENT'),completed:{comment:true,revision:false},allowed:m=>m!=='COMMENT',execute:m=>calls.push(m),undo:()=>calls.push('undo')})
 const html=ui.render(p)
 assert.match(html,/补做修订/);assert.match(html,/撤销上次操作/)
 const nodes=buttons(ui.tree(p))
 nodes.find(b=>b.props['aria-label']==='补做修订').props.onClick()
 assert.deepEqual(calls,['ALL'])
 nodes.find(b=>!b.props['aria-label']&&b.props.onClick===p.undo).props.onClick()
 assert.deepEqual(calls,['ALL','undo'])
})
test('an old comment preference no longer exposes a standalone comment action',()=>{
 const p=props({mode:'COMMENT'})
 assert.doesNotMatch(ui.render(p),/aria-label="添加批注"/)
 assert.match(ui.render(p),/aria-label="接受修注"/)
 const done=ui.render(props({mode:'MODIFY',completed:{comment:false,revision:true}}))
 assert.match(done,/修订已保存/)
 assert.doesNotMatch(done,/补加批注|选择修订操作/)
})
test('fully completed proposal never exposes a new write action',()=>{
 const html=ui.render(props({op:op('ALL'),completed:{comment:true,revision:true}}))
 assert.match(html,/修订与批注均已保存/);assert.doesNotMatch(html,/选择修订操作|接受修注/)
})
test('existing draft can still be accepted as a tracked revision',()=>{
 const calls=[]
 const controls=ui.tree(props({mode:'MODIFY',execute:m=>calls.push(m)}))
 buttons(controls).find(b=>b.props['aria-label']==='接受修订').props.onClick()
 assert.deepEqual(calls,['MODIFY'])
})
test('uncertain saved operation shows the reason and confirmation action instead of reapplying',()=>{
 let confirms=0
 const p=props({op:{...op('ALL','prepared'),verification_error:'批注尚未完整保存'},confirm:()=>confirms++})
 const html=ui.render(p)
 assert.match(html,/批注尚未完整保存/);assert.match(html,/重试保存确认/);assert.doesNotMatch(html,/接受修注|选择修订操作/)
 buttons(ui.tree(p))[0].props.onClick();assert.equal(confirms,1)
 const withoutError=ui.render(props({op:op('ALL','prepared')}))
 assert.match(withoutError,/重试保存确认/)
 assert.match(withoutError,/撤销未完成操作/)
 assert.doesNotMatch(withoutError,/revision-blocker|写入结果待确认/)
})
test('blocking reasons are visible and controls remain disabled while busy',()=>{
 const html=ui.render(props({disabled:true,allowed:()=>false,reason:()=> '目标条款已变化'}))
 assert.match(html,/<p[^>]*role="status"[^>]*>目标条款已变化/)
 assert.match(html,/<button[^>]*aria-label="接受修注"[^>]*disabled=""/)
})

test('previous-run pending operation is recoverable while current-run pending does not duplicate its card',async()=>{
 const calls=[],operation={...op('COMMENT','prepared'),run_id:'old'}
 const p={runId:'current',operation,disabled:false,perform:async(...args)=>calls.push(args)}
 assert.match(ui.recovery(p),/上一轮操作保存结果待确认/)
 const controls=buttons(ui.recoveryTree(p))
 controls[0].props.onClick();controls[1].props.onClick()
 assert.deepEqual(calls,[['p','COMMENT',operation],['p','COMMENT',operation,true]])
 assert.equal(ui.recovery({...p,runId:'old'}),'')
 assert.equal(ui.recovery({...p,operation:{...operation,state:'applied'}}),'')
})
