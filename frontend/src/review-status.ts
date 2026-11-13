import { reviewItems } from './review-issues'
import type { Finding, ReviewDecision, ServerRun } from './backend-api'

export const aiLabels:Record<string,string>={flag:'发现问题',insufficient_evidence:'证据不足',no_flag_for_target_rule:'本项未发现问题',not_applicable:'本项不适用'}
export const decisionLabels:Record<string,string>={acknowledged:'已核对',ignored:'已忽略',exception_recorded:'已记录例外',false_positive:'已标记误报',needs_business_confirmation:'待业务确认'}
export const needsReview=(finding:Pick<Finding,'status'>)=>['flag','insufficient_evidence'].includes(finding.status)
export const isResolved=(decision?:ReviewDecision)=>!!decision&&decision.action!=='needs_business_confirmation'
export type ReviewFilter='all'|'pending'|'evidence'|'handled'
export function matchesFilter(f:Pick<Finding,'status'>,decision:ReviewDecision|undefined,filter:ReviewFilter){
  if(filter==='all')return true
  if(filter==='handled')return isResolved(decision)
  if(filter==='evidence')return f.status==='insufficient_evidence'&&!isResolved(decision)
  return needsReview(f)&&!isResolved(decision)
}
export function summarizeReview(run:Pick<ServerRun,'findings'|'decisions'|'result_schema_version'|'issues'>|null){
  const decisions=new Map(run?.decisions?.map(d=>[d.finding_id,d]))
  const required=reviewItems(run).filter(needsReview)
  return {decisions,pending:required.filter(f=>!isResolved(decisions.get(f.id))).length,handled:required.filter(f=>isResolved(decisions.get(f.id))).length}
}
export function elapsedLabel(run:Pick<ServerRun,'created_at'|'finished_at'>,now=Date.now()){
  if(!run.created_at)return ''
  const end=run.finished_at?Date.parse(run.finished_at):now
  const seconds=Math.max(0,Math.floor((end-Date.parse(run.created_at))/1000))
  if(!Number.isFinite(seconds))return ''
  return seconds<60?`${seconds} 秒`:`${Math.floor(seconds/60)} 分 ${seconds%60} 秒`
}

export const reviewProgressText=(run:Pick<ServerRun,'stage'|'progress'>)=>run.stage==='checking'?'正在依据审查规则核验合同':run.progress
