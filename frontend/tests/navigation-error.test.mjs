import {test} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
async function load(path){const r=await build({entryPoints:[path],bundle:true,platform:'node',format:'esm',write:false});return import('data:text/javascript;base64,'+Buffer.from(r.outputFiles[0].text).toString('base64'))}
const {requireNavigationReceipt,NavigationError}=await load('src/editors/navigation-error.ts')
const {createReferenceNavigator}=await load('src/review-reference.ts')
test('specific bridge failures survive reference navigation and keep the return anchor',async()=>{
 const cases=[['mapping_mismatch',undefined,/第 3 段/],['ambiguous','paragraph_mapping',/重复/],['not_found','paragraph_missing',/未能与编辑器内容匹配/],['not_found','range_text_mismatch',/确认引用的文字范围/],['not_found','selected_text_mismatch',/未能保留这处引用的选区/],['stale',undefined,/保存/],['unsupported',undefined,/定位能力/],['interrupted',undefined,/中断/],['mapping_missing',undefined,/映射已失效/]]
 for(const [status,reason,pattern] of cases){
  const receipt={status,reason,sourceIndex:2},phase=status==='mapping_mismatch'?'bind':'locate'
  assert.throws(()=>requireNavigationReceipt(receipt,phase),e=>e instanceof NavigationError&&e.receipt===receipt&&e.phase===phase)
  let state;const c=createReferenceNavigator({locate:async()=>{requireNavigationReceipt(receipt,phase);return true},pause(){},cancel(){},changed:s=>state=s})
  const point=id=>({title:id,anchor:{block_id:id,start:0,end:2,quote:'原文'}})
  assert.equal(await c.open(point('a'),point('b')),false)
  assert.equal(state.phase,'error');assert.match(state.message,pattern);assert.doesNotMatch(state.message,/原阅读位置仍保留/);assert.equal(state.origin.title,'a')
 }
})
test('missing receipts cannot claim success and successful receipts remain accepted',()=>{
 assert.throws(()=>requireNavigationReceipt(undefined,'locate'),/未确认/)
 requireNavigationReceipt({status:'located'},'locate');requireNavigationReceipt({status:'bound'},'bind')
})
test('transport errors remain actionable instead of becoming a generic failed visit',async()=>{
 let state;const c=createReferenceNavigator({locate:async()=>{throw Error('编辑器响应超时，请重试')},pause(){},cancel(){},changed:s=>state=s})
 const p={title:'原文',anchor:{block_id:'a',start:0,end:2,quote:'原文'}}
 await c.open(p,p);assert.equal(state.message,'编辑器响应超时，请重试')
})
