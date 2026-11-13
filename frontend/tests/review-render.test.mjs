import {test,before,after} from 'node:test'
import assert from 'node:assert/strict'
import {build} from 'esbuild'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {createRequire} from 'node:module'
let dir,render
before(async()=>{
 dir=await mkdtemp(join(tmpdir(),'rixin-render-'))
 await build({stdin:{contents:`import {createElement} from 'react';import {renderToStaticMarkup} from 'react-dom/server';import {ReviewProgress} from './src/review-progress';import {RevisionProposalCard} from './src/revision-proposal-card';import {ReviewResultsList} from './src/review-results-list';import {ReviewFindingCard} from './src/review-finding-card';export const proposal=props=>renderToStaticMarkup(createElement(RevisionProposalCard,props));export const results=props=>renderToStaticMarkup(createElement(ReviewResultsList,props));export const progress=run=>renderToStaticMarkup(createElement(ReviewProgress,{run}));export const card=props=>renderToStaticMarkup(createElement(ReviewFindingCard,props));`,resolveDir:process.cwd()},bundle:true,platform:'node',format:'cjs',jsx:'automatic',outfile:join(dir,'render.cjs')})
 render=createRequire(import.meta.url)(join(dir,'render.cjs'))
})
after(async()=>{await rm(dir,{recursive:true,force:true})})
test('unknown review state cannot be reported as AI completion',()=>{
 const html=render.progress({id:'r',status:'unexpected'})
 assert.doesNotMatch(html,/AI 审查完成|AI 分析已完成|本轮审查结果已生成/)
})
test('failed and running states remain explicit while completed state is compact',()=>{
 assert.match(render.progress({id:'r',status:'failed',error:{message:'连接失败'}}),/连接失败/)
 assert.match(render.progress({id:'r',status:'running',stage:'extracting'}),/AI 正在审查/)
 const done=render.progress({id:'r',status:'needs_input',stage:'done'})
 assert.match(done,/AI 分析已完成/);assert.doesNotMatch(done,/等待执行|本轮无待处理事项/)
})
test('evidence-free locked cards retain the finding but cannot claim or locate evidence',()=>{
 const html=render.card({finding:{id:'f',rule_id:'RL-03',status:'insufficient_evidence',explanation:'条款无法确认',evidence:[]},run:{id:'r',findings:[]},cid:'c',version:null,collapsed:false,locked:true,ready:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/没有可定位的原文证据/);assert.doesNotMatch(html,/定位原文/)
 assert.match(html,/<button[^>]* disabled=""[^>]*>记录处理/)
})
test('closed rows preview the opinion without exposing processing buttons or invented risk levels',()=>{
 const html=render.card({finding:{id:'f',rule_id:'RL-03',status:'insufficient_evidence',explanation:'不应在收起行显示的长解释',evidence:[]},run:{id:'r',findings:[]},cid:'c',version:null,locked:false,ready:true,onLocate(){},onDecision(){},onSupplement(){},collapsed:true})
 assert.match(html,/不应在收起行显示的长解释/)
 assert.doesNotMatch(html,/记录处理/);assert.doesNotMatch(html,/高风险|中风险|低风险/)
})
test('terminal run with module failure is visibly incomplete',()=>{
 const html=render.progress({id:'r',status:'needs_input',stage:'done',module_errors:[{module:'liability',code:'invalid',message:'责任核验失败'}]})
 assert.match(html,/本轮审查未完成|责任核验失败/)
 assert.doesNotMatch(html,/AI 分析已完成/)
})
test('case advisory card labels policy review separately from missing evidence',()=>{
 const html=render.card({finding:{id:'f',rule_id:'CR-02',execution_mode:'case_advisory',status:'insufficient_evidence',explanation:'责任需核对',evidence:[]},run:{id:'r',findings:[]},cid:'c',version:null,collapsed:false,locked:true,ready:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/需法务复核/)
 assert.doesNotMatch(html,/证据不足/)
})

test('v3 delete proposals remain visible with empty after_text and cannot write into editor',()=>{
 const run={id:'r',document_version_id:'v',result_schema_version:'interactive-review-v3',findings:[],issues:[]}
 const proposal={proposal_id:'p',event_ids:['e'],document_version_id:'v',operation:'delete',before_text:'并赔偿全部损失',after_text:'',rationale:'责任重复',basis_refs:[],state:'draft'}
 const html=render.proposal({proposal,run,version:{id:'v',blocks:[]},locked:false})
 assert.match(html,/删除上述文字/);assert.match(html,/并赔偿全部损失/);assert.match(html,/手工修订/);assert.doesNotMatch(html,/写入修订/)
 const stale=render.proposal({proposal,run,version:{id:'new',blocks:[]},locked:false})
 assert.match(stale,/建议已过期/);assert.match(stale,/<button[^>]* disabled=""[^>]*>复制建议/)
 const card=render.card({finding:{id:'f',rule_id:'CR-02',status:'flag',explanation:'风险',evidence:[],suggested_text:'旧文本'},run,cid:'c',version:null,collapsed:false,locked:false,ready:true,canApply:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.doesNotMatch(card,/写入修订/);assert.match(card,/法务反馈与历史/)
})
test('v3 results retain independent events and context issues in one numbered queue',()=>{
 const issues=['delay','termination'].map((id)=>({id,rule_id:'CR-02',event_id:id,clause_number:'7.4',status:'flag',explanation:'风险',evidence:[]}))
 issues.push({id:'number',rule_id:'RL-05',display_group:'context',status:'insufficient_evidence',explanation:'编号待确认',evidence:[]})
 const run={id:'r',document_version_id:'v',result_schema_version:'interactive-review-v3',issues,findings:[],rule_results:[],revision_proposals:[]}
 const html=render.results({run,version:null,cid:'c',locked:false,ready:false,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/第 7.4 条/);assert.equal((html.match(/<article class="review-finding/g)??[]).length,3)
 assert.match(html,/编号待确认/);assert.match(html,/问题事件 2/);assert.match(html,/修改建议 0/)
 assert.match(html,/aria-label="意见处理状态"/)
})
test('event anchor remains locatable without replacing the whole paragraph evidence',()=>{
 const html=render.card({finding:{id:'f',rule_id:'CR-02',status:'flag',explanation:'风险',evidence:[],event_anchor:{block_id:'b',start:0,end:2,quote:'延误'}},run:{id:'r',result_schema_version:'interactive-review-v3',findings:[],issues:[]},cid:'c',version:{id:'v',blocks:[{id:'b',text:'延误服务'}]},collapsed:false,locked:false,ready:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/定位原文/)
})
test('only current draft proposals can be copied as a definite suggestion',()=>{
 const run={id:'r',document_version_id:'v',findings:[]},version={id:'v',blocks:[]}
 const proposal={proposal_id:'p',event_ids:[],document_version_id:'v',operation:'replace',before_text:'原文',after_text:'待确认文本',rationale:'需核对',basis_refs:[]}
 for(const state of ['invalid','context_required','conflict']){
  const html=render.proposal({proposal:{...proposal,state},run,version,locked:false})
  assert.match(html,/<button[^>]* disabled=""[^>]*>复制建议/)
  assert.match(html,/当前建议仅供核对/)
 }
 const html=render.proposal({proposal:{...proposal,state:'draft'},run,version,locked:false})
 assert.doesNotMatch(html,/<button[^>]* disabled=""[^>]*>复制建议/)
})
test('v3 displays business scope warning once without inflating event counts',()=>{
 const run={id:'r',document_version_id:'v',result_schema_version:'interactive-review-v3',issues:[],findings:[],diagnostics:{context_warnings:['合同类型标签与正文业务范围不一致，请核对。']}}
 const html=render.results({run,version:null,cid:'c',locked:false,ready:false,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/审查范围与待核对事项/);assert.equal(html.split('合同类型标签与正文业务范围不一致，请核对。').length-1,1)
 assert.match(html,/问题事件 0/)
})

test('expanded v3 opinions show only proposals for their own event and preserve invalid-state protection',()=>{
 const proposal={proposal_id:'p',event_ids:['event-a'],document_version_id:'v',operation:'replace',before_text:'旧内容',after_text:'本事件修订',rationale:'本事件依据',basis_refs:[],state:'invalid'}
 const run={id:'r',document_version_id:'v',result_schema_version:'interactive-review-v3',issues:[],findings:[],revision_proposals:[proposal,{...proposal,proposal_id:'other',event_ids:['event-b'],after_text:'其他事件修订'}]}
 const html=render.card({finding:{id:'f',event_id:'event-a',rule_id:'CR-02',status:'flag',explanation:'风险',evidence:[]},run,cid:'c',version:{id:'v',blocks:[]},collapsed:false,locked:false,ready:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/本事件修订/);assert.doesNotMatch(html,/其他事件修订/)
 assert.match(html,/<button[^>]* disabled=""[^>]*>复制建议/)
})
test('unlinked v3 proposals remain discoverable even when there are no actionable findings',()=>{
 const run={id:'r',document_version_id:'v',result_schema_version:'interactive-review-v3',issues:[],findings:[],revision_proposals:[{proposal_id:'p',event_ids:['missing-event'],document_version_id:'v',operation:'delete',before_text:'需要核对的旧内容',after_text:'',rationale:'依据',basis_refs:[],state:'draft'}]}
 const html=render.results({run,version:null,cid:'c',locked:true,ready:false,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/其他修改建议/);assert.match(html,/需要核对的旧内容/)
})

test('missing evidence asks for verification instead of pretending to provide an edit',()=>{
 const html=render.card({finding:{id:'f',rule_id:'RL-03',status:'insufficient_evidence',explanation:'我方合同角色不明确',evidence:[]},run:{id:'r',findings:[]},cid:'c',version:null,collapsed:false,locked:false,ready:false,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/待核对事项/);assert.doesNotMatch(html,/>修改方向</)
 assert.match(html,/确认我方主体及甲乙方角色/)
})
test('proposal differences highlight only changed text',()=>{
 const props={proposal:{proposal_id:'p',event_ids:[],document_version_id:'v',operation:'replace',before_text:'逾期10日付款。',after_text:'逾期30日付款。',rationale:'测试',basis_refs:[],state:'draft'},run:{id:'r',document_version_id:'v',findings:[]},version:{id:'v',blocks:[]},locked:false}
 const html=render.proposal(props)
 assert.match(html,/<del[^>]*>1<\/del>/);assert.match(html,/<ins[^>]*>3<\/ins>/)
 const unchanged=render.proposal({...props,proposal:{...props.proposal,after_text:'逾期10日付款。'}})
 assert.doesNotMatch(unchanged,/<(?:del|ins)[ >]/)
 const removal=render.proposal({...props,proposal:{...props.proposal,operation:'delete',after_text:''}})
 assert.match(removal,/<del[^>]*>逾期10日付款。<\/del>/)
})
test('insertions highlight new text while stale and invalid proposals stay reference-only',()=>{
 const props={proposal:{proposal_id:'p',event_ids:[],document_version_id:'v',operation:'insert',before_text:'定位段落',after_text:'新增🙂\n条款',rationale:'测试',basis_refs:[],state:'draft'},run:{id:'r',document_version_id:'v',findings:[]},version:{id:'v',blocks:[]},locked:false}
 assert.match(render.proposal(props),/<ins>新增🙂\n条款<\/ins>/)
 for(const changed of [{...props,run:{...props.run,stale:true}},{...props,proposal:{...props.proposal,state:'invalid'}}])assert.doesNotMatch(render.proposal(changed),/<(?:ins|del)[ >]/)
})
test('legacy suggestions only compare against verified current single-source evidence',()=>{
 const props={finding:{id:'f',rule_id:'RL-03',status:'flag',explanation:'核对',suggested_text:'修改后',evidence:[{block_id:'b',start:0,end:3,quote:'修改前'}]},run:{id:'r',document_version_id:'v',findings:[]},cid:'c',version:{id:'v',blocks:[{id:'b',text:'修改前'}]},collapsed:false,locked:false,ready:true,onLocate(){},onDecision(){},onSupplement(){}}
 assert.match(render.card(props),/<del>前<\/del>/)
 assert.doesNotMatch(render.card({...props,version:{id:'v',blocks:[{id:'b',text:'不同原文'}]}}),/<(?:del|ins)[ >]/)
 assert.doesNotMatch(render.card({...props,run:{...props.run,stale:true}}),/<(?:del|ins)[ >]/)
})
