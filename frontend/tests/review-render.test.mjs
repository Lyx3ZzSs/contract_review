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
 await build({stdin:{contents:`import {createElement} from 'react';import {renderToStaticMarkup} from 'react-dom/server';import {ReviewProgress} from './src/review-progress';import {RevisionProposalCard} from './src/revision-proposal-card';import {ReviewResultsList} from './src/review-results-list';import {ReviewFindingCard} from './src/review-finding-card';import {ReviewReadingIssues} from './src/review-reading-issues';export const reading=props=>renderToStaticMarkup(createElement(ReviewReadingIssues,props));export const proposal=props=>renderToStaticMarkup(createElement(RevisionProposalCard,props));export const results=props=>renderToStaticMarkup(createElement(ReviewResultsList,props));export const progress=run=>renderToStaticMarkup(createElement(ReviewProgress,{run}));export const card=props=>renderToStaticMarkup(createElement(ReviewFindingCard,props));`,resolveDir:process.cwd()},bundle:true,platform:'node',format:'cjs',jsx:'automatic',outfile:join(dir,'render.cjs')})
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
 assert.match(html,/<details class="review-card-menu">/);assert.doesNotMatch(html,/高风险|中风险|低风险/)
})
test('terminal run with module failure is visibly incomplete',()=>{
 const html=render.progress({id:'r',status:'needs_input',stage:'done',module_errors:[{module:'liability',code:'invalid',message:'责任核验失败'}]})
 assert.match(html,/本轮审查未完成|责任核验失败/)
 assert.doesNotMatch(html,/AI 分析已完成/)
})
test('configured drafting failure preserves the completed rule-check status',()=>{
 const html=render.progress({id:'r',status:'needs_input',stage:'partial',rule_results:[{execution_state:'completed'}],module_errors:[{module:'configured-drafting',code:'draft_missing',message:'7 项意见尚缺少可用改文'}]})
 assert.match(html,/规则核查已完成，部分改文待处理/)
 assert.match(html,/7 项意见尚缺少可用改文/)
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
 assert.match(html,/删除上述文字/);assert.match(html,/并赔偿全部损失/);assert.match(html,/未应用/);assert.doesNotMatch(html,/写入修订/)
 const stale=render.proposal({proposal,run,version:{id:'new',blocks:[]},locked:false})
 assert.match(stale,/建议已过期/);assert.match(stale,/<button[^>]* disabled=""[^>]*>(?:<svg[\s\S]*?<\/svg>)?复制建议/)
 const card=render.card({finding:{id:'f',rule_id:'CR-02',status:'flag',explanation:'风险',evidence:[],suggested_text:'旧文本'},run,cid:'c',version:null,collapsed:false,locked:false,ready:true,canApply:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.doesNotMatch(card,/写入修订/);assert.match(card,/法务反馈与历史/)
})
test('regular and streaming results omit inconclusive checks while keeping flagged events',()=>{
 const issues=['delay','termination'].map((id)=>({id,rule_id:'CR-02',event_id:id,clause_number:'7.4',status:'flag',explanation:'风险',evidence:[]}))
 for(const [rule_id,title] of [['RL-01','期限一致性'],['VL-01','我方累计违约责任是否超过内部限额']])
  issues.push({id:rule_id,rule_id,title,display_group:'context',status:'insufficient_evidence',explanation:'待核对',evidence:[]})
 const run={id:'r',document_version_id:'v',result_schema_version:'interactive-review-v3',issues,findings:[],rule_results:[],revision_proposals:[]}
 const html=render.results({run,version:null,cid:'c',locked:false,ready:false,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/第 7.4 条/);assert.equal((html.match(/<article class="review-finding/g)??[]).length,2)
 assert.doesNotMatch(html,/期限一致性|我方累计违约责任是否超过内部限额/);assert.match(html,/问题事件 2/);assert.match(html,/修改建议 0/)
 assert.match(html,/aria-label="意见处理状态"/)
 const streaming=render.results({run:{...run,status:'running',decisions:[{finding_id:'termination',action:'acknowledged',note:'已记录'}]},active:true,compactStream:true,version:null,cid:'c',locked:true,ready:false,onLocate(){},onDecision(){},onSupplement(){}})
 assert.doesNotMatch(streaming,/result-stream-toolbar|result-status-bar|aria-label="风险类型"|aria-label="意见处理状态"/)
 assert.match(streaming,/aria-label="审查意见"/)
 assert.equal((streaming.match(/<article class="review-finding/g)??[]).length,2)
 assert.doesNotMatch(streaming,/期限一致性|我方累计违约责任是否超过内部限额/)
 assert.match(streaming,/已核对/)
 assert.equal((streaming.match(/class="result-row"[^>]*aria-expanded="true"/g)??[]).length,1)
})
test('event anchor remains locatable without replacing the whole paragraph evidence',()=>{
 const html=render.card({finding:{id:'f',rule_id:'CR-02',status:'flag',explanation:'风险',evidence:[],event_anchor:{block_id:'b',start:0,end:2,quote:'延误'}},run:{id:'r',result_schema_version:'interactive-review-v3',findings:[],issues:[]},cid:'c',version:{id:'v',blocks:[{id:'b',text:'延误服务'}]},collapsed:false,locked:false,ready:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/定位原文/)
})
test('business confirmation does not block copying review drafts',()=>{
 const run={id:'r',document_version_id:'v',findings:[]},version={id:'v',blocks:[]}
 const proposal={proposal_id:'p',event_ids:[],document_version_id:'v',operation:'replace',before_text:'原文',after_text:'待确认文本',rationale:'需核对',basis_refs:[]}
 for(const state of ['invalid','conflict']){
  const html=render.proposal({proposal:{...proposal,state},run,version,locked:false})
  assert.match(html,/<button[^>]* disabled=""[^>]*>(?:<svg[\s\S]*?<\/svg>)?复制建议/)
  assert.match(html,/仅供核对/)
 }
 const html=render.proposal({proposal:{...proposal,state:'draft'},run,version,locked:false})
 assert.doesNotMatch(html,/<button[^>]* disabled=""[^>]*>(?:<svg[\s\S]*?<\/svg>)?复制建议/)
 const pending=render.proposal({proposal:{...proposal,state:'context_required',message:'期限尚待协商'},run,version,locked:false})
 assert.doesNotMatch(pending,/期限尚待协商|接受后保留为审阅稿/)
 assert.doesNotMatch(pending,/<button[^>]* disabled=""[^>]*>(?:<svg[\s\S]*?<\/svg>)?复制建议/)
 assert.doesNotMatch(pending,/仅供核对/)
})
test('v3 hides retired business scope warnings in saved runs',()=>{
 const run={id:'r',document_version_id:'v',result_schema_version:'interactive-review-v3',issues:[],findings:[],diagnostics:{context_warnings:['合同类型标签与正文业务范围不一致，请核对。','本轮使用仅适用于此合同的已确认个案参数；不代表公司通用规则。']}}
 const html=render.results({run,version:null,cid:'c',locked:false,ready:false,onLocate(){},onDecision(){},onSupplement(){}})
 assert.doesNotMatch(html,/合同类型标签与正文业务范围不一致|待核对事项|已确认个案参数|不代表公司通用规则/)
 assert.match(html,/问题事件 0/)
})

test('expanded v3 opinions show only proposals for their own event and preserve invalid-state protection',()=>{
 const proposal={proposal_id:'p',event_ids:['event-a'],document_version_id:'v',operation:'replace',before_text:'旧内容',after_text:'本事件修订',rationale:'本事件依据',basis_refs:[],state:'invalid'}
 const run={id:'r',document_version_id:'v',result_schema_version:'interactive-review-v3',issues:[],findings:[],revision_proposals:[proposal,{...proposal,proposal_id:'other',event_ids:['event-b'],after_text:'其他事件修订'}]}
 const html=render.card({finding:{id:'f',event_id:'event-a',rule_id:'CR-02',status:'flag',explanation:'风险',evidence:[]},run,cid:'c',version:{id:'v',blocks:[]},collapsed:false,locked:false,ready:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/本事件修订/);assert.doesNotMatch(html,/其他事件修订/)
 assert.match(html,/<button[^>]* disabled=""[^>]*>(?:<svg[\s\S]*?<\/svg>)?复制建议/)
})
test('unlinked v3 proposals remain discoverable even when there are no actionable findings',()=>{
 const run={id:'r',document_version_id:'v',result_schema_version:'interactive-review-v3',issues:[],findings:[],revision_proposals:[{proposal_id:'p',event_ids:['missing-event'],document_version_id:'v',operation:'delete',before_text:'需要核对的旧内容',after_text:'',rationale:'依据',basis_refs:[],state:'draft'}]}
 const html=render.results({run,version:null,cid:'c',locked:true,ready:false,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/其他修改建议/);assert.match(html,/需要核对的旧内容/)
 assert.doesNotMatch(html,/按风险点|按条款顺序/)
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
 assert.doesNotMatch(html,/修改依据与反馈|正文操作记录/)
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

const readingProps=()=>({issues:[{id:'f',rule_id:'RL-03',title:'付款与验收条件冲突',status:'flag',explanation:'应核对验收条件',suggested_text:null,evidence:[{block_id:'a',start:0,end:2,quote:'付款'},{block_id:'b',start:0,end:2,quote:'验收'}]}],run:{id:'r',document_version_id:'v',findings:[],decisions:[]},version:{id:'v',blocks:[{id:'a',text:'付款'},{id:'b',text:'验收'}]},cid:'c',blockIds:['a'],disabled:false,locked:false,onEvidence(){},onDecision(){},onInteract(){}})
test('current clause cards show explanation, local and related evidence, guidance and decision actions',()=>{
 const html=render.reading(readingProps());for(const text of ['付款与验收条件冲突','应核对验收条件','查看本条原文','查看关联原文','下一步核对','记录处理','待业务确认'])assert.ok(html.includes(text),text)
})
test('processed current opinions stay visible with their recorded decision',()=>{
 const props=readingProps();props.run.decisions=[{finding_id:'f',action:'acknowledged',note:'已核验两处原文'}];const html=render.reading(props);assert.match(html,/已核对|已核验两处原文/);assert.match(html,/付款与验收条件冲突/);assert.doesNotMatch(html,/>记录处理<|>待业务确认</)
})
test('reference and processing controls respect stale or running locks',()=>{
 const html=render.reading({...readingProps(),disabled:true,locked:true});assert.match(html,/<button disabled="">查看关联原文/);assert.match(html,/<button disabled="">记录处理/)
})
test('evidence-free reading cards do not invent navigation or a clean review conclusion',()=>{
 const props=readingProps();props.issues[0].evidence=[];const html=render.reading(props);assert.match(html,/没有可定位的原文证据/);assert.doesNotMatch(html,/查看关联原文|查看本条原文/);const empty=render.reading({...props,issues:[]});assert.match(empty,/暂无已生成的待处理意见/);assert.doesNotMatch(empty,/无风险|审查通过/)
})
test('same-clause evidence chips expose separate ranges and only acknowledge the verified active range',()=>{
 const a={block_id:'b',start:0,end:4,quote:'7.4甲'},b={block_id:'b',start:4,end:6,quote:'乙方'}
 const html=render.card({finding:{id:'f',rule_id:'CR-02',status:'flag',explanation:'风险',evidence:[a,b]},run:{id:'r',findings:[]},cid:'c',version:{id:'v',blocks:[{id:'b',text:'7.4甲乙方'}]},activeEvidenceKey:'b:4:6',collapsed:false,locked:false,ready:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.equal((html.match(/class="result-evidence-chip"/g)??[]).length,2)
 assert.equal((html.match(/aria-pressed="true"/g)??[]).length,1)
 assert.match(html,/本项意见的原文引用|定位原文/)
 assert.doesNotMatch(html,/原文与依据|<summary>处理记录/)
})

test('streaming candidates escape content and expose no verified-result actions',()=>{
 const issue={id:'f',title:'责任核查',event_id:'e',rule_id:'CR-02',status:'flag',evidence:[],explanation:''}
 const run={id:'r',document_version_id:'v',result_schema_version:'interactive-review-v3',issues:[issue],findings:[],rule_results:[]}
 const props={run,version:null,cid:'c',locked:true,ready:true,active:true,onLocate(){},onDecision(){},onSupplement(){}}
 for(const state of ['generating','validating','failed']){
  const html=render.results({...props,drafts:{f:{issue,revision:2,state,first_seq:1,fields:{explanation:'<script>alert(1)</script>', 'edit:0:after_text':''}}}})
  assert.match(html,/&lt;script&gt;alert/)
  assert.doesNotMatch(html,/<script>|定位原文|复制意见|复制建议|记录处理/)
  assert.match(html,/建议删除原文片段/)
  if(state==='failed')assert.match(html,/未完成核验，不能用于修改正文/)
 }
})


test('running opinions show lifecycle and preserve explanation while drafting inside the same card',()=>{
 const finding={id:'f',rule_id:'CR-06',status:'insufficient_evidence',title:'付款核查',explanation:'初步意见原文',evidence:[],review_state:'drafting'}
 const props={finding,run:{id:'r',status:'running',findings:[finding]},cid:'c',version:null,collapsed:false,locked:true,ready:true,onLocate(){},onDecision(){},onSupplement(){}}
 const html=render.card({...props,draft:{issue:finding,revision:1,state:'generating',fields:{'edit:0:after_text':'新的修改片段'}}})
 assert.match(html,/正在生成修改/);assert.match(html,/初步意见原文/);assert.match(html,/新的修改片段/)
 assert.equal((html.match(/data-finding-id="f"/g)||[]).length,1)
 assert.doesNotMatch(html,/已完成整体复核/)
})
test('stale deletion proposal explains deletion instead of claiming missing output',()=>{
 const proposal={id:'p',event_ids:[],document_version_id:'v',operation:'delete',before_text:'原文',after_text:'',rationale:'理由',basis_refs:[],state:'draft'}
 const html=render.proposal({proposal,run:{id:'r',document_version_id:'new',findings:[]},version:{id:'new',blocks:[]},locked:true})
 assert.match(html,/建议已过期/);assert.match(html,/建议删除上述原文/);assert.doesNotMatch(html,/尚无确定文本/)
})

test('withdrawn opinions stay in audit history and their old proposals do not reappear as orphan edits',()=>{
 const issue={id:'f',rule_id:'CR-06',event_id:'e',title:'已撤回问题',status:'no_flag_for_target_rule',review_state:'retracted',explanation:'原意见',evidence:[],reconciliation_note:'关联条款已明确抵扣',reconciliation:{previous_explanation:'原意见'}}
 const run={id:'r',document_version_id:'v',status:'needs_input',result_schema_version:'interactive-review-v3',issues:[issue],findings:[issue],revision_proposals:[{id:'p',event_ids:['e'],state:'invalid',operation:'delete',before_text:'不得再次展示的旧修改',after_text:'',document_version_id:'v',rationale:'旧理由',basis_refs:[]}]}
 const html=render.results({run,version:{id:'v',blocks:[]},cid:'c',locked:false,ready:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/整体复核变更记录/);assert.match(html,/已撤回问题/);assert.match(html,/关联条款已明确抵扣/);assert.doesNotMatch(html,/不得再次展示的旧修改/)
})

test('grounded card paragraphs cite their own evidence and keep the modification plan separate',()=>{
 const e={block_id:'b',start:0,end:6,quote:'7.3原文。'}
 const finding={id:'f',rule_id:'CR-06',status:'flag',explanation:'风险说明',review_state:'reviewed',evidence:[e],reconciliation_note:'已复核保留',card_content:{version:'review-card-v1',risk_paragraphs:[{text:'合同缺少付款期限。',evidence:[e]}],modification_plan:'补充双方确认的付款期限。'}}
 const props={finding,run:{id:'r',status:'needs_input',findings:[]},cid:'c',version:{id:'v',blocks:[{id:'b',text:e.quote}]},collapsed:false,locked:false,ready:true,onLocate(){},onDecision(){},onSupplement(){}}
 const html=render.card(props)
 assert.match(html,/<p class="result-cited-paragraph"[^>]*>合同缺少付款期限。[\s\S]*?<button[^>]*aria-label="定位第 7.3 条"/)
 assert.match(html,/修改方案<\/h4><p[^>]*>补充双方确认的付款期限/)
 assert.doesNotMatch(html,/result-applicability/)
 const adjusted=render.card({...props,finding:{...finding,review_state:'adjusted',explanation:'复核后的风险'}})
 assert.match(adjusted,/复核后的风险/);assert.doesNotMatch(adjusted,/result-cited-paragraph|补充双方确认的付款期限/)
 const unknown=render.card({...props,finding:{...finding,card_content:{...finding.card_content,risk_paragraphs:[{text:'错误引用',evidence:[{...e,block_id:'missing'}]}]}}})
 assert.doesNotMatch(unknown,/错误引用|result-cited-paragraph/)
})

test('active v2 card replaces its risk text in place and never repeats it inside the draft',()=>{
 const finding={id:'f',rule_id:'CR-06',status:'flag',review_state:'drafting',explanation:'初步风险',evidence:[]}
 const draft={issue:finding,state:'generating',revision:1,fields:{'risk:0:text':'生成中的风险说明',modification_plan:'生成中的修改方案','edit:0:after_text':'候选修改'}}
 const html=render.card({finding,draft,run:{id:'r',status:'running',findings:[]},cid:'c',version:null,collapsed:false,locked:true,ready:false,onLocate(){},onDecision(){},onSupplement(){}})
 assert.equal((html.match(/生成中的风险说明/g)??[]).length,1)
 assert.equal((html.match(/生成中的修改方案/g)??[]).length,1)
 assert.match(html,/候选修改/);assert.doesNotMatch(html,/初步风险|复制建议/)
})

test('one coordinated revision is linked from both risks with one proposal identity',()=>{
 const issues=['a','b'].map(event_id=>({id:event_id,event_id,rule_id:'CR-06',status:'flag',title:`风险${event_id}`,explanation:'需要核对',evidence:[],review_state:'reviewed'}))
 const proposal={id:'shared',event_ids:['a','b'],document_version_id:'v',operation:'replace',anchor:{block_id:'p',start:0,end:2,quote:'原文'},before_text:'原文',after_text:'统一修改',rationale:'同时覆盖两项要求',basis_refs:[],state:'draft',coordination:{group_id:'g',event_ids:['a','b'],requirement_ids:['a:0','b:0'],summary:'统一处理解除和退款',structurally_valid:true}}
 const run={id:'r',document_version_id:'v',status:'needs_input',result_schema_version:'interactive-review-v3',issues,findings:issues,revision_proposals:[proposal]}
 for(const finding of issues){
  const html=render.card({finding,run,cid:'c',version:{id:'v',blocks:[{id:'p',text:'原文'}]},collapsed:false,locked:false,ready:true,onLocate(){},onDecision(){},onSupplement(){}})
  assert.match(html,/data-proposal-id="shared"/)
  assert.match(html,/关联 2 个风险 · 同步应用状态/)
  assert.match(html,/统一修改/)
 }
})

test('same clause displays two risks and one shared plan, including a handled risk',()=>{
 const evidence={block_id:'p',start:0,end:6,quote:'7.3原文。'}
 const issues=['a','b'].map(id=>({id,event_id:id,rule_id:'CR-06',status:'flag',title:`风险${id}`,explanation:`风险说明${id}`,evidence:[evidence],review_state:'reviewed',card_content:{version:'review-card-v1',risk_paragraphs:[{text:`风险说明${id}`,evidence:[evidence]}],modification_plan:'旧的单项修改方向'}}))
 const p={id:'shared',event_ids:['a','b'],document_version_id:'v',operation:'replace',anchor:evidence,before_text:evidence.quote,after_text:'统一解除与结算安排',rationale:'共同处理',basis_refs:[],state:'draft',coordination:{group_id:'g',event_ids:['a','b'],requirement_ids:[],summary:'最终统一方案',structurally_valid:true}}
 const run={id:'r',status:'needs_input',document_version_id:'v',result_schema_version:'interactive-review-v3',issues,findings:issues,revision_proposals:[p],decisions:[{finding_id:'b',action:'acknowledged',note:'已核对退款风险'}]}
 const html=render.results({initialMode:'clause',run,version:{id:'v',blocks:[{id:'p',text:evidence.quote}]},cid:'c',locked:false,ready:true,active:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.equal((html.match(/data-clause-result=/g)??[]).length,1)
 assert.equal((html.match(/data-proposal-id="shared"/g)??[]).length,1)
 assert.match(html,/2 个风险点/);assert.match(html,/风险说明a/);assert.match(html,/风险说明b/)
 assert.match(html,/已核对退款风险/);assert.match(html,/旧的单项修改方向/)
 const conflict=render.results({initialMode:'clause',run:{...run,revision_proposals:[{...p,state:'conflict'}]},version:{id:'v',blocks:[{id:'p',text:evidence.quote}]},cid:'c',locked:false,ready:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(conflict,/尚未形成可共同采用的统一稿/);assert.match(conflict,/查看未采用的候选稿/)
})

test('original-text buttons remain clickable while editor is loading or processing is locked',()=>{
 const evidence={block_id:'b',start:0,end:2,quote:'原文'}
 const html=render.card({finding:{id:'f',rule_id:'CR-02',status:'flag',explanation:'风险',evidence:[evidence]},run:{id:'r',stale:true,findings:[]},cid:'c',version:{id:'v',blocks:[{id:'b',text:'原文'}]},collapsed:false,locked:true,locateLocked:true,ready:false,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/<button[^>]*class="result-locate"[^>]*>.*?定位原文<\/button>/)
 assert.doesNotMatch(html,/<button[^>]*class="result-locate"[^>]*disabled/)
 assert.doesNotMatch(html,/<button[^>]*class="result-evidence-chip"[^>]*disabled/)
 assert.match(html,/<button[^>]*disabled=""[^>]*>记录处理/)
})


test('cumulative liability rows offer clause-specific navigation even when general evidence starts at another clause',()=>{
 const anchors=['1.3 保密条款。','1.1 逾期交付。','1.4 解约退款。'].map((quote,index)=>({block_id:'p'+index,start:0,end:quote.length,quote}))
 const finding={id:'f',rule_id:'VL-01',status:'insufficient_evidence',explanation:'累计责任',evidence:anchors,
  card_content:{version:'review-card-v1',modification_plan:'',risk_paragraphs:[
   {text:'逾期交付违约金',evidence:[anchors[1]]},{text:'解约退款与违约金',evidence:[anchors[2]]},
  ]}}
 const version={id:'v',blocks:anchors.map(a=>({id:a.block_id,text:a.quote}))}
 const run={id:'r',document_version_id:'v',findings:[finding]}
 const html=render.card({finding,run,version,cid:'c',collapsed:false,locked:false,ready:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/<button(?=[^>]*class="result-locate")(?=[^>]*aria-haspopup="menu")[^>]*>.*?定位原文.*?<\/button>/)
 assert.match(html,/aria-label="定位第 1\.1 条"/)
 assert.match(html,/aria-label="定位第 1\.4 条"/)
 assert.doesNotMatch(html,/aria-label="定位第 1\.3 条"/)
})

test('revision differences keep inline placeholders without the confirmation section or count',()=>{
 const run={id:'r',document_version_id:'v',findings:[]},version={id:'v',blocks:[]}
 const proposal={id:'p',event_ids:[],document_version_id:'v',operation:'replace',before_text:'原句',after_text:'待确认文本',rationale:'需核对',basis_refs:[],state:'context_required',message:'旧版长提示；不要同时重复显示'}
 const text='协商期限待确认'
 const html=render.proposal({proposal:{...proposal,confirmation_items:[{id:'a',text,source:'draft'},{id:'b',text:text+'。',source:'requirement',parameter_sources:[{value:'10日',origin:'model_proposal'}]}]},run,version,locked:false})
 assert.match(html,/<ins>待确认文本<\/ins>/)
 assert.doesNotMatch(html,/待确认事项|待确认 1 项|协商期限待确认|模型建议，未经确认|旧版长提示/)
 const legacy=render.proposal({proposal,run,version,locked:false})
 assert.match(legacy,/<ins>待确认文本<\/ins>/)
 assert.doesNotMatch(legacy,/旧版长提示|待确认事项|待确认 1 项/)
})

test('completed compact results merge identical primary ranges and show a shared revision once',()=>{
 const anchor={block_id:'p',start:0,end:4,quote:'同一原文'}
 const other={block_id:'q',start:0,end:4,quote:'另一原文'}
 const issues=[anchor,other,anchor].map((event_anchor,i)=>({
  id:String(i),event_id:String(i),clause_number:'10.2',title:'10.2 事项'+i,rule_id:'VL-01',status:'flag',
  event_anchor,evidence:[anchor],explanation:'风险'+i,review_state:'reviewed'
 }))
 const proposal={id:'shared',state:'draft',event_ids:['0','2'],anchor,operation:'replace',before_text:anchor.quote,after_text:'统一改文',rationale:'限责',document_version_id:'v'}
 const run={id:'r',document_version_id:'v',status:'needs_input',result_schema_version:'interactive-review-v3',issues,findings:issues,revision_proposals:[proposal]}
 const html=render.results({run,version:{id:'v',blocks:[]},compactStream:true,cid:'c',locked:false,ready:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/2 项审查结果 · 3 个风险点/)
 assert.deepEqual([...html.matchAll(/class="result-number" aria-hidden="true">(\d+)</g)].map(match=>match[1]),['01','02'])
 const summary=html.match(/<details class="review-finding finding-flag review-merged-result"[^>]*>(<summary.*?<\/summary>)/s)?.[1]
 assert.match(summary,/class="result-row-title">第 10.2 条</)
 assert.match(summary,/class="merged-risk-preview"><span>事项0<\/span><span>事项2<\/span>/)
 assert.equal((html.match(/<details class="review-finding finding-flag review-merged-result"/g)??[]).length,1)
 assert.equal((html.match(/data-proposal-id="shared"/g)??[]).length,1)
 for(const issue of issues)assert.match(html,new RegExp('data-finding-id="'+issue.id+'"'))
})

test('completed review shows pending verification separately when it has zero flags',()=>{
 const run={id:'r',status:'needs_input',result_schema_version:'interactive-review-v3',issues:[],findings:[],rule_results:[{rule_id:'VL-01',status:'insufficient_evidence',execution_state:'completed',explanation:'项目口径须运管确认'}]}
 const html=render.results({run,compactStream:true,version:null,cid:'c',locked:false,ready:true,onLocate(){},onDecision(){},onSupplement(){}})
 assert.match(html,/项目口径须运管确认/)
 assert.match(html,/问题事件 0/)
 assert.doesNotMatch(html,/本轮未发现需要处理的事项/)
})
