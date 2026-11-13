import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
let dir, createReviewPoller
before(async()=>{
  dir=await mkdtemp(join(tmpdir(),'rixin-poll-tests-'))
  await build({entryPoints:['src/review-polling.ts'],bundle:true,platform:'node',format:'esm',outfile:join(dir,'poll.mjs')})
  ;({createReviewPoller}=await import(pathToFileURL(join(dir,'poll.mjs'))))
})
after(async()=>{await rm(dir,{recursive:true,force:true})})
const pause=ms=>new Promise(r=>setTimeout(r,ms))
test('queued/running tasks refresh until terminal and then stop',async()=>{
  let calls=0
  const poller=createReviewPoller(async()=>++calls<3,()=>assert.fail('unexpected error'),5)
  await poller.refresh();await pause(50);poller.stop()
  assert.equal(calls,3)
})
test('terminal snapshots do not poll but can refresh after a new review',async()=>{
  let calls=0,active=false
  const poller=createReviewPoller(async()=>{calls++;return active},()=>{},5)
  await poller.refresh();await pause(20);assert.equal(calls,1)
  active=true;await poller.refresh();active=false;await pause(30);poller.stop()
  assert.equal(calls,3)
})
test('refresh during a slow read reruns afterward without overlapping',async()=>{
  let calls=0,concurrent=0,max=0
  const poller=createReviewPoller(async()=>{calls++;max=Math.max(max,++concurrent);await pause(15);concurrent--;return false},()=>{},5)
  await Promise.all([poller.refresh(),poller.refresh()]);poller.stop()
  assert.equal(calls,2);assert.equal(max,1)
})
test('unmount during a request cannot restart the timer',async()=>{
  let calls=0
  const poller=createReviewPoller(async()=>{calls++;await pause(15);return true},()=>{},5)
  const work=poller.refresh();poller.stop();await work;await pause(30)
  assert.equal(calls,1)
})
test('manual retry recovers after three failed refreshes',async()=>{
  let calls=0,errors=0
  const poller=createReviewPoller(async()=>{if(++calls<=3)throw new Error('offline');return false},()=>{errors++},5)
  await poller.refresh();await pause(50);assert.equal(calls,3);assert.equal(errors,3)
  await poller.refresh();await pause(20);poller.stop();assert.equal(calls,4)
})
