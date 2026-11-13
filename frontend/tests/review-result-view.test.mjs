import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
let dir, model
before(async()=>{
  dir=await mkdtemp(join(tmpdir(),'rixin-result-view-'))
  await build({entryPoints:['src/review-result-view.ts'],bundle:true,platform:'node',format:'esm',outfile:join(dir,'view.mjs')})
  model=await import(pathToFileURL(join(dir,'view.mjs')))
})
after(async()=>{await rm(dir,{recursive:true,force:true})})
const finding=(id,status,rule_id='RL-05')=>({id,status,rule_id,explanation:'原判断',evidence:[]})
test('pending and handled partition actionable items without counting clean rules',()=>{
  const run={findings:[finding('a','insufficient_evidence'),finding('b','flag'),finding('c','no_flag_for_target_rule','RL-01')],decisions:[{finding_id:'b',action:'acknowledged'}]}
  const original=structuredClone(run), view=model.buildReviewResultView(run)
  assert.deepEqual(view.pending.map(x=>x.id),['a'])
  assert.deepEqual(view.handled.map(x=>x.id),['b'])
  assert.equal(view.defaultFilter,'pending');assert.deepEqual(run,original)
})
test('latest business confirmation stays pending and old IDs cannot resolve new items',()=>{
  const run={findings:[finding('a','flag')],decisions:[{finding_id:'a',action:'acknowledged'},{finding_id:'a',action:'needs_business_confirmation'},{finding_id:'old',action:'false_positive'}]}
  assert.equal(model.buildReviewResultView(run).pending.length,1)
  assert.equal(model.buildReviewResultView(run).handled.length,0)
})
test('interactive coverage preserves zero and multiple attachment issues independently',()=>{
  const run={result_schema_version:'interactive-review-v1',findings:[],rule_results:[finding('rule','flag','RL-04')],issues:['a','b','c'].map(id=>finding(id,'flag','RL-04')),decisions:[]}
  assert.equal(model.buildReviewResultView(run).coverage.length,1)
  assert.equal(model.buildReviewResultView(run).pending.length,3)
  assert.equal(model.buildReviewResultView({...run,issues:[]}).coverage.length,1)
  assert.equal(model.buildReviewResultView({...run,issues:[]}).pending.length,0)
})
test('empty and clean results are not human-approved; handled-only defaults to handled',()=>{
  assert.equal(model.buildReviewResultView(null).pending.length,0)
  assert.equal(model.buildReviewResultView({findings:[finding('x','not_applicable')]}).handled.length,0)
  assert.equal(model.buildReviewResultView({findings:[finding('x','flag')],decisions:[{finding_id:'x',action:'false_positive'}]}).defaultFilter,'handled')
})
test('attachment category survives a missing upload and category counts exclude clean checks',()=>{
  const run={findings:[finding('clause','no_flag_for_target_rule','RL-01'),finding('missing','insufficient_evidence','RL-04')],decisions:[]}
  const view=model.buildReviewResultView(run)
  assert.deepEqual(view.categories.map(c=>[c.id,c.pending,c.handled]),[['clauses',0,0],['attachments',1,0]])
  assert.equal(view.defaultCategory,'attachments')
  assert.equal(model.resultCategory(run.findings[1]),'attachments')
})
test('handled attachments stay discoverable without manufacturing risk levels or clean issues',()=>{
  const run={findings:[finding('clean','no_flag_for_target_rule'),finding('a','flag','RL-04')],decisions:[{finding_id:'a',action:'false_positive'}]}
  const original=structuredClone(run),view=model.buildReviewResultView(run)
  assert.equal(view.defaultCategory,'attachments')
  assert.equal(view.categories.find(c=>c.id==='attachments').handled,1)
  assert.deepEqual(run,original)
})
test('v3 preserves distinct events in the same clause and counts proposals independently',()=>{
 const issues=[{...finding('a','flag','CR-02'),event_id:'delay',clause_number:'7.4'}, {...finding('b','flag','CR-02'),event_id:'termination',clause_number:'7.4'}, {...finding('c','flag','CR-01'),event_id:'termination',clause_number:'7.4'}, {...finding('context','insufficient_evidence','RL-05'),display_group:'context'}]
 const run={result_schema_version:'interactive-review-v3',issues,findings:[],rule_results:[],revision_proposals:[{proposal_id:'p',event_ids:['termination']}],decisions:[]}
 const view=model.buildReviewResultView(run)
 assert.equal(view.clauseGroups[0].events.length,2)
 assert.equal(view.clauseGroups[0].events[1].issues.length,2)
 assert.equal(view.riskEventCount,2);assert.equal(view.proposalCount,1)
 assert.equal(view.contextItems[0].id,'context')
 assert.equal(view.categories.find(c=>c.id==='context').pending,1)
 assert.equal(model.buildReviewResultView({...run,legal_feedback:[{issue_id:'a',verdict:'agree'}]}).pending.length,4)
})
test('diagnostic context warnings are visible independently of legal event counts',()=>{
 const run={result_schema_version:'interactive-review-v3',issues:[{...finding('a','flag','CR-02'),event_id:'e'}],findings:[],diagnostics:{context_warnings:['业务范围冲突','业务范围冲突']},revision_proposals:[{proposal_id:'a',event_ids:['e']},{proposal_id:'b',event_ids:['e']}]}
 const view=model.buildReviewResultView(run)
 assert.deepEqual(view.contextWarnings,['业务范围冲突'])
 assert.equal(view.riskEventCount,1);assert.equal(view.proposalCount,2);assert.equal(view.pending.length,1)
 assert.deepEqual(model.buildReviewResultView({...run,diagnostics:[]}).contextWarnings,[])
})
