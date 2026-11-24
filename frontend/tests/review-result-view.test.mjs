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

test('saved scope warning is retired without hiding other review limitations',()=>{
 const warning='合同类型标签与正文业务范围不一致，请核对。'
 const other='金额检查仅校验可核验的明确算式。'
 const run={diagnostics:{context_warnings:[warning,other,other]},findings:[]}
 assert.deepEqual(model.buildReviewResultView(run).contextWarnings,[other])
 assert.deepEqual(run.diagnostics.context_warnings,[warning,other,other])
})

test('clause identity groups multiple paragraphs without merging repeated clause numbers or unknown locations',()=>{
 const f=(id,block)=>({...finding(id,'flag','CR-06'),event_id:id,evidence:block?[{block_id:block,start:0,end:2,quote:'原文'}]:[]})
 const issues=[f('a','p1'),f('b','p2'),f('c','p3'),f('d'),f('e')]
 const version={id:'v',blocks:[],clauses:[{id:'c1',number:'7.3',block_ids:['p1','p2']},{id:'c2',number:'7.3',block_ids:['p3']}]}
 const groups=model.groupClauseResults(issues,{revision_proposals:[]},version)
 assert.equal(groups.length,4)
 assert.deepEqual(groups[0].issues.map(f=>f.id),['a','b'])
 assert.notEqual(groups[0].id,groups[1].id)
})

test('shared revision is displayed once at its target clause and preserves all risk identities',()=>{
 const issues=['a','b','c'].map((id,i)=>({...finding(id,'flag','CR-06'),event_id:id,evidence:[{block_id:i===2?'p2':'p1',start:0,end:2,quote:'原文'}]}))
 const shared={id:'shared',event_ids:['a','b','c'],anchor:{block_id:'p1'}}
 const original=structuredClone(issues)
 const groups=model.groupClauseResults(issues,{revision_proposals:[shared,shared]},{id:'v',blocks:[{id:'p1',text:'7.3 原文'},{id:'p2',text:'7.4 原文'}]})
 assert.equal(groups.length,2);assert.equal(groups[0].proposals.length,1);assert.equal(groups[1].proposals.length,0)
 assert.equal(groups[1].relatedProposalCount,1)
 assert.deepEqual(issues,original)
})

test('clause groups follow document order regardless of arrival, labels or block IDs',()=>{
 const version={id:'v',blocks:[{id:'p20',text:'前段'},{id:'p3',text:'后段'},{id:'p11',text:'末段'}]}
 const at=(id,block,number)=>({...finding(id,'flag','CR-06'),clause_number:number,event_id:id,event_anchor:{block_id:block,start:0,end:2},evidence:[]})
 const early=at('early','p20','9.3'),late=at('late','p3','1.1'),last=at('last','p11','2.1')
 const missing=at('missing','other-version:p20','0.1')
 const run={revision_proposals:[]}
 const original=structuredClone([last,late,missing,early])
 const expected=['p20','p3','p11','other-version:p20']
 assert.deepEqual(model.groupClauseResults(original,run,version).map(g=>g.id),expected)
 assert.deepEqual(model.groupClauseResults([early,missing,late,last],run,version).map(g=>g.id),expected)
 assert.deepEqual(original,[last,late,missing,early])
})

test('multi-paragraph clauses use their start and retain risk order within a group',()=>{
 const version={id:'v',blocks:['p1','p2','p3'].map(id=>({id,text:'原文'})),clauses:[{id:'first',number:'1',block_ids:['p1','p3']},{id:'second',number:'2',block_ids:['p2']}]}
 const f=(id,block)=>({...finding(id,'flag','CR-06'),evidence:[{block_id:block,start:0,end:2}]})
 const groups=model.groupClauseResults([f('second','p2'),f('first-risk','p3'),f('next-risk','p1')],{revision_proposals:[]},version)
 assert.deepEqual(groups.map(g=>g.id),['first','second'])
 assert.deepEqual(groups[0].issues.map(f=>f.id),['first-risk','next-risk'])
})

test('clauses sharing a paragraph use source span offsets and unlocated items stay independent',()=>{
 const version={id:'v',blocks:[{id:'p1',text:'原文'}],clauses:[{id:'late',number:'1.1',block_ids:['p1'],source_spans:[{block_id:'p1',start:10,end:20}]},{id:'early',number:'9.9',block_ids:['p1'],source_spans:[{block_id:'p1',start:0,end:10}]}]}
 const f=(id,start)=>({...finding(id,'flag','CR-06'),event_anchor:{block_id:'p1',start,end:start+2},evidence:[]})
 const items=[finding('z','flag'),f('late-risk',12),finding('a','flag'),f('early-risk',2)]
 assert.deepEqual(model.groupClauseResults(items,{revision_proposals:[]},version).map(g=>g.id),['early','late','issue:a','issue:z'])
 assert.deepEqual(model.groupClauseResults([...items].reverse(),{revision_proposals:[]},version).map(g=>g.id),['early','late','issue:a','issue:z'])
})

test('shared and supplementary revisions sort by target position without duplication or mutation',()=>{
 const version={id:'v',blocks:['p9','p2','p10'].map(id=>({id,text:'原文'}))}
 const f=(id,block)=>({...finding(id,'flag','CR-06'),event_id:id,event_anchor:{block_id:block,start:0,end:2},evidence:[]})
 const proposal=(id,block,start,event_ids=['a','b'])=>({id,event_ids,anchor:{block_id:block,start,end:start+1}})
 const proposals=[proposal('unknown','missing',0),proposal('early-second','p9',4),proposal('late','p10',0),proposal('early-first','p9',1)]
 const original=structuredClone(proposals)
 const groups=model.groupClauseResults([f('b','p2'),f('a','p9')],{revision_proposals:[...proposals,proposals[3]]},version)
 assert.deepEqual(groups[0].proposals.map(p=>p.id),['early-first','early-second'])
 assert.deepEqual(groups.map(g=>g.id),['p9','p2','p10','missing'])
 assert.deepEqual(groups.flatMap(g=>g.proposals.map(p=>p.id)),['early-first','early-second','late','unknown'])
 assert.equal(groups[0].relatedProposals.find(p=>p.proposalId==='late').groupId,'p10')
 assert.equal(groups[1].relatedProposalCount,4)
 assert.deepEqual(proposals,original)
 assert.deepEqual(model.orderRevisionProposals(proposals,version).map(p=>p.id),['early-first','early-second','late','unknown'])
})


test('risk classification uses explicit schema, never title keywords',()=>{
 assert.equal(model.riskCategory({...finding('a','flag'),title:'管辖条款合法性',category:'legality'}),'other')
 assert.equal(model.riskCategory({...finding('a','flag'),review_category:'procedure'}),'procedure')
 assert.equal(model.riskCategory({...finding('a','flag'),review_category:'unknown'}),'other')
})
test('risk proposals share canonical IDs and retain actual target order',()=>{
 const f={...finding('a','flag'),event_id:'e'}
 const early={id:'early',event_ids:['e'],anchor:{block_id:'p1',start:0}}
 const late={id:'late',event_ids:['e','other'],anchor:{block_id:'p2',start:0}}
 const run={revision_proposals:[late,early,late,{id:'unrelated',event_ids:['other']}]}
 assert.deepEqual(model.linkedProposals(f,run,{blocks:[{id:'p1'},{id:'p2'}]}).map(p=>p.id),['early','late'])
})
test('empty filters and incomplete executions never imply a clean review',()=>{
 assert.match(model.resultEmptyState({status:'completed'},true,false,false).title,/筛选/)
 for(const run of [{status:'failed'},{status:'unknown'},{status:'completed',module_errors:[{message:'失败'}]}]){
  assert.doesNotMatch(model.resultEmptyState(run,false,false,false).title,/未发现|已处理/)
 }
 assert.match(model.resultEmptyState({status:'running'},false,false,false).title,/正在生成/)
 assert.match(model.resultEmptyState({status:'completed'},false,false,true).title,/已处理/)
 assert.match(model.resultEmptyState({status:'completed'},false,false,false).title,/未发现/)
})
