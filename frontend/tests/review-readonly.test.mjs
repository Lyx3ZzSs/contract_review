import {test} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {pathToFileURL} from 'node:url'
const dir=await mkdtemp(join(tmpdir(),'review-readonly-'))
try{
 await build({entryPoints:['src/editors/review-readonly.ts'],bundle:true,platform:'node',format:'esm',outfile:join(dir,'module.mjs')})
 const {createReviewReadonly}=await import(pathToFileURL(join(dir,'module.mjs')))
 test('review ending before lock acknowledgement still restores editing in order',async()=>{
  const calls=[];let release
  const set=createReviewReadonly(async locked=>{calls.push(locked);if(locked)await new Promise(r=>release=r)})
  const start=set(true);await new Promise(r=>setTimeout(r,0));const end=set(false)
  assert.deepEqual(calls,[true]);release();await Promise.all([start,end]);assert.deepEqual(calls,[true,false])
  await set(false);assert.deepEqual(calls,[true,false])
 })
 test('failed mode transition rejects and can be retried without poisoning restoration',async()=>{
  let fail=true;const calls=[]
  const set=createReviewReadonly(async locked=>{calls.push(locked);if(fail){fail=false;throw Error('busy')}})
  await assert.rejects(set(true),/busy/);await set(true);await set(false);assert.deepEqual(calls,[true,true,false])
 })
}finally{await rm(dir,{recursive:true,force:true})}
