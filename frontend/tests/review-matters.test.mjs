import {test,before,after} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {pathToFileURL} from 'node:url'
let dir,buildReviewMatters,selectMatter,matterPresentation
before(async()=>{dir=await mkdtemp(join(tmpdir(),'review-matters-'));await build({entryPoints:['src/review-matters.ts'],bundle:true,platform:'node',format:'esm',outfile:join(dir,'module.mjs')});({buildReviewMatters,selectMatter,matterPresentation}=await import(pathToFileURL(join(dir,'module.mjs'))))})
after(async()=>{await rm(dir,{recursive:true,force:true})})
const a={block_id:'v:p1',start:0,end:2,quote:'付款'},b={...a,block_id:'v:p2',quote:'验收'}
const state=()=>({status:'running',tasks:{'e:R1':{id:'e:R1',anchor:a,state:'running',title:'核对付款',first_seq:1},'e:R2':{id:'e:R2',anchor:a,state:'queued',title:'核对争议',first_seq:2}},issues:{}})
const issue=(overrides={})=>({id:'i',rule_id:'R1',event_id:'e',title:'付款条件',status:'flag',explanation:'核对验收',event_anchor:a,evidence:[a,b],suggested_text:null,...overrides})
test('task identity survives opinion arrival, revision and final metadata reconciliation',()=>{
 const s=state(),before=buildReviewMatters(s,[]),after=buildReviewMatters(s,[issue()]),revised=buildReviewMatters(s,[issue({explanation:'补充依据',revision:9})])
 assert.equal(before[0].id,after[0].id);assert.equal(after[0].id,revised[0].id)
 assert.equal(before[0].phase,'checking');assert.equal(after[0].phase,'attention');assert.equal(after[0].evidence.length,2)
 assert.equal(after.length,2);assert.equal(after[1].issues.length,0)
})
test('shared paragraph and shared event do not merge independent rule matters',()=>{
 const m=buildReviewMatters(state(),[issue(),issue({id:'j',rule_id:'R2'})])
 assert.deepEqual(m.map(x=>x.issues.map(i=>i.id)),[['i'],['j']])
 const extra=buildReviewMatters(state(),[issue({id:'other',event_id:'different'})]);assert.equal(extra.length,3)
})
test('same-unit parallel work does not steal the chosen matter',()=>{
 const s=state();s.tasks['e:R2'].state='running';const m=buildReviewMatters(s,[issue()])
 assert.equal(selectMatter(m,'task:e:R1',['v:p1']).id,'task:e:R1')
 assert.equal(selectMatter(m,'task:e:R2',['v:p1']).id,'task:e:R2')
 assert.equal(selectMatter(m,'task:e:R1',['v:missing']),undefined)
})
test('failure stays incomplete even if an older opinion exists; completed is not inferred from navigation',()=>{
 const s=state();s.tasks['e:R1'].state='failed';s.tasks['e:R1'].message='校验失败';const m=buildReviewMatters(s,[issue()])
 assert.equal(m[0].phase,'incomplete');assert.equal(m[0].detail,'校验失败')
 s.tasks['e:R1'].state='completed';assert.equal(buildReviewMatters(s,[])[0].phase,'settling')
 assert.equal(buildReviewMatters(s,[issue({status:'no_flag_for_target_rule'})])[0].phase,'finished')
})
test('retracted opinions disappear while the original task remains; unanchored work is not invented',()=>{
 const s=state();s.tasks.global={id:'global',state:'running'}
 assert.equal(buildReviewMatters(s,[]).length,2)
 assert.equal(buildReviewMatters(s,[issue({event_id:undefined,event_anchor:undefined,evidence:[]})]).length,2)
})
test('explicit event/rule metadata supports task IDs independently of naming conventions',()=>{
 const s={status:'running',tasks:{t:{id:'opaque',event_id:'e',rule_id:'R1',anchor:a,state:'running'}}}
 assert.equal(buildReviewMatters(s,[issue()])[0].issues.length,1)
})

test('a narrower validated quote is emphasized without repainting its whole parent as related evidence',()=>{
 const anchor={block_id:'v:p1',start:0,end:7,quote:'甲方应支付费用'},narrow={block_id:'v:p1',start:2,end:4,quote:'应支'};
 const matter={anchor,issues:[{status:'flag',evidence:[narrow,b]}],evidence:[anchor,narrow,b]};
 assert.deepEqual(matterPresentation(matter),{current:narrow,related:[b]});
 assert.equal(matterPresentation({...matter,issues:[]}).current,anchor);
})
