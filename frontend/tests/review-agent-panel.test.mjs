import {test,before,after} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {createRequire} from 'node:module'
let dir,render,reviewProcess,showReviewResults
before(async()=>{
 dir=await mkdtemp(join(tmpdir(),'agent-panel-'))
 await build({stdin:{contents:`import {createElement} from 'react';import {renderToStaticMarkup} from 'react-dom/server';import {ReviewAgentPanel} from './src/review-agent-panel';export {reviewProcess,showReviewResults} from './src/review-process';export const render=(state,policyVersion)=>renderToStaticMarkup(createElement(ReviewAgentPanel,{state,policyVersion,onLocate(){},disabled:false}));`,resolveDir:process.cwd()},bundle:true,platform:'node',format:'cjs',jsx:'automatic',loader:{'.css':'empty'},outfile:join(dir,'panel.cjs')})
 ;({render,reviewProcess,showReviewResults}=createRequire(import.meta.url)(join(dir,'panel.cjs')))
})
after(async()=>{await rm(dir,{recursive:true,force:true})})
test('six completed phases show human review without legacy automatic findings',()=>{
 const keys=['parse','transaction','rules','discovery','synthesis','drafting']
 const html=render({schema_version:2,run_id:'r',document_version_id:'v',attempt_id:'a',seq:1,status:'needs_input',tasks:{},issues:{},
  phases:Object.fromEntries(keys.map(id=>[id,{id,title:id,state:'completed'}])),
  proposals:{p:{id:'p',review_findings:[{stage:'group',reason:'两项上限关系待人工判断'}]}}})
 assert.match(html,/本轮审查已完成，待人工复核/)
 assert.doesNotMatch(html,/自动核验发现|两项上限关系待人工判断/)
 assert.doesNotMatch(html,/部分审查未完成|修改稿未全部完成/)
 assert.match(html,/查看审查过程/);assert.doesNotMatch(html,/agent-process-groups/)
})
const base={run_id:'r',attempt_id:'a',status:'running',tasks:{},phases:{parse:{id:'parse',title:'合同解析',state:'completed'}},artifacts:{}}
test('queued review cannot claim completion when no stage has started',()=>{
 const html=render(base);assert.match(html,/正在准备核查任务/);assert.doesNotMatch(html,/本轮审查已完成/)
})
test('snapshot phase order is independent of JSON key ordering; partial stays visible',()=>{
 const html=render({...base,status:'running',phases:{synthesis:{id:'synthesis',title:'整体复核',state:'failed'},transaction:{id:'transaction',title:'交易理解',state:'completed'},parse:base.phases.parse}})
 assert.ok(html.indexOf('合同解析')<html.indexOf('交易理解'));assert.ok(html.indexOf('交易理解')<html.indexOf('整体复核'));assert.match(html,/未完成/)
})
test('completed analysis persists, long reference lists collapse, HTML remains escaped',()=>{
 const html=render({...base,status:'running',artifacts:{a:{id:'transaction-1',title:'合同交易分析',revision:1,state:'completed',fields:{},sections:[{title:'交易概况',text:'<script>untrusted</script>',evidence:Array.from({length:9},(_,i)=>({block_id:'b'+i,start:0,end:2,quote:'合同'}))}]}}})
 assert.match(html,/交易概况/);assert.match(html,/全部 9 处依据/);assert.doesNotMatch(html,/原文依据 4/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/)
})


test('dynamic task totals are not displayed as a fixed progress fraction',()=>{
 const html=render({...base,tasks:{a:{id:'a',state:'completed'},b:{id:'b',state:'running'}},issues:{f:{id:'f'}}})
 assert.match(html,/已完成 1 项/);assert.match(html,/进行中 1 项/);assert.match(html,/合同风险识别/);assert.doesNotMatch(html,/1 \/ 2/)
})

test('revision-only failure preserves completed risk review and orders verification last',()=>{
 const html=render({...base,status:'running',phases:{verification:{id:'verification',title:'修改稿一致性核验',state:'failed'},drafting:{id:'drafting',title:'生成修改',state:'completed'},synthesis:{id:'synthesis',title:'风险自动复核',state:'completed'}}})
 assert.match(html,/未完成/)
 assert.ok(html.indexOf('风险自动复核')<html.indexOf('生成修改'))
 assert.ok(html.indexOf('生成修改')<html.indexOf('修改稿一致性核验'))
})

test('streamed checks occupy their own rows and cannot expose provisional references',()=>{
 const state={...base,phases:{discovery:{id:'discovery',title:'全文风险发现',state:'running'}},artifacts:{a:{id:'discovery-1',state:'generating',fields:{'check:1:title':'程序条款','check:1:text':'已识别保密条款','section:0:title':'付款风险','section:0:text':'需核对'},sections:[]}}}
 const process=reviewProcess(state)
 assert.equal(process.risk[1].state,'running');assert.equal(process.risk[1].sections[0].text,'已识别保密条款')
 assert.equal(process.risk[3].sections[0].title,'付款风险')
 assert.match(render(state),/已识别保密条款/);assert.doesNotMatch(render(state),/原文依据/)
 assert.equal(showReviewResults(true,state),false);assert.equal(showReviewResults(false,state),true)
 assert.equal(showReviewResults(true,{...state,phases:{}}),true)
})
test('configured progress shows the pending task and releases only verified actionable opinions',()=>{
 const policy='review-configured-rules-v1'
 const state={...base,status:'running',phases:{rules:{id:'rules',title:'配置规则核查',state:'running'}},
  tasks:{'base:facts':{id:'base:facts',state:'completed',sections:[{title:'附件引用',text:'正文引用《报价单》。',evidence:[]}]},limit:{id:'limit',state:'running',title:'核查累计违约责任'}},
  issues:{ok:{id:'ok',rule_id:'RL-01',status:'no_flag_for_target_rule',review_state:'reviewed',explanation:'核对了付款起算条件。',evidence:[]},
   pending:{id:'pending',rule_id:'RL-03',status:'flag',review_state:'preliminary',explanation:'未经校验的结论'},
   failed:{id:'failed',rule_id:'RL-02',status:'insufficient_evidence',review_state:'reviewed',execution_state:'failed',explanation:'金额核查超时'}}}
 assert.match(render(state,policy),/正在核查累计违约责任 · 已有 1 项规则返回结论/)
 assert.match(render(state,policy),/正文引用《报价单》/)
 assert.match(render(state,policy),/本项未发现问题.*核对了付款起算条件/)
 assert.match(render(state,policy),/金额核查超时/)
 assert.doesNotMatch(render(state,policy),/未经校验的结论/)
 assert.doesNotMatch(render(state,policy),/查看详细执行记录/)
 assert.equal(showReviewResults(true,state,policy),false)
 const draft={id:'clause-14',title:'1.4 解约退款与违约金',rule_id:'VL-01',status:'flag',review_state:'reviewed',execution_state:'completed',
  explanation:'核对本条退款范围。',event_anchor:{block_id:'p14',start:0,end:3,quote:'1.4'},revision_plan:{state:'generating',message:'正在拟定本条改文。'}}
 const drafting={...state,phases:{...state.phases,drafting:{id:'drafting',state:'running'}},issues:{...state.issues,verified:draft}}
 assert.equal(showReviewResults(true,drafting,policy),true)
 assert.match(render(drafting,policy),/正在生成候选改文/)
 assert.match(render(drafting,policy),/1\.4 解约退款与违约金.*title="1\.4".*正在拟定本条改文/)
 const complete=render({...drafting,status:'needs_input'},policy)
 assert.match(complete,/查看审查过程/)
 assert.doesNotMatch(complete,/agent-current|正在生成候选改文/)
})
test('all batches must finish; missing checks stay unrecorded and insufficient evidence stays explicit',()=>{
 const state={...base,phases:{discovery:{id:'discovery',title:'全文风险发现',state:'running'}},artifacts:{a:{id:'discovery-1',state:'completed',fields:{},sections:[{title:'合法性',check_id:'合法性',check_status:'insufficient_evidence',text:'引用效力待核实',evidence:[]}]}}}
 assert.equal(reviewProcess(state).risk[2].state,'running')
 state.phases.discovery.state='completed'
 assert.equal(reviewProcess(state).risk[2].state,'attention')
 assert.equal(reviewProcess(state).risk[0].state,'unavailable')
 state.artifacts.b={id:'discovery-2',state:'failed',fields:{},sections:[],message:'核查超时'}
 assert.equal(reviewProcess(state).risk[2].state,'failed');assert.equal(reviewProcess(state).risk[2].sections.length,1)
})
test('terminal failures keep history without redundant status banners',()=>{
 assert.doesNotMatch(render({...base,status:'failed'}),/部分审查未完成|agent-current/)
 assert.match(render({...base,status:'failed'}),/查看审查过程/)
 assert.match(render({...base,status:'needs_input',phases:{synthesis:{id:'synthesis',title:'风险自动复核',state:'completed'},drafting:{id:'drafting',title:'修改稿生成',state:'failed'}}}),/查看审查过程/)
})

test('stream completion preserves content anchors for readers who scrolled up',()=>{
 const state={...base,phases:{discovery:{id:'discovery',state:'running'}},artifacts:{a:{id:'discovery-1',state:'generating',fields:{'check:1:title':'程序条款','check:1:text':'已识别','section:0:title':'风险','section:0:text':'需核对'},sections:[]}}}
 const before=reviewProcess(state)
 state.artifacts.a={...state.artifacts.a,state:'completed',fields:{},sections:[{title:'程序条款',check_id:'程序条款',text:'已识别',evidence:[]},{title:'风险',text:'需核对',evidence:[]}]}
 const after=reviewProcess(state)
 assert.equal(before.risk[1].sections[0].key,after.risk[1].sections[0].key)
 assert.equal(before.risk[3].sections[0].key,after.risk[3].sections[0].key)
})

test('specialist rows identify the failed domain and preserve completed peers',()=>{
 const artifacts=Object.fromEntries(['performance','remedies','consistency'].map(role=>[role,{
  id:'discovery-1-'+role,state:role==='remedies'?'failed':'completed',fields:{},
  sections:[{title:'检查结果',text:'已核对',evidence:[]}],message:role==='remedies'?'超时':undefined,
 }]))
 const state={...base,status:'needs_input',phases:{discovery:{id:'discovery',state:'failed'}},artifacts}
 assert.deepEqual(reviewProcess(state).risk.map(r=>[r.title,r.state]),[
  ['履约与结算','completed'],['责任与退出','failed'],['程序与一致性','completed'],
 ])
})

test('power data runs expose separate delivery and receivables rows',()=>{
 const make = (topic, text) => ({id:'discovery-1-'+topic+'-performance',state:'completed',fields:{},sections:[{title:'检查结果',text,evidence:[]}]})
 const state={...base,artifacts:{delivery:make('topic1','数据授权'),payment:make('topic2','验收依据')}}
 const rows=reviewProcess(state,'review-agent-v4-power-data').risk
 assert.deepEqual(rows.map(row=>row.title),['交付与数据授权','验收与回款','责任与退出结算','重大例外全文检查'])
 assert.deepEqual(rows.slice(0,2).map(row=>row.sections.map(section=>section.text)),[['数据授权'],['验收依据']])
})

test('configured transaction text streams without links until completion and rule groups expose real progress',()=>{
 const policy='review-configured-rules-v1'
 const id='transaction-overview', evidence={block_id:'v:p1',start:0,end:2,quote:'供货'}
 const a={id,title:'核心交易内容分析',state:'generating',fields:{'section:0:title':'交易概况','section:0:text':'乙方负责供货'},sections:[]}
 const step={id:'base:liability-limit:group-1',title:'责任条款核查 1/2',state:'running',message:'正在校验原文',sections:[{title:'',text:'',evidence:[evidence]}]}
 const state={...base,artifacts:{[id]:a},issues:{},tasks:{[step.id]:step}}
 const run={rule_snapshot:{rules:[{id:'VL-01',title:'累计责任'}]}}
 const before=reviewProcess(state,policy,run)
 assert.equal(before.transaction[0].sections[0].text,'乙方负责供货')
 assert.deepEqual(before.transaction[0].sections[0].evidence,[])
 assert.deepEqual(before.risk[0].clauses.map(c=>c.anchor),[evidence])
 const perspective={...step,id:step.id+'-perspective',state:'completed',first_seq:10}
 const checked=reviewProcess({...state,tasks:{...state.tasks,[perspective.id]:perspective},phases:{rules:{id:'rules',state:'running'}}},policy,run)
 assert.equal(checked.risk[0].clauses.length,1)
 assert.equal(checked.risk[0].clauses[0].message,'已完成本步，等待整体核对')
 state.artifacts[id]={...a,state:'completed',fields:{},sections:[{title:'交易概况',text:'乙方负责供货',evidence:[evidence]}]}
 const after=reviewProcess(state,policy,run)
 assert.equal(after.transaction[0].sections[0].key,before.transaction[0].sections[0].key)
 assert.deepEqual(after.transaction[0].sections[0].evidence,[evidence])
})

test('shared extraction steps stay scoped to their rules in live and restored runs',()=>{
 const policy='review-configured-rules-v1'
 const rules=['RL-01','RL-02','RL-03','RL-04','RL-05'].map(id=>({id,title:id}))
 const state={...base,issues:{},tasks:{
  'base:basic':{id:'base:basic',state:'completed'},
  'base:assignment':{id:'base:assignment',state:'running',rule_scope:{'RL-03':'筛出 2 个候选段落'}},
  'base:facts':{id:'base:facts',state:'completed',sections:[{title:'关键字段',text:'签署日期 · 空白',evidence:[]}]},
 }}
 const run={rule_snapshot:{rules}}
 const rows=reviewProcess(state,policy,run).risk
 assert.deepEqual(rows.map(row=>row.steps.length),[1,1,1,2,1])
 assert.equal(rows[2].steps[0].message,'筛出 2 个候选段落')
 assert.match(rows[4].steps[0].message,/1 项填写情况/)
 assert.doesNotMatch(rows[1].steps[0].message,/填写情况/)
 assert.equal(new Set(rows.flatMap(row=>row.steps.map(t=>t.id))).size,6)
 assert.equal(rows[4].formEntries[0].text,'签署日期 · 空白')
 assert.equal(reviewProcess(state,policy,run).transaction.length,0)
 const id='transaction-overview'
 const source={block_id:'v:p1',start:0,end:9,quote:'签订后十日开通服务'}
 state.artifacts={[id]:{id,title:'核心交易内容分析',state:'completed',fields:{},sections:[{title:'履约安排',text:source.quote,evidence:[source]}]}}
 const facts=reviewProcess(state,policy,run).transaction
 assert.equal(facts.length,1)
 assert.equal(facts[0].title,'提取合同事实')
 assert.deepEqual(facts[0].sections[0].evidence,[source])
 assert.doesNotMatch(JSON.stringify(facts),/签署日期/)
})

test('a completed amount check with no arithmetic keeps its scope visible and its trace folded',()=>{
 const policy='review-configured-rules-v1'
 const finding={id:'amount',rule_id:'RL-02',status:'no_flag_for_target_rule',execution_state:'completed',
  review_state:'reviewed',computed_calculations:[],explanation:'本项未发现问题',evidence:[]}
 const state={...base,issues:{amount:finding},tasks:{'base:facts':{id:'base:facts',state:'completed',
  rule_scope:{'RL-02':'正在索引候选段落'},rule_observations:{'RL-02':'提取到 0 项可复算关系'}}}}
 const html=render(state,policy)
 assert.match(html,/aria-expanded="false"[^>]*title="展开核查过程"/)
 assert.match(html,/未作金额复算/)
 assert.doesNotMatch(html,/本项未发现问题|正在索引候选段落|提取到 0 项可复算关系/)
 const steps=reviewProcess(state,policy).risk[0].steps
 assert.equal(steps[0].message,'提取到 0 项可复算关系')
 const failure={...finding,status:'insufficient_evidence',execution_state:'failed',explanation:'计算关系未通过原文核验'}
 assert.doesNotMatch(render({...state,issues:{amount:failure}},policy),/未作金额复算/)
 assert.match(render({...state,issues:{amount:failure}},policy),/计算关系未通过原文核验/)
})
