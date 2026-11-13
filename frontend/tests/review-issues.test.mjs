import { test, before, after } from 'node:test'
import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { mkdtemp, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
let dir, issues
before(async()=>{dir=await mkdtemp(join(tmpdir(),'rixin-issues-'));await build({entryPoints:['src/review-issues.ts'],bundle:true,platform:'node',format:'esm',outfile:join(dir,'issues.mjs')});issues=await import(pathToFileURL(join(dir,'issues.mjs')))})
after(async()=>{await rm(dir,{recursive:true,force:true})})
test('legacy results remain unchanged, and no attachment reference invents an issue',()=>{
 const findings=[{id:'old',rule_id:'RL-04',status:'flag'}]
 assert.deepEqual(issues.reviewItems({findings}),findings)
 const current={findings,result_schema_version:'interactive-review-v1',rule_results:findings,issues:[]}
 assert.deepEqual(issues.reviewItems(current),[])
 assert.equal(issues.ruleResults(current).length,1)
 assert.deepEqual(issues.groupReviewIssues(current)[0].issues,[])
})
test('three attachment issues stay in one rule with independent identities',()=>{
 const run={findings:[],result_schema_version:'interactive-review-v1',rule_results:[{rule_id:'RL-04'}],issues:['a','b','c'].map(id=>({id,rule_id:'RL-04'}))}
 assert.equal(issues.ruleResults(run).length,1)
 assert.deepEqual(issues.groupReviewIssues(run)[0].issues.map(x=>x.id),['a','b','c'])
})
test('document, material snapshot and server stale flag independently invalidate results',()=>{
 const run={document_version_id:'v1',material_bundle_id:'b1'}
 assert.equal(issues.isReviewStale(run,'v1','b1'),false)
 assert.equal(issues.isReviewStale(run,'v2','b1'),true)
 assert.equal(issues.isReviewStale(run,'v1','b2'),true)
 assert.equal(issues.isReviewStale({...run,stale:true},'v1','b1'),true)
})
test('pending re-review shows latest completed historical results, not an earlier failed run',()=>{
 const runs=[{id:'next',status:'running',findings:[]},{id:'failed',status:'failed',findings:[]},{id:'old',status:'completed',findings:[{id:'a'}]}]
 assert.equal(issues.previousCompletedRun(runs)?.id,'old')
 assert.equal(issues.previousCompletedRun([{id:'current',status:'completed',findings:[]}]),null)
})
test('external evidence resolves only within the reviewed bundle and validates Unicode offsets',()=>{
 const evidence={block_id:'m1:p1',start:1,end:3,quote:'😀附'}
 const materials=[{id:'m1',filename:'附件.docx',blocks:[{id:'m1:p1',text:'甲😀附件乙'}]}]
 assert.deepEqual(issues.materialEvidence(evidence,materials),{material:materials[0],before:'甲',quote:'😀附',after:'件乙'})
 assert.equal(issues.materialEvidence({...evidence,quote:'错误'},materials),null)
 assert.equal(issues.materialEvidence({...evidence,block_id:'other:p1'},materials),null)
})
test('restored body associations belong to this attachment and document only',()=>{
 const links=[{reference_name:'技术附件',target_material_version_id:null,target_block_ids:['p1','gone']},{reference_name:'其他附件',target_block_ids:['p2']},{reference_name:'技术附件',target_material_version_id:'m1',target_block_ids:['m1:p1']}]
 assert.deepEqual(issues.linkedBodyBlocks({attachment_name:'技术附件'},links,[{id:'p1'},{id:'p2'}]),['p1'])
 assert.deepEqual(issues.linkedBodyBlocks({rule_id:'RL-02'},links,[{id:'p1'}]),[])
})
test('finalization follows the latest review and material snapshot, preserving unchanged legacy results',()=>{
 const run={id:'r1',status:'completed',document_version_id:'v1',material_bundle_id:'b1'}
 const result={id:'f1',document_version_id:'v1',created_at:'2026-11-10T10:00:00Z',run_id:'r1',review_snapshot:run}
 assert.equal(issues.isCurrentFinalization(result,run,'v1'),true)
 for(const latest of [{...run,id:'r2'}, {...run,stale:true}, {...run,status:'running'}, {...run,material_bundle_id:'b2'}])assert.equal(issues.isCurrentFinalization(result,latest,'v1'),false)
 assert.equal(issues.isCurrentFinalization(result,run,'v2'),false)
 assert.equal(issues.isCurrentFinalization(result,run,'v1','2026-11-10T11:00:00Z'),false)
 const legacy={document_version_id:'v1',created_at:'2026-11-10T10:00:00Z',review_snapshot:{id:'old',document_version_id:'v1',status:'completed'}}
 assert.equal(issues.isCurrentFinalization(legacy,legacy.review_snapshot,'v1'),true)
 assert.equal(issues.isCurrentFinalization({...legacy,review_snapshot:undefined},null,'v1'),true)
})
test('accepted supplement persists a queued review before a failed synchronization without reposting',async()=>{
 const previous={id:'r1',status:'completed',document_version_id:'v1',material_bundle_id:'b1',findings:[{id:'old-risk'}],issues:[{id:'old-risk'}],decisions:[{finding_id:'old-risk',action:'acknowledged'}]}
 let state, failure, reads=0
 await issues.acceptSubmittedReview(previous,{review_id:'r2',bundle_id:'b2',parent_run_id:'r1'},value=>{state=value},async()=>{reads++;throw new Error('offline')},error=>{failure=error})
 assert.equal(state.id,'r2');assert.equal(state.material_bundle_id,'b2');assert.equal(state.status,'queued')
 assert.deepEqual(state.findings,[]);assert.deepEqual(state.issues,[]);assert.deepEqual(state.decisions,[])
 assert.equal(failure,'offline');assert.equal(reads,1)
 assert.equal(previous.findings[0].id,'old-risk')
})
test('a finalized needs-input review stays complete after its pending items were handled',()=>{
 const run={id:'r1',status:'needs_input',document_version_id:'v1'}
 assert.equal(issues.isCurrentFinalization({run_id:'r1',document_version_id:'v1',created_at:'2026-11-10T10:00:00Z',review_snapshot:run},run,'v1'),true)
})
test('v2 reads issues and tracks incomplete modules independently of risk status',()=>{
 const run={result_schema_version:'interactive-review-v2',findings:[],issues:[{id:'cr',rule_id:'CR-01'}],rule_results:[{rule_id:'CR-01',execution_state:'completed'}],module_errors:[{module:'amount',code:'invalid',message:'failed'}]}
 assert.equal(issues.reviewItems(run).length,1)
 assert.equal(issues.hasIncompleteReview(run),true)
 assert.equal(issues.coverageGroups(run)[1].rules[0].state,'completed')
 assert.equal(issues.coverageGroups({findings:[]})[1].rules[0].state,'uncovered')
})
test('coverage includes every configured and returned rule beyond the historical seven',()=>{
 const run={result_schema_version:'interactive-review-v3',findings:[],rule_snapshot:{rules:[{id:'CR-03'},{id:'CR-04'},{id:'CR-05'}]},rule_results:[{rule_id:'CR-03',execution_state:'completed'},{rule_id:'CR-05',execution_state:'failed'},{rule_id:'CUSTOM-01',execution_state:'completed'}]}
 const rows=issues.coverageGroups(run).flatMap(g=>g.rules)
 assert.equal(rows.find(r=>r.id==='CR-03').state,'completed')
 assert.equal(rows.find(r=>r.id==='CR-04').state,'not_run')
 assert.equal(rows.find(r=>r.id==='CR-05').state,'failed')
 assert.equal(rows.find(r=>r.id==='CUSTOM-01').state,'completed')
 assert.equal(new Set(rows.map(r=>r.id)).size,rows.length)
})
