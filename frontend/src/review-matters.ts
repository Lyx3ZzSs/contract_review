import {needsReview} from './review-status'
import type {Evidence,Finding} from './backend-api'
import type {ExecutionState,ExecutionTask} from './review-execution'
import {evidenceKey,issuePresentation} from './review-issue-presentation'
export type ReviewMatter={id:string;title:string;anchor:Evidence;task?:ExecutionTask;issues:Finding[];evidence:Evidence[];phase:'queued'|'checking'|'settling'|'attention'|'incomplete'|'finished';detail:string}
// Task identity is independent of paragraph/view position and of later issue revisions.
export function buildReviewMatters(state:ExecutionState|null,issues:Finding[]):ReviewMatter[]{
 if(!state)return []
 const tasks=Object.values(state.tasks).filter((t):t is ExecutionTask&{anchor:Evidence}=>!!t.anchor)
 const linked=new Set<string>()
 const make=(id:string,anchor:Evidence,task:ExecutionTask|undefined,findings:Finding[]):ReviewMatter=>{
  const first=findings[0],presentation=first?issuePresentation(first,first.rule_id):undefined
  const evidence=[anchor,...findings.flatMap(f=>[...(f.event_anchor?[f.event_anchor]:[]),...f.evidence])].filter((e,i,all)=>all.findIndex(other=>evidenceKey(other)===evidenceKey(e))===i)
  const actionable=findings.some(needsReview)
  const phase=task?.state==='failed'?'incomplete':actionable?'attention':task?.state==='running'?'checking':task?.state==='queued'?'queued':findings.length?'finished':task&&['running','queued'].includes(state.status)?'settling':'finished'
  const detail=phase==='incomplete'?task?.message||'这项核查未完成，不能据此判断没有问题。':presentation?.summary??(phase==='checking'?'后台正在核查这一事项；有经过校验的证据和意见时，会在这里更新。':phase==='queued'?'任务尚未开始，正文不会按计时器轮播。':phase==='settling'?'任务已返回，正在等待经过校验的意见。':'当前没有有效待处理意见，不代表所有条款均无风险。')
  return {id,title:task?.title||presentation?.title||'核查相关约定',anchor,task,issues:findings,evidence,phase,detail}
 }
 const matters=tasks.sort((a,b)=>(a.first_seq??0)-(b.first_seq??0)).map(task=>{
  // Never merge independent matters just because their evidence shares a paragraph.
  const own=issues.filter(f=>!!f.event_id&&(task.id===`${f.event_id}:${f.rule_id}`||task.event_id===f.event_id&&task.rule_id===f.rule_id))
  own.forEach(f=>linked.add(f.id));return make('task:'+task.id,task.anchor,task,own)
 })
 for(const issue of issues){
  if(linked.has(issue.id))continue
  const anchor=issue.event_anchor??issue.evidence[0]
  if(anchor)matters.push(make('issue:'+issue.id,anchor,undefined,[issue]))
 }
 return matters
}
export function selectMatter(matters:ReviewMatter[],selectedId:string|undefined,blockIds:string[]){
 const selected=matters.find(m=>m.id===selectedId)
 if(selected&&blockIds.includes(selected.anchor.block_id))return selected
 const local=matters.filter(m=>blockIds.includes(m.anchor.block_id))
 return local.find(m=>['checking','attention','incomplete'].includes(m.phase))??local[0]
}

// A task's reading anchor stays stable; validated, narrower evidence gets the stronger mark.
export function matterPresentation(matter:ReviewMatter){
 const anchor=matter.anchor;
 const current=matter.issues.filter(needsReview).flatMap(i=>i.evidence).find(e=>e.block_id===anchor.block_id&&e.start>=anchor.start&&e.end<=anchor.end&&e.end-e.start<anchor.end-anchor.start)??anchor;
 const related=matter.evidence.filter(e=>!(e.block_id===current.block_id&&e.start<=current.start&&e.end>=current.end));
 return {current,related};
}
