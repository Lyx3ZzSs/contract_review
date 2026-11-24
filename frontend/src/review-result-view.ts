import type { Finding, ServerRun, Version, RevisionProposal } from './backend-api'
import { reviewItems, groupReviewIssues } from './review-issues'
import { needsReview, isResolved, summarizeReview } from './review-status'

export type ResultFilter = 'pending' | 'handled'
import {reviewClauseAt,reviewClauseLabel} from './clause-tree'
export type ResultCategory = 'clauses' | 'attachments' | 'context'
export const resultCategory = (finding:Finding):ResultCategory => finding.display_group==='context'?'context':finding.rule_id==='RL-04'?'attachments':'clauses'
export const riskCategories = [{id:'transaction',label:'交易条款'},{id:'procedure',label:'程序性条款'},{id:'wording',label:'文字符号'},{id:'legality',label:'合法性'},{id:'other',label:'其他'}] as const
export function riskCategory(f:Finding){return riskCategories.some(c=>c.id===f.review_category)?f.review_category!:'other'}
export function linkedProposals(f:Finding,run:ServerRun,version:Version|null){
 return orderRevisionProposals([...new Map((run.revision_proposals??[]).filter(p=>f.event_id&&p.event_ids.includes(f.event_id)).map(p=>[p.proposal_id??p.id,p])).values()],version)
}
export function resultEmptyState(run:ServerRun,filtered:boolean,handled:boolean,hasHandled:boolean){
 if(filtered)return {title:'没有符合筛选条件的意见',text:'调整筛选条件，查看其他审查意见。'}
 if(handled)return {title:'暂无已处理意见',text:'记录处理结论后，可在这里查看。'}
 if(['queued','running'].includes(run.status))return {title:'正在生成审查意见',text:'已校验的意见会陆续出现在这里。'}
 if(run.status==='failed'||run.module_errors?.length)return {title:'本轮暂无可展示的意见',text:'部分检查未能返回结果，可在执行详情中查看原因并重试。'}
 if(hasHandled)return {title:'本轮待处理意见已处理',text:'可在已处理列表中查看结论；正文操作状态以各条修订为准。'}
 if(['completed','needs_input'].includes(run.status))return {title:'本轮未发现需要处理的事项',text:'可结合合同正文和审查范围核对结果。'}
 return {title:'暂无可展示的审查结果',text:'请在执行详情中查看本轮状态。'}
}
export function buildReviewResultView(run: ServerRun | null) {
  const hiddenNotices=new Set(['合同类型标签与正文业务范围不一致，请核对。','本轮使用仅适用于此合同的已确认个案参数；不代表公司通用规则。'])
  const contextWarnings=[...new Set((run?.diagnostics&&!Array.isArray(run.diagnostics)?run.diagnostics.context_warnings??[]:[]).filter(w=>typeof w==='string'&&w.trim()&&!hiddenNotices.has(w.trim())))]
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


export type ClauseResult = {id:string; title:string; sourceTitle?:string; issues:Finding[]; proposals:RevisionProposal[]; relatedProposalCount:number; relatedProposals:{groupId:string;title:string;proposalId:string}[]}
type SourcePosition = readonly [number, number]
const unknownPosition:SourcePosition=[Infinity,Infinity]
const comparePosition=(a:SourcePosition,b:SourcePosition)=>(a[0]-b[0])||(a[1]-b[1])||0
const compareId=(a:string,b:string)=>a<b?-1:a>b?1:0
function sourcePositions(version:Version|null){
  const blocks=new Map(version?.blocks.map((b,index)=>[b.id,index])??[])
  return (anchor?:{block_id:string;start?:number}):SourcePosition=>{
    const index=anchor?blocks.get(anchor.block_id):undefined
    return index===undefined?unknownPosition:[index,anchor?.start??0]
  }
}
export function orderRevisionProposals(proposals:RevisionProposal[],version:Version|null){
  const position=sourcePositions(version)
  return [...proposals].sort((a,b)=>comparePosition(position(a.anchor),position(b.anchor))||compareId(a.proposal_id??a.id??'',b.proposal_id??b.id??''))
}
// Source identity wins over model-written labels. Unknown locations never collapse
// into a single "unknown clause", and attachment/context items remain independent.
export function groupClauseResults(items:Finding[], run:ServerRun, version:Version|null):ClauseResult[] {
  const position=sourcePositions(version)
  const positions=new Map<string,SourcePosition>()
  const location=(e?:{block_id:string;start:number;end:number})=>{
    const blockId=e?.block_id
    if(!blockId)return null
    const clause=reviewClauseAt(version,e)
    const block=version?.blocks.find(b=>b.id===blockId)
    const number=clause?.number??block?.text.trim().match(/^(\d+(?:\.\d+)+)(?![\d.]|万元|元|年|月|日|%|％)/)?.[1]
    const starts=clause?.source_spans?.length?clause.source_spans:clause?.block_ids.map(block_id=>({block_id,start:0}))??[]
    const first=starts.map(position).sort(comparePosition)[0]
    return {id:clause?.id??blockId,position:first&&Number.isFinite(first[0])?first:position({block_id:blockId,start:0}),...reviewClauseLabel(version,clause,number)}
  }
  const groups=new Map<string,ClauseResult>()
  for(const f of items){
    const source=resultCategory(f)==='clauses'?location(f.event_anchor??f.evidence[0]):null
    const id=source?.id??`issue:${f.id}`
    if(!groups.has(id)){
      groups.set(id,{id,title:source?.title??f.title??'审查事项',sourceTitle:source?.sourceTitle,issues:[],proposals:[],relatedProposalCount:0,relatedProposals:[]})
      positions.set(id,source?.position??unknownPosition)
    }
    groups.get(id)!.issues.push(f)
  }
  const values=[...groups.values()].sort((a,b)=>comparePosition(positions.get(a.id)!,positions.get(b.id)!)||compareId(a.id,b.id)),seen=new Set<string>()
  for(const p of orderRevisionProposals(run.revision_proposals??[],version)){
    const pid=p.proposal_id??p.id!
    if(seen.has(pid))continue
    seen.add(pid)
    const linked=values.filter(g=>g.issues.some(f=>f.event_id&&p.event_ids.includes(f.event_id)))
    if(!linked.length)continue
    const target=location(p.anchor)
    let owner=target?groups.get(target.id):undefined
    if(!owner&&target){
      owner={id:target.id,title:target.title,sourceTitle:target.sourceTitle,issues:[...new Map(linked.flatMap(g=>g.issues).filter(f=>f.event_id&&p.event_ids.includes(f.event_id)).map(f=>[f.id,f])).values()],proposals:[],relatedProposalCount:0,relatedProposals:[]}
      groups.set(owner.id,owner);positions.set(owner.id,target.position);values.push(owner)
    }
    owner??=linked[0]
    owner.proposals.push(p)
    for(const g of linked)if(g!==owner){g.relatedProposalCount++;g.relatedProposals.push({groupId:owner.id,title:owner.title,proposalId:pid})}
  }
  return values.sort((a,b)=>comparePosition(positions.get(a.id)!,positions.get(b.id)!)||compareId(a.id,b.id))
}
