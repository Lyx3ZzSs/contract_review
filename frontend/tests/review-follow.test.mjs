import {test} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
const result=await build({entryPoints:['src/review-follow.ts'],bundle:true,platform:'node',format:'esm',write:false})
const {createReviewFollower}=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64'))
const target=id=>({key:id,title:id,anchor:{block_id:id,start:0,end:2,quote:'正文'}})
test('task arrival, completion, new findings and old guided controls never move the document',async()=>{
 const calls=[],f=createReviewFollower(async t=>{calls.push(t.key);return true},()=>{})
 f.update([target('a')]);f.update([target('a'),target('b')]);f.setPace('guided');f.toggle();f.update([target('b')],true,undefined,true)
 await new Promise(r=>setTimeout(r,500));assert.deepEqual(calls,[])
 await f.select(target('a'));assert.deepEqual(calls,['a']);f.update([target('a'),target('b')]);assert.deepEqual(calls,['a'])
 await f.advance();assert.deepEqual(calls,['a','b']);f.dispose()
})
test('manual navigation cancellation prevents late success from replacing the selected reference',async()=>{
 let release;const states=[],f=createReviewFollower(t=>t.key==='a'?new Promise(r=>release=r):Promise.resolve(true),s=>states.push(s))
 f.update([target('a'),target('b')]);const old=f.select(target('a'));await f.select(target('b'));release(true);await old;assert.equal(states.at(-1).target.key,'b')
 f.update([target('a')],true,'正文已变更');assert.equal(await f.select(target('a')),false);f.dispose()
})
