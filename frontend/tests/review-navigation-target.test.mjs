import {test} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
const result=await build({entryPoints:['src/review-navigation-target.ts'],bundle:true,platform:'node',format:'esm',write:false})
const {reviewNavigationTarget:target}=await import('data:text/javascript;base64,'+Buffer.from(result.outputFiles[0].text).toString('base64'))
const version=(id,texts)=>({id,blocks:texts.map((text,i)=>({id:`${id}:${i}`,text}))})
const evidence={block_id:'old:1',start:0,end:2,quote:'原文'}
test('saved new version with identical text rebinds IDs including repeated paragraphs',()=>{
 const a=version('old',['原文','原文']),b=version('new',['原文','原文'])
 assert.deepEqual(target(evidence,a,b),{documentVersionId:'new',blockId:'new:1',start:0,end:2,quote:'原文',paragraph:'原文',blocks:b.blocks})
})
test('unchanged unique paragraph remains locatable after other paragraphs change or move',()=>{
 assert.equal(target(evidence,version('old',['标题','原文']),version('new',['新标题','新增','原文'])).blockId,'new:2')
})
test('ambiguous repeated paragraphs cannot receive old evidence offsets',()=>{
 const a=version('old',['标题','原文'])
 assert.throws(()=>target(evidence,a,version('new',['新标题','原文','原文'])),/无法唯一确认/)
 assert.throws(()=>target(evidence,version('old',['原文','原文']),version('new',['标题','原文'])),/无法唯一确认/)
})
test('evidence is validated with Unicode code point offsets and strict bounds',()=>{
 const a=version('old',['标题','😀原文']),e={...evidence,start:1,end:3}
 assert.equal(target(e,a,a).quote,'原文')
 assert.throws(()=>target({...e,end:99},a,a),/证据校验失败/)
 assert.throws(()=>target({...e,quote:'错误'},a,a),/证据校验失败/)
})

function navigate(old,now,quote,index=0,occurrence=0){
 let at=-1;for(let i=0;i<=occurrence;i++)at=old[index].indexOf(quote,at+1)
 assert.ok(at>=0)
 const start=Array.from(old[index].slice(0,at)).length
 const result=target({block_id:`old:${index}`,start,end:start+Array.from(quote).length,quote},version('old',old),version('new',now))
 assert.equal(Array.from(result.paragraph).slice(result.start,result.end).join(''),result.quote)
 assert.equal(result.paragraph,now[Number(result.blockId.split(':')[1])])
 return result
}
test('editing before and after evidence rebases exact Unicode offsets',()=>{
 for(const now of ['甲方支付100元，期限五日。','甲方应支付100元，期限十日。','😀甲方应支付100元，期限十日。','甲方支付100元，期限十日。 ']){
  const r=navigate(['甲方支付100元，期限十日。'],[now],'100元')
  assert.equal(r.quote,'100元');assert.equal(r.start,Array.from(now.slice(0,now.indexOf('100元'))).length)
  assert.match(r.navigationNotice,/仍保留的引用/)
 }
})
test('repeated paragraphs retain identity through verified surrounding order',()=>{
 const old=['第一条','相同正文','第二条','相同正文','尾文']
 for(const i of [1,3])assert.equal(navigate(old,['新增',...old],'相同正文',i).blockId,`new:${i+1}`)
})
test('split and merged paragraphs locate retained evidence in its current paragraph',()=>{
 assert.equal(navigate(['甲方支付100元。乙方交货。'],['甲方支付100元。','乙方交货。'],'100元').blockId,'new:0')
 const r=navigate(['甲方支付100元。','乙方交货。'],['甲方支付100元。乙方交货。'],'乙方交货',1)
 assert.equal(r.start,9);assert.equal(r.quote,'乙方交货')
})
test('modified evidence navigates to the current paragraph without a notice',()=>{
 const r=navigate(['甲方应于十日内支付100元。'],['甲方应于十日内支付200元。'],'100元')
 assert.equal(r.quote,'甲方应于十日内支付200元。');assert.equal(r.start,0)
 assert.equal(r.navigationNotice,undefined)
})
test('repeated quotes use context and never choose the first hit',()=>{
 const r=navigate(['甲方支付100元，乙方支付100元。'],['说明：甲方支付100元，乙方支付100元。'],'100元',0,1)
 assert.equal(r.start,16);assert.equal(r.quote,'100元')
})
test('deleted paragraph, unrelated replacement and ambiguous duplicates stay blocked',()=>{
 assert.throws(()=>navigate(['前文','甲方支付100元。','尾文'],['前文','尾文'],'100元',1),/已删除/)
 assert.throws(()=>navigate(['甲方支付100元。'],['协议自签署日起生效。'],'100元'),/无法唯一确认/)
 assert.throws(()=>navigate(['相同正文','相同正文'],['相同正文'],'相同正文',1),/无法唯一确认/)
})
test('noninteger offsets and contradictory same-version snapshots are rejected',()=>{
 const a=version('old',['标题','原文'])
 for(const start of [.5,NaN])assert.throws(()=>target({...evidence,start},a,a),/证据校验失败/)
 assert.throws(()=>target(evidence,a,version('old',['标题','原文已改'])),/快照/)
})
test('large changed regions have an explicit bounded failure',()=>{
 assert.throws(()=>navigate(['甲'.repeat(1100)+'原文'],['乙'.repeat(1100)+'原文'],'原文'),/变化范围较大/)
})
test('whole-paragraph evidence split across paragraphs explicitly selects only its first fragment',()=>{
 const r=navigate(['甲方支付100元。乙方交货。'],['甲方支付100元。','乙方交货。'],'甲方支付100元。乙方交货。')
 assert.equal(r.quote,'甲方支付100元。');assert.match(r.navigationNotice,/起始片段/)
})
test('ambiguous quote occurrence falls back to its confirmed paragraph without pretending exactness',()=>{
 const r=navigate(['甲方约定按期支付100元并结清费用。'],['甲方约定按期支付100元100元并结清费用。'],'100元')
 assert.equal(r.quote,'甲方约定按期支付100元100元并结清费用。')
 assert.equal(r.navigationNotice,undefined)
})
