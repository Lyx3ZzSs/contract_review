import {test,before,after} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {createRequire} from 'node:module'
let dir,render
before(async()=>{
 dir=await mkdtemp(join(tmpdir(),'rixin-subject-render-'))
 await build({stdin:{contents:`import {createElement} from 'react';import {renderToStaticMarkup} from 'react-dom/server';import {SubjectRiskCard,SubjectRiskTile,subjectRiskCounts} from './src/subject-risk-card';import {SubjectCompanyDetails} from './src/subject-company-details';export {subjectRiskCounts};export const company=props=>renderToStaticMarkup(createElement(SubjectCompanyDetails,props));export const tile=props=>renderToStaticMarkup(createElement(SubjectRiskTile,props));export const card=props=>renderToStaticMarkup(createElement(SubjectRiskCard,props));`,resolveDir:process.cwd()},bundle:true,platform:'node',format:'cjs',jsx:'automatic',outfile:join(dir,'render.cjs')})
 render=createRequire(import.meta.url)(join(dir,'render.cjs'))
})
after(async()=>{await rm(dir,{recursive:true,force:true})})
const card=result=>render.card({module:'execution',result,busy:false,matched:true,onQuery(){},onDetail(){}})
test('permission, transport and unqueried states never render zero risk',()=>{
 for(const state of ['unavailable','failed','not_queried']){
  const html=card({label:'被执行人',state,message:'查询未成功',data:null})
  assert.doesNotMatch(html,/0 条记录|未发现相关记录/)
  assert.match(html,/查询未成功/)
 }
 assert.match(card({label:'被执行人',state:'empty',data:{total:0},message:''}),/未发现相关记录/)
})
test('failed next page keeps evidence with original timestamp and pagination',()=>{
 const html=card({label:'被执行人',state:'failed',message:'网络失败',queried_at:'2026-11-18T08:00:00Z',last_attempt_at:'2026-11-18T08:01:00Z',data:{total:21},pages:{'1':{records:[{title:'测试案号',fields:[{label:'执行标的（元）',value:'200000'}]}]}}})
 assert.match(html,/本次查询未成功/);assert.match(html,/测试案号/);assert.match(html,/已加载 1 \/ 21 条/);assert.match(html,/加载更多记录/)
})
test('bankruptcy cases expose historical status and on-demand details',()=>{
 const html=render.card({module:'bankruptcy',result:{label:'破产重整',state:'ready',data:{total:1},pages:{'1':{records:[{title:'破产案号',detail_id:'uuid',fields:[{label:'案件状态',value:'历史案件'}]}]}}},busy:false,matched:true,onQuery(){},onDetail(){}})
 assert.match(html,/历史案件/);assert.match(html,/查询案件详情/);assert.doesNotMatch(html,/加载更多记录/)
})
test('unconfirmed identity disables risk queries',()=>{
 const html=render.card({module:'tax',result:{label:'税务非正常户',state:'not_queried',message:'尚未查询',data:null},busy:false,matched:false,onQuery(){},onDetail(){}})
 assert.match(html,/<button[^>]*disabled=""[^>]*>[\s\S]*?查询此项<\/button>/)
})

test('risk overview keeps unavailable categories separate from clear categories',()=>{
 const results=[{state:'ready',data:{total:2}},{state:'empty',data:{total:0}},{state:'failed',data:{total:20}},{state:'unavailable'},{state:'unavailable',provider_code:300005},{state:'not_queried'},{state:'empty',data:{total:0}}]
 assert.deepEqual(render.subjectRiskCounts(results),{found:1,clear:2,unknown:3})
 const html=render.tile({result:{label:'税务非正常户',state:'unavailable',provider_code:300005},selected:true,onClick(){}})
 assert.equal(html,'')
 assert.equal(card({label:'税务非正常户',state:'unavailable',provider_code:300005,message:'未开通查询权限',data:null}),'')
 const company=render.company({modules:{ownership:{state:'unavailable',provider_code:300005},scale:{state:'ready',data:'微型'}},busy:false,matched:true,onQuery(){}})
 assert.doesNotMatch(company,/企业属性|权限|开通/);assert.match(company,/企业规模|微型/)
 assert.equal(render.company({modules:Object.fromEntries(['ownership','scale','shareholders'].map(key=>[key,{state:'unavailable',provider_code:300005}])),busy:false,matched:true,onQuery(){}}),'')
})
