import {test} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
const result=await build({entryPoints:['src/review-reference.ts'],bundle:true,platform:'node',format:'esm',write:false})
const {createReferenceNavigator,stableIssueOrder}=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64'))
const point=id=>({title:id,anchor:{block_id:id,start:0,end:2,quote:'原文'}})
function fixture(locate=async()=>true){const states=[],calls=[];let pauses=0,cancels=0;const c=createReferenceNavigator({locate:async(p,valid)=>{calls.push(p.title);return locate(p,valid)},pause:()=>pauses++,cancel:()=>cancels++,changed:s=>states.push(s)});return {c,states,calls,get pauses(){return pauses},get cancels(){return cancels}}}
test('multiple references keep one original reading location and return without advancing it',async()=>{
 const f=fixture();await f.c.open(point('a'),point('b'));await f.c.open(point('c'),point('d'));assert.equal(f.states.at(-1).origin.title,'a');await f.c.back();assert.deepEqual(f.calls,['b','d','a']);assert.equal(f.states.at(-1),null);assert.equal(f.pauses,3)
})
test('failed visit and failed return retain a retryable original location',async()=>{
 let ok=false;const f=fixture(async()=>ok);await f.c.open(point('a'),point('b'));assert.equal(f.states.at(-1).phase,'error');await f.c.back();assert.equal(f.states.at(-1).origin.title,'a');ok=true;await f.c.back();assert.equal(f.c.checkpoint(),null)
})
test('a late navigation cannot overwrite a newer reference or cleared reading context',async()=>{
 let release;const f=fixture(async p=>p.title==='b'?new Promise(r=>release=r):true);const old=f.c.open(point('a'),point('b'));await f.c.open(point('a'),point('c'));release(true);await old;assert.equal(f.states.at(-1).destination.title,'c');assert.equal(f.states.at(-1).phase,'viewing');assert.ok(f.cancels>=2);f.c.clear();assert.equal(f.c.checkpoint(),null)
})
test('scroll interruption invalidates pending callbacks and retains a return point',async()=>{
 let release,valid;const f=fixture(async(_,v)=>{valid=v;return new Promise(r=>release=r)});const work=f.c.open(point('a'),point('b'));f.c.interrupt();assert.equal(valid(),false);release(true);await work;assert.equal(f.states.at(-1).phase,'paused');assert.equal(f.states.at(-1).origin.title,'a')
})
test('refresh restores only verified anchor keys and never saves contract text',async()=>{
 const f=fixture();await f.c.open(point('a'),point('b'));const memory=f.c.checkpoint();assert.doesNotMatch(JSON.stringify(memory),/原文/);const restored=fixture();restored.c.restore(memory,[point('a'),point('b')]);assert.equal(restored.states.at(-1).phase,'paused');assert.equal(restored.calls.length,0);await restored.c.back();assert.deepEqual(restored.calls,['a']);const missing=fixture();missing.c.restore(memory,[point('b')]);assert.equal(missing.c.checkpoint(),null)
})
test('leaving a run suppresses pending reference results',async()=>{
 let release;const f=fixture(async()=>new Promise(r=>release=r));const work=f.c.open(point('a'),point('b'));f.c.dispose();const n=f.states.length;release(true);await work;assert.equal(f.states.length,n)
})
test('opinion updates preserve visible order and append new opinions; withdrawn items disappear',()=>{
 const a={id:'a',explanation:'old'},b={id:'b'},c={id:'c'},updated={...a,explanation:'new'}
 assert.deepEqual(stableIssueOrder(['a','b'],[c,b,updated]),[updated,b,c]);assert.deepEqual(stableIssueOrder(['a','b'],[b,c]),[b,c]);assert.deepEqual(stableIssueOrder([],[]),[])
})
test('two ranges in the same paragraph retain their own identity and return to the original range',async()=>{
 const f=fixture(),a=point('same'),b={...a,anchor:{...a.anchor,start:3,end:5},title:'second range'}
 await f.c.open(a,b);assert.equal(f.states.at(-1).phase,'viewing');assert.equal(f.states.at(-1).origin.anchor.start,0)
 await f.c.back();assert.deepEqual(f.calls,['second range','same']);assert.equal(f.states.at(-1),null)
 await f.c.open(a,a);assert.equal(f.states.at(-1),null)
})
