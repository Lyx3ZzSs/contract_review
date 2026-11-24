import {test} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
const compiled=await build({entryPoints:['src/editors/proposal-recovery.ts'],bundle:true,platform:'node',format:'esm',write:false})
const {recoverProposal,inspectProposalFailure}=await import('data:text/javascript;base64,'+Buffer.from(compiled.outputFiles[0].text).toString('base64'))
const prepared={id:'o',bookmark:'rx_o',state:'prepared',phase:'saved_unverified',verification_error:'批注未完整保存'}
const applied={...prepared,state:'applied',phase:'verified'},cancelled={...prepared,state:'cancelled'}
function fixture(overrides={}){
 const calls=[]
 const functions={confirm:async()=>{throw Error('核验失败')},load:async()=>prepared,inspect:async()=>({status:'present'}),state:async()=>({modified:false,canSave:false}),cancel:async()=>cancelled,saveAndConfirm:async()=>applied,markClean:()=>{},...overrides}
 const io=Object.fromEntries(Object.entries(functions).map(([name,fn])=>[name,(...args)=>{calls.push(name);return fn(...args)}]))
 return {io,calls}
}
test('saved receipt recovers without inspecting, replaying or saving, and clears false dirty state',async()=>{
 const f=fixture({confirm:async()=>applied})
 assert.equal(await recoverProposal(f.io),applied)
 assert.deepEqual(f.calls,['confirm','state','markClean'])
})
test('confirmed result survives a failed read-only state query',async()=>{
 const f=fixture({confirm:async()=>applied,state:async()=>{throw Error('桥接超时')}})
 assert.equal(await recoverProposal(f.io),applied)
 assert.deepEqual(f.calls,['confirm','state'])
})
test('new manual edits are never cleared when recovering an older successful receipt',async()=>{
 const f=fixture({confirm:async()=>applied,state:async()=>({modified:true,canSave:true})})
 await recoverProposal(f.io);assert.deepEqual(f.calls,['confirm','state'])
})
test('saved but invalid snapshot exposes verification reason without error-4 force-save loop',async()=>{
 const f=fixture()
 await assert.rejects(recoverProposal(f.io),/批注未完整保存/)
 assert.deepEqual(f.calls,['confirm','load','inspect','state'])
})
test('uncertain dirty write is saved once and confirmed without a second content command',async()=>{
 const f=fixture({inspect:async()=>({status:'uncertain'}),state:async()=>({modified:false,canSave:true})})
 assert.equal(await recoverProposal(f.io),applied)
 assert.deepEqual(f.calls,['confirm','load','inspect','state','saveAndConfirm'])
})
test('proven absent write returns cancellation instead of claiming application',async()=>{
 const f=fixture({inspect:async()=>({status:'absent'})})
 assert.equal((await recoverProposal(f.io)).state,'cancelled')
 assert.deepEqual(f.calls,['confirm','load','inspect','cancel'])
})
test('cancel refusal remains prepared and never falls through to an unnecessary save',async()=>{
 const f=fixture({inspect:async()=>({status:'absent'}),cancel:async()=>prepared})
 assert.equal((await recoverProposal(f.io)).state,'prepared')
 assert.deepEqual(f.calls,['confirm','load','inspect','cancel'])
})
test('failed inspection preserves uncertainty without saving or cancelling',async()=>{
 const f=fixture({inspect:async()=>{throw Error('读取失败')}})
 await assert.rejects(recoverProposal(f.io),/读取失败/)
 assert.deepEqual(f.calls,['confirm','load','inspect'])
})
test('lost apply reply performs only inspection and conditional cancellation',async()=>{
 for(const status of ['present','uncertain','absent']){
  const calls=[]
  const result=await inspectProposalFailure({inspect:async()=>{calls.push('inspect');return {status}},cancel:async()=>{calls.push('cancel');return cancelled}})
  assert.deepEqual(calls,status==='absent'?['inspect','cancel']:['inspect'])
  assert.equal(result,status==='absent'?cancelled:undefined)
 }
})
test('prepared write without a business receipt still requests save even if the editor has autosaved',async()=>{
 const f=fixture({load:async()=>({...prepared,phase:'prepared'})})
 assert.equal(await recoverProposal(f.io),applied)
 assert.deepEqual(f.calls,['confirm','load','inspect','state','saveAndConfirm'])
})
