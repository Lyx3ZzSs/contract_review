import {test} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
const compiled=await build({entryPoints:['src/editors/onlyoffice-client.ts'],bundle:true,platform:'node',format:'esm',write:false})
const {bridge}=await import('data:text/javascript;base64,'+Buffer.from(compiled.outputFiles[0].text).toString('base64'))
const tick=()=>new Promise(r=>setImmediate(r))
function fixture(){
 let receive;const sent=[],frame={postMessage:m=>sent.push(m)}
 globalThis.window={addEventListener:(_,fn)=>receive=fn,removeEventListener:()=>{}}
 const wire=bridge({querySelector:()=>({contentWindow:frame})},'https://editor.test','doc')
 const reply=(i,ok=true)=>receive({origin:'https://editor.test',source:frame,data:{...sent[i],ok,result:{status:'located'},error:'failure'}})
 return {wire,sent,reply}
}
test('mode restoration waits until navigation has acknowledged completion',async()=>{
 const f=fixture();try{const a=f.wire.send('locate'),b=f.wire.send('mode',{mode:'suggesting'});await tick();assert.deepEqual(f.sent.map(m=>m.action),['locate']);f.reply(0);await a;await tick();assert.deepEqual(f.sent.map(m=>m.action),['locate','mode']);f.reply(1);await b}finally{f.wire.dispose()}
})
test('cancel bypasses pending operations and suppresses stale queued locations',async()=>{
 const f=fixture();try{const a=f.wire.send('bindAnchors'),b=f.wire.send('locate');await tick();const c=f.wire.send('cancelNavigation');assert.deepEqual(f.sent.map(m=>m.action),['bindAnchors','cancelNavigation']);f.reply(1);await c;f.reply(0);await a;assert.equal((await b).status,'interrupted');assert.equal(f.sent.length,2)}finally{f.wire.dispose()}
})
test('a failed operation does not poison the queue; disposed queues cannot dispatch',async()=>{
 const f=fixture();try{const a=f.wire.send('locate'),failed=assert.rejects(a,/failure/),b=f.wire.send('mode');await tick();f.reply(0,false);await failed;await tick();assert.equal(f.sent[1].action,'mode');const c=f.wire.send('state'),closed=assert.rejects(c,/会话已结束/);f.reply(1);f.wire.dispose();await b;await closed;assert.equal(f.sent.length,2)}finally{f.wire.dispose()}
})
test('cancellation suppresses queued view-only evidence updates as well as navigation',async()=>{
 const f=fixture();try{const a=f.wire.send('bindAnchors'),b=f.wire.send('presentEvidence',{reveal:'never'});await tick();const c=f.wire.send('cancelNavigation');f.reply(1);await c;f.reply(0);await a;assert.equal((await b).status,'interrupted');assert.deepEqual(f.sent.map(m=>m.action),['bindAnchors','cancelNavigation'])}finally{f.wire.dispose()}
})

test('optional initialization timeout releases the queue without accepting late replies',async()=>{
 const f=fixture();try{
   const optional=f.wire.send('disableSpellcheck',{},10)
   const failed=assert.rejects(optional,/响应超时/)
   const save=f.wire.send('freeze')
   await failed;await tick()
   assert.deepEqual(f.sent.map(m=>m.action),['disableSpellcheck','freeze'])
   f.reply(0) // A late cosmetic response cannot settle the save barrier.
   let settled=false;void save.then(()=>{settled=true});await tick();assert.equal(settled,false)
   f.reply(1);await save
 }finally{f.wire.dispose()}
})
