import type { ServerRun, Evidence, MaterialVersion, Finding, AttachmentLink, Version, ServerResult, SupplementReceipt } from './backend-api'
type ReviewData = Pick<ServerRun, 'findings'|'result_schema_version'|'issues'|'rule_results'>
export const isInteractive = (run: Pick<ServerRun,'result_schema_version'>|null) => ['interactive-review-v1','interactive-review-v2','interactive-review-v3'].includes(run?.result_schema_version??'')
export const reviewItems = (run: ReviewData|null) => !run ? [] : isInteractive(run) ? run.issues ?? [] : run.findings
export const ruleResults = (run: ReviewData|null) => !run ? [] : isInteractive(run) ? run.rule_results ?? [] : run.findings
export const isReviewStale = (run: ServerRun|null, documentVersion?:string, bundleId?:string) => !!run && (!!run.stale || !!documentVersion && run.document_version_id !== documentVersion || !!bundleId && run.material_bundle_id !== bundleId)
export function groupReviewIssues(run: ReviewData|null) {
  const items = reviewItems(run)
  return ruleResults(run).map(rule => ({rule,issues:items.filter(issue => issue.rule_id === rule.rule_id)}))
}
export function previousCompletedRun(runs: ServerRun[]) {
  if(!runs[0] || !['queued','running','failed'].includes(runs[0].status))return null
  return runs.slice(1).find(run=>!['queued','running','failed'].includes(run.status))??null
}

export function materialEvidence(evidence:Evidence, materials:MaterialVersion[]) {
  for(const material of materials){
    const block=material.blocks?.find(b=>b.id===evidence.block_id)
    if(!block)continue
    const chars=[...block.text]
    if(evidence.start<0 || evidence.end>chars.length || evidence.end<=evidence.start || chars.slice(evidence.start,evidence.end).join('')!==evidence.quote)return null
    return {material,before:chars.slice(0,evidence.start).join(''),quote:evidence.quote,after:chars.slice(evidence.end).join('')}
  }
  return null
}
export function linkedBodyBlocks(issue:Finding, links:AttachmentLink[], blocks:Version['blocks']) {
  const name=issue.attachment_name??issue.reference_name
  if(!name)return []
  const valid=new Set(blocks.map(b=>b.id))
  return [...new Set(links.filter(l=>l.reference_name===name&&!l.target_material_version_id).flatMap(l=>l.target_block_ids).filter(id=>valid.has(id)))]
}

export function isCurrentFinalization(result:ServerResult|undefined, latest:ServerRun|null, documentVersion?:string, reopenedAt?:string|null) {
  if(!result || result.document_version_id!==documentVersion || reopenedAt && reopenedAt>=result.created_at)return false
  if(result.review_snapshot?.stale)return false
  if(!latest)return true // Legacy snapshots can predate a separately exposed run.
  if(latest.stale || !['completed','needs_input'].includes(latest.status) || latest.document_version_id!==documentVersion)return false
  const runId=result.run_id??result.review_snapshot?.id
  if(runId ? latest.id!==runId : !latest.created_at || latest.created_at>result.created_at)return false
  return (latest.material_bundle_id??null)===(result.material_bundle_id??result.review_snapshot?.material_bundle_id??null)
}
export async function acceptSubmittedReview(previous:ServerRun, receipt:SupplementReceipt, publish:(run:ServerRun)=>void, refresh:()=>Promise<void>, onError:(message:string)=>void) {
  // The POST receipt is authoritative even if every subsequent read fails.
  publish({id:receipt.review_id,document_version_id:previous.document_version_id,material_bundle_id:receipt.bundle_id,parent_run_id:receipt.parent_run_id,status:'queued',stage:'queued',progress:'补充资料已保存，等待同步复审进度',findings:[],issues:[],rule_results:[],decisions:[],result_schema_version:previous.result_schema_version})
  try{await refresh()}catch(error){onError(error instanceof Error?error.message:String(error))}
}

export function hasIncompleteReview(run: Pick<ServerRun,'module_errors'|'rule_results'|'findings'>) {
  return !!run.module_errors?.length || (run.rule_results??run.findings??[]).some(r=>r.execution_state==='failed'||r.execution_state==='not_run')
}
export function coverageGroups(run: ServerRun) {
  const results=ruleResults(run)
  // Retain historical uncovered baseline entries, then include every configured or returned rule.
  const ids=[...new Set(['RL-01','RL-02','RL-03','RL-04','RL-05','CR-01','CR-02',...(run.rule_snapshot?.rules??[]).map(r=>r.id),...results.map(r=>r.rule_id)])]
  return [{title:'基础检查',ids:ids.filter(id=>id.startsWith('RL-'))},{title:'责任与费用保护',ids:ids.filter(id=>id.startsWith('CR-'))},{title:'其他检查',ids:ids.filter(id=>!id.startsWith('RL-')&&!id.startsWith('CR-'))}].filter(group=>group.ids.length).map(group=>({title:group.title,rules:group.ids.map(id=>{
    const result=results.find(r=>r.rule_id===id)
    const configured=run.rule_snapshot?.rules.some(r=>r.id===id)
    const state=result?(result.execution_state??'completed'):configured?'not_run':'uncovered'
    return {id,result,state}
  })}))
}
