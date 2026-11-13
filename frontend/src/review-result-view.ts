import type { Finding, ServerRun } from './backend-api'
import { reviewItems, groupReviewIssues } from './review-issues'
import { needsReview, isResolved, summarizeReview } from './review-status'

export type ResultFilter = 'pending' | 'handled'
export type ResultCategory = 'clauses' | 'attachments' | 'context'
export const resultCategory = (finding:Finding):ResultCategory => finding.display_group==='context'?'context':finding.rule_id==='RL-04'?'attachments':'clauses'
export function buildReviewResultView(run: ServerRun | null) {
  const contextWarnings=[...new Set((run?.diagnostics&&!Array.isArray(run.diagnostics)?run.diagnostics.context_warnings??[]:[]).filter(w=>typeof w==='string'&&w.trim()))]
  const { decisions } = summarizeReview(run)
  const actionable = reviewItems(run).filter(needsReview)
  const pending = actionable.filter(f => !isResolved(decisions.get(f.id)))
  const handled = actionable.filter(f => isResolved(decisions.get(f.id)))
  const categories=([{id:'clauses',label:'条款审查'},{id:'attachments',label:'附件核验'},{id:'context',label:'信息待办'}] as const)
    .filter(c=>c.id==='clauses'||reviewItems(run).some(f=>resultCategory(f)===c.id&&(needsReview(f)||f.attachment_name||f.reference_name)))
    .map(c=>({...c,pending:pending.filter(f=>resultCategory(f)===c.id).length,handled:handled.filter(f=>resultCategory(f)===c.id).length}))
  const defaultCategory=categories.find(c=>c.pending)?.id??categories.find(c=>c.handled)?.id??'clauses'
  const contextItems=actionable.filter(f=>resultCategory(f)==='context')
  const legalItems=actionable.filter(f=>resultCategory(f)==='clauses')
  return { pending, handled, categories, defaultCategory, contextWarnings, contextItems, clauseGroups:groupClauseEvents(legalItems), riskEventCount:new Set(legalItems.map(f=>f.event_id??f.id)).size, proposalCount:run?.revision_proposals?.length??0, coverage: groupReviewIssues(run),
    defaultFilter: (pending.length || !handled.length ? 'pending' : 'handled') as ResultFilter }
}

export function groupClauseEvents(items:Finding[]) {
  const groups=new Map<string,{clauseId:string;events:{eventId:string;issues:Finding[]}[]}>()
  for(const finding of items){
    const clauseId=finding.clause_number??'未标明条款'
    let group=groups.get(clauseId)
    if(!group){group={clauseId,events:[]};groups.set(clauseId,group)}
    const eventId=finding.event_id??finding.id
    let event=group.events.find(e=>e.eventId===eventId)
    if(!event){event={eventId,issues:[]};group.events.push(event)}
    event.issues.push(finding)
  }
  return [...groups.values()]
}
