import {needsReview} from './review-status'
import type {ExecutionState,ReviewUnit} from './review-execution'
export type ReviewGuidance={phase:'queued'|'checking'|'attention'|'incomplete'|'settling'|'clear'|'context';eligible:boolean;reason:string;detail:string;signature:string;related:number}
// A compact content fingerprint survives final reconciliation dropping stream revision metadata.
function fingerprint(value:unknown){let hash=2166136261;for(const char of JSON.stringify(value)){hash=Math.imul(hash^char.codePointAt(0)!,16777619)}return (hash>>>0).toString(36)}
export function unitGuidance(state:ExecutionState,unit:ReviewUnit):ReviewGuidance{
 const blocks=unit.block_ids??[unit.anchor.block_id],ids=unit.task_ids??[],tasks=ids.flatMap(id=>state.tasks[id]?[state.tasks[id]]:[])
 const issues=Object.values(state.issues).filter(i=>needsReview(i)&&(i.event_anchor?[i.event_anchor]:i.evidence??[]).some(e=>blocks.includes(e.block_id)))
 const related=new Set(issues.flatMap(i=>i.evidence??[]).filter(e=>!blocks.includes(e.block_id)).map(e=>`${e.block_id}:${e.start}:${e.end}`)).size
 const signature=fingerprint([...issues].sort((a,b)=>a.id.localeCompare(b.id)).map(i=>[i.id,i.status,i.explanation,i.presentation?.summary,i.presentation?.next_step,i.suggested_text,(i.evidence??[]).map(e=>[e.block_id,e.start,e.end,e.quote])]))
 if(issues.length){const first=issues[0];return {phase:'attention',eligible:true,reason:`${issues.length} 项意见需要核对`,detail:first.presentation?.summary||first.explanation,signature,related}}
 const failed=tasks.filter(t=>t.state==='failed')
 if(failed.length)return {phase:'incomplete',eligible:true,reason:'本条核查未完成',detail:failed[0].message||'当前任务未能完成，不能据此判断本条没有问题。',signature:failed.map(t=>t.id).sort().join('|'),related}
 const running=tasks.filter(t=>t.state==='running')
 if(running.length)return {phase:'checking',eligible:true,reason:running.map(t=>t.title||'当前条款').join('；'),detail:'后台正在执行这项核查，结果返回前保持当前位置。',signature:running.map(t=>t.id).join('|'),related}
 if(ids.length&&(tasks.length<ids.length||tasks.some(t=>t.state==='queued')))return {phase:'queued',eligible:false,reason:'本条等待核查',detail:'后台尚未开始这项任务。',signature:'queued',related}
 if(tasks.length&&['queued','running'].includes(state.status))return {phase:'settling',eligible:false,reason:'任务已返回，正在等待核查意见',detail:'结果尚未形成完整回执，保持当前位置。',signature:'settling',related}
 return {phase:tasks.length?'clear':'context',eligible:false,reason:tasks.length?'本条相关任务已结束':'正文阅读单元',detail:tasks.length?'本轮没有可展示的待复核意见，可从目录查看原文。':'没有关联到独立核查任务，仍可通过阅读目录查看；不代表本条无风险。',signature:'context',related}
}
