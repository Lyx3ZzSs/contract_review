import type {AnalysisArtifact,ExecutionState,ReviewPhase} from './review-execution'
import type {Finding,RuleResult,ServerRun} from './backend-api'
import {aiLabels,needsReview} from './review-status'
export const CONFIGURED_REVIEW_POLICY='review-configured-rules-v1'
export const processChecks=['文字符号','程序条款','合法性'] as const
export type ProcessState=ReviewPhase['state']|'unavailable'|'attention'
export type ProcessSection=AnalysisArtifact['sections'][number]&{key:string;provisional:boolean}
export type ProcessItem={id:string;title:string;state:ProcessState;sections:ProcessSection[];message?:string;statusLabel?:string;revisionMessage?:string;formEntries?:ProcessSection[];clauses?:ClauseProgress[];steps?:ExecutionState['tasks'][string][];basicCheck?:boolean}
export type ProcessRules=Pick<ServerRun,'rule_snapshot'|'rule_results'|'context_snapshot'>

type ClauseProgress={id:string;anchor:Finding['evidence'][number];message:string;state:ProcessState;issue?:ProcessItem}

function liabilityProgress(tasks:ExecutionState['tasks'][string][],issues:Finding[],rows:ProcessItem[],running:boolean){
 const clauses=new Map<string,ClauseProgress>()
 for(const task of tasks){
  if(!task.id.startsWith('base:liability-limit:group-'))continue
  const perspective=task.id.endsWith('-perspective')
  const message=task.state==='failed'?'本条核查未完成':task.state==='completed'?
   (running?'已完成本步，等待整体核对':'本条核查已结束'):
   (perspective?'正在核对我方利益':'正在核查责任约定')
  for(const section of task.sections??[])for(const anchor of section.evidence){
   clauses.set(anchor.block_id,{id:anchor.block_id,anchor,state:task.state,message})
  }
 }
 const linked=new Set<string>()
 for(const [index,issue] of issues.entries()){
  const row=issue.event_anchor&&clauses.get(issue.event_anchor.block_id)
  if(!row||row.issue)continue
  row.issue=rows[index];row.state=rows[index].state
  row.message=rows[index].revisionMessage||rows[index].statusLabel||'核查意见已返回'
  linked.add(rows[index].id)
 }
 return {clauses:[...clauses.values()],linked}
}

export function processTaskTitle(task:ExecutionState['tasks'][string]){
 return task.id==='base:facts'?'核对金额、附件及填写情况':task.title
}

// A shared extraction can serve several rules. Only show steps whose task was recorded.
const basicRuleSteps:Record<string,Record<string,string>>={
 'RL-01':{'base:basic':'比对期限类型、起算条件和时长'},
 'RL-02':{'base:facts':'提取算式、分期比例和计价依据'},
 'RL-03':{'base:assignment':'核对转让主体和同意条件'},
 'RL-04':{'base:basic':'检查正文中的附件约定','base:facts':'识别正文引用的附件','base:attachments':'核对已提供的附件材料'},
 'RL-05':{'base:facts':'区分填写状态和当前必填要求'},
}

function basicCheckSteps(id:string, tasks:ExecutionState['tasks'][string][]){
 const labels=basicRuleSteps[id]
 if(!labels)return []
 return tasks.filter(t=>labels[t.id]).map(t=>{
  let observation=t.rule_observations?.[id]
  // Older runs saved the extracted facts without per-rule counts.
  if(!observation&&t.id==='base:facts'&&t.state==='completed'&&t.sections?.length){
   const titles=t.sections.map(s=>s.title)
   if(id==='RL-04')observation=`提取记录中有 ${titles.filter(t=>t==='附件引用').length} 项附件引用。`
   if(id==='RL-02')observation=`提取记录中有 ${titles.filter(t=>t==='金额核算依据').length} 项可复算关系。`
   if(id==='RL-05')observation=`提取记录中有 ${titles.filter(t=>t==='关键字段').length} 项填写情况。`
  }
  const sections=t.sections?.filter(s=>(t.id==='base:assignment'&&id==='RL-03')||
   (t.id==='base:facts'&&((id==='RL-04'&&s.title==='附件引用')||(id==='RL-02'&&s.title==='金额核算依据'))))
  const message=t.state==='failed'?t.message:t.state==='completed'?observation:t.rule_scope?.[id]
  return {...t,id:`${id}:${t.id}`,title:labels[t.id],message,sections}
 })
}

function basicOutcome(issue:RuleResult){
 if(issue.status!=='no_flag_for_target_rule'||issue.execution_state!=='completed'||issue.review_state==='adjusted')return
 switch(issue.rule_id){
  case 'RL-01':
   if(issue.evidence?.length)return {label:'未见期限冲突',text:issue.explanation}
   break
  case 'RL-02':
   if(issue.computed_calculations?.length===0)return {label:'未作金额复算',text:'本轮未提取到可按同一口径复算的算式或分期比例。'}
   if(issue.computed_calculations?.length)return {label:'已复算',text:issue.explanation}
   break
  case 'RL-03':
   if(issue.review_reason==='no_customer_assignment_permission')return {label:'未见允许客户自行转让的约定',text:''}
   break
  case 'RL-04':
   if(issue.attachment_references?.length===0&&!issue.reference_name&&!issue.attachment_name)return {label:'未识别到附件引用',text:''}
   break
  case 'RL-05':
   if(issue.field_checks?.length===0||issue.explanation==='本次已解析范围内未提取到关键字段的具体空白或占位证据。')return {label:'未发现当前必填缺项',text:''}
 }
}

function configuredProcess(state:ExecutionState,run?:ProcessRules){
 const facts=state.tasks['base:facts']
 const transaction:ProcessItem[]=[]
 const overview=state.artifacts?.['transaction-overview']
 if(overview)transaction.push({
  id:overview.id,title:'提取合同事实',
  state:overview.state==='generating'||overview.state==='validating'?'running':overview.state,
  sections:overview.sections.length?overview.sections.map(section=>({...section,key:`${overview.id}:topic:${section.title}`,provisional:false})):artifactSections(overview).map(section=>({...section,key:`${overview.id}:topic:${section.title}`})),message:overview.message,
 })
 else if(facts?.sections?.length){
  // Older runs may only have the specialist extraction.
  const sections=facts.sections.filter(s=>s.title==='金额核算依据'||s.title==='附件引用')
   .map((s,i)=>({...s,key:`${facts.id}:${i}`,provisional:false}))
  if(sections.length)transaction.push({id:facts.id,title:'已记录的金额与附件依据',state:facts.state,sections})
 }

 const parsed=state.phases?.parse
 if(parsed?.message){
  const role=run?.context_snapshot?.our_party
  transaction.unshift({id:'transaction-context',title:'审查范围与立场',state:parsed.state,
   sections:[{key:'transaction-context',title:'',text:[typeof role==='string'&&role?`我方立场：${role}`:'',parsed.message].filter(Boolean).join('\n'),evidence:[],provisional:false}]})
 }

 const running=['queued','running'].includes(state.status)
 const issues=Object.values(state.issues as Record<string,Finding&{first_seq?:number}>)
  .filter(issue=>issue.rule_id&&(!running||issue.review_state==='reviewed'))
  .sort((a,b)=>(a.first_seq??0)-(b.first_seq??0))
 const seen=new Set(issues.map(issue=>issue.rule_id))
 const titles=new Map(run?.rule_snapshot?.rules.map(rule=>[rule.id,rule.title]))
 const remaining=running?[]:run?.rule_results?.filter(rule=>!seen.has(rule.rule_id))??[]
 const records=[...issues,...remaining]
 const conclusions=records.map((issue):ProcessItem=>{
  const failed=issue.execution_state==='failed'||issue.execution_state==='not_run'
  const attachment=issue.reference_name??issue.attachment_name
  const title=issue.title||(attachment?`附件核验 · 《${attachment}》`:titles.get(issue.rule_id)??issue.rule_id)
  const outcome=basicOutcome(issue)
  const text=outcome?.text??((basicRuleSteps[issue.rule_id]?issue.explanation:'')||issue.presentation?.summary||issue.explanation)
  const evidence=basicRuleSteps[issue.rule_id]&&issue.evidence?.length?issue.evidence:issue.event_anchor?[issue.event_anchor]:issue.evidence??[]
  return {
   id:issue.id,title,state:failed?'failed':needsReview(issue)?'attention':'completed',
   statusLabel:failed?undefined:outcome?.label??aiLabels[issue.status],
   message:failed?text:undefined,
   sections:failed||(!text&&!evidence.length)?[]:[{key:issue.id,title:'',text,evidence,provisional:false}],
   revisionMessage:issue.revision_plan?.state==='ready'?'改文已就绪，待人工确认':issue.revision_plan?.message,
  }
 })
 const tasks=Object.values(state.tasks).sort((a,b)=>(a.first_seq??0)-(b.first_seq??0))
 const ruleIds=new Set([...(titles.keys()),...records.map(r=>r.rule_id)])
 const risk:ProcessItem[]=[]
 for(const id of ruleIds){
  const ruleRecords=records.filter(r=>r.rule_id===id)
  const rows=conclusions.filter((_,index)=>records[index].rule_id===id)
  const steps=tasks.filter(t=>t.id.startsWith('base:liability-limit:')&&id==='VL-01')
  const {clauses,linked}=liabilityProgress(steps,ruleRecords,rows,running&&state.phases?.rules?.state==='running')
  const ruleSteps=basicCheckSteps(id,tasks)
  const assigned=id==='VL-01'?tasks.filter(t=>t.id==='base:liability-limit'):ruleSteps
  const failed=rows.some(r=>r.state==='failed')||assigned.some(t=>t.state==='failed')
  const stateLabel:ProcessState=failed?'failed':rows.some(r=>r.state==='attention')?'attention':
   rows.length?'completed':!running?'unavailable':(steps.length>0||assigned.some(t=>t.state!=='queued'))?'running':'queued'
  risk.push({id:'rule:'+id,title:titles.get(id)??rows[0]?.title??id,state:stateLabel,basicCheck:!!basicRuleSteps[id],
   formEntries:id==='RL-05'?facts?.sections?.filter(s=>s.title==='关键字段')
    .map((s,i)=>({...s,title:'',key:`field:${i}`,provisional:false})):undefined,
   statusLabel:!failed&&rows.length===1?rows[0].statusLabel:undefined,
   message:rows.find(r=>r.state==='failed')?.message??assigned.find(t=>t.state==='failed')?.message,
   clauses,sections:rows.filter(r=>!linked.has(r.id)).flatMap(r=>r.sections.map(section=>({...section,title:r.title===titles.get(id)?'':r.title}))),
   revisionMessage:rows.length===1?rows[0].revisionMessage:undefined,steps:ruleSteps.length?ruleSteps:steps.filter(t=>!clauses.length||!t.id.includes(':group-')||!t.sections?.length)})
 }
 return {transaction,risk}
}
export function artifactSections(artifact:AnalysisArtifact):ProcessSection[]{
 if(artifact.state==='failed')return []
 if(artifact.state==='completed'){
  let contentIndex=0
  return artifact.sections.map(s=>({...s,key:s.check_id?`${artifact.id}:check:${processChecks.indexOf(s.check_id as typeof processChecks[number])}`:`${artifact.id}:section:${contentIndex++}`,provisional:false}))
 }
 return ['check','section'].flatMap(prefix=>Array.from({length:12},(_,i)=>({
  title:artifact.fields[`${prefix}:${i}:title`]??'',text:artifact.fields[`${prefix}:${i}:text`]??'',evidence:[],
  ...(prefix==='check'?{check_id:processChecks[i]}:{}),key:`${artifact.id}:${prefix}:${i}`,provisional:true,
 })).filter(s=>s.title||s.text))
}
export function reviewProcess(state:ExecutionState,policyVersion?:string,run?:ProcessRules):{transaction:ProcessItem[];risk:ProcessItem[]}{
 if(policyVersion===CONFIGURED_REVIEW_POLICY)return configuredProcess(state,run)
 const artifacts=Object.values(state.artifacts??{}).sort((a,b)=>a.id.localeCompare(b.id,undefined,{numeric:true}))
 const transaction=artifacts.filter(a=>a.id.startsWith('transaction'))
 const discovery=artifacts.filter(a=>a.id.startsWith('discovery'))
 const terminal=!['queued','running'].includes(state.status)
 function item(id:string,title:string,phaseId:string,source:AnalysisArtifact[],select:(s:ProcessSection)=>boolean):ProcessItem{
  const phase=state.phases?.[phaseId],sections=source.flatMap(artifactSections).filter(select)
  let status:ProcessState=phase?.state??(terminal?'unavailable':'queued')
  if(source.some(a=>a.state==='failed'))status='failed'
  else if(source.some(a=>['generating','validating'].includes(a.state)))status='running'
  // Older snapshots without this output cannot be presented as checks that passed.
  if(status==='completed'&&!sections.length)status='unavailable'
  if(terminal&&['running','queued'].includes(status))status='failed'
  if(status==='completed'&&sections.some(s=>s.check_status==='insufficient_evidence'))status='attention'
  return {id,title,state:status,sections,message:source.find(a=>a.state==='failed')?.message??(status==='failed'?phase?.message:undefined)}
 }
 const vertical=policyVersion==='review-agent-v4-power-data'
 const reviewers=vertical?[
  ['topic1-performance','交付与数据授权'],['topic2-performance','验收与回款'],
  ['topic4-remedies','责任与退出结算'],['topic6-consistency','重大例外全文检查'],
 ]:[['performance','履约与结算'],['remedies','责任与退出'],['consistency','程序与一致性']] as const
 const teamReview=vertical||discovery.some(a=>reviewers.some(([key])=>a.id.endsWith('-'+key)))
 const risk=teamReview?reviewers.map(([key,title])=>{
  const assigned=discovery.filter(a=>a.id.endsWith('-'+key))
  const row=item(key,title,'discovery',assigned,()=>true)
  if(state.phases?.discovery?.state==='failed'&&assigned.length&&assigned.every(a=>a.state==='completed')){
   row.state=row.sections.some(s=>s.check_status==='insufficient_evidence')?'attention':'completed'
   row.message=undefined
  }
  return row
 }):[...processChecks.map(title=>item(title,title,'discovery',discovery,s=>s.check_id===title)),item('risk','交易风险','discovery',discovery,s=>!s.check_id)]
 return {
  transaction:[item('type','交易类型分析','transaction',transaction,s=>s.title==='交易类型分析'),item('core','核心交易内容分析','transaction',transaction,s=>s.title!=='交易类型分析')],
  risk,
 }
}
export function isVerifiedLiveIssue(issue:Finding){
 return issue.review_state==='reviewed'&&issue.execution_state!=='failed'&&needsReview(issue)
}
export function showReviewResults(waiting:boolean,state:ExecutionState|null|undefined,policyVersion?:string){
 if(waiting&&policyVersion===CONFIGURED_REVIEW_POLICY)
  return Object.values(state?.issues??{}).some(isVerifiedLiveIssue)
 return !waiting||!Object.keys(state?.phases??{}).length
}
