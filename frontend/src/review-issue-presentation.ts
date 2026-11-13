import type { Evidence, Finding, IssueHistory } from './backend-api'
export type SupplementMode = 'material' | 'link' | 'statement'
export function supplementAction(issue:Finding):{mode:SupplementMode;label:string} {
  if (issue.execution_mode==='case_advisory'||issue.rule_id.startsWith('CR-')) return {mode:'statement',label:'记录法务复核说明'}
  if (!issue.attachment_name&&!issue.reference_name) return {mode:'statement',label:'添加说明'}
  if (['candidate','matched','version_conflict'].includes(issue.match_state??'')) return {mode:'link',label:'关联已有内容'}
  return {mode:'material',label:'补充附件'}
}
export const evidenceKey=(e:Evidence)=>JSON.stringify([e.block_id,e.start,e.end,e.quote])
export function issuePresentation(issue:Finding,fallbackTitle:string) {
  const presentation=issue.presentation?.version==='issue-presentation-v1'?issue.presentation:null
  const observations=presentation?.observations??[]
  const active=observations.filter(o=>o.status==='flag'||o.status==='insufficient_evidence')
  const excluded=observations.filter(o=>o.status==='no_flag_for_target_rule')
  // Metadata may only select already-retained source evidence, never invent a new location.
  const selected=new Set(active.flatMap(o=>[...o.evidence,...o.requirement_evidence]).map(evidenceKey))
  const relevant=issue.evidence.filter(e=>selected.has(evidenceKey(e)))
  const name=issue.attachment_name??issue.reference_name
  const attachmentLabels:Record<string,string>={missing:'本轮未见对应内容',candidate:'对应内容待核验',version_conflict:'版本差异待核验',unreadable:'内容无法读取',title_only:'仅见标题，内容待补充',matched:'匹配内容需核对',future_template:'填写阶段需核对'}
  return {
    title:presentation?.title??issue.title??(name?`${name} · ${attachmentLabels[issue.match_state??'']??'需要核对'}`:fallbackTitle),
    summary:presentation?.summary??issue.explanation,
    nextStep:presentation?.next_step??(issue.execution_mode==='case_advisory'||issue.rule_id.startsWith('CR-')?'需法务复核：核对责任范围、关联条款及适用政策，记录核对或修改方向。':name?'核对本轮材料中的对应内容；可补充附件、关联已有内容或说明提供阶段。':issue.status==='insufficient_evidence'&&issue.rule_id==='RL-03'?'确认我方主体及甲乙方角色，核对客户转让是否需我方同意；如条款未约定，请法务确认是否补充转让限制。':issue.status==='insufficient_evidence'?'核对现有证据和适用条件，补充说明后记录核验结论。':'核对原文与规则要求，再记录处理结论。'),
    evidence:relevant.length?relevant:issue.evidence,active,excluded,structured:!!presentation,
  }
}

export function historyChanges(history:IssueHistory) {
  const rows=[...history.items].sort((a,b)=>(a.created_at??'').localeCompare(b.created_at??''))
  return rows.map((item,index)=>{
    const previous=rows.slice(0,index).reverse().find(row=>row.issue.rule_id===item.issue.rule_id&&
      (item.issue.subject_key?row.issue.subject_key===item.issue.subject_key:row.issue.id===item.issue.id))
    const signature=(finding:Finding)=>finding.evidence.map(evidenceKey).sort().join('|')
    let change='首次记录'
    if(previous) change=previous.issue.status!==item.issue.status?'AI 判断已变化':signature(previous.issue)!==signature(item.issue)?'证据已更新，AI 判断保持不变':previous.issue.explanation!==item.issue.explanation?'判断说明已更新':'AI 判断与证据未变化'
    return {...item,previousStatus:previous?.issue.status,change}
  })
}
