import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
let dir, status
before(async()=>{
  dir=await mkdtemp(join(tmpdir(),'rixin-state-tests-'))
  await build({entryPoints:['src/review-status.ts'],bundle:true,platform:'node',format:'esm',outfile:join(dir,'state.mjs')})
  status=await import(pathToFileURL(join(dir,'state.mjs')))
})
after(async()=>{await rm(dir,{recursive:true,force:true})})
test('business confirmation stays pending and latest opinion wins',()=>{
  const run={findings:[{id:'1',status:'flag'},{id:'2',status:'insufficient_evidence'},{id:'3',status:'no_flag_for_target_rule'}],decisions:[{finding_id:'1',action:'acknowledged'},{finding_id:'1',action:'needs_business_confirmation'},{finding_id:'2',action:'false_positive'}]}
  const summary=status.summarizeReview(run)
  assert.equal(summary.pending,1)
  assert.equal(summary.handled,0)
  assert.equal(summary.decisions.get('1').action,'needs_business_confirmation')
  assert.equal(status.matchesFilter(run.findings[0],summary.decisions.get('1'),'pending'),true)
  assert.equal(status.matchesFilter(run.findings[1],summary.decisions.get('2'),'evidence'),false)
})
test('new evidence shortages appear under verification, clean rules are not human-approved',()=>{
  assert.equal(status.matchesFilter({status:'insufficient_evidence'},undefined,'evidence'),true)
  assert.equal(status.matchesFilter({status:'no_flag_for_target_rule'},undefined,'handled'),false)
  assert.equal(status.summarizeReview(null).pending,0)
})
test('elapsed time freezes on completion, never displays a negative duration',()=>{
  assert.equal(status.elapsedLabel({created_at:'2026-11-10T00:00:00Z',finished_at:'2026-11-10T00:01:05Z'},Date.parse('2026-11-10T01:00:00Z')),'1 分 5 秒')
  assert.equal(status.elapsedLabel({created_at:'2026-11-10T00:00:00Z'},0),'0 秒')
  assert.equal(status.elapsedLabel({},0),'')
})
test('interactive results count independent issues, not five rule summaries',()=>{
  const run={result_schema_version:'interactive-review-v1',findings:[],rule_results:Array.from({length:5},(_,i)=>({id:String(i),status:'flag'})),issues:[{id:'a',status:'no_flag_for_target_rule'},{id:'b',status:'flag'},{id:'c',status:'insufficient_evidence'}],decisions:[{finding_id:'old-b',action:'acknowledged'}]}
  assert.equal(status.summarizeReview(run).pending,1)
  assert.equal(status.summarizeReview(run).handled,0)
})
