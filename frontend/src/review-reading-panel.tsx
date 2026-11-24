import type {RuleResult} from './backend-api'
import type {ReactNode} from 'react'
import type {ExecutionState} from './review-execution'
import {followTargets,type FollowTarget} from './review-follow'
export function ReviewReadingPanel({state,target,onSelect,disabled,ruleResults,children}:{state:ExecutionState;target?:FollowTarget;onSelect:(target:FollowTarget)=>void;disabled:boolean;ruleResults?:RuleResult[];children?:ReactNode}){
 if(!state.plan)return null
 const targets=followTargets(state),index=targets.findIndex(t=>t.key===target?.key),unit=state.plan.units.find(u=>u.id===target?.unitId)
 const guidance=targets[index]?.guidance
 const globalTasks=Object.values(state.tasks).filter(t=>t.id.startsWith('base:'))
 return <section className="review-reading" aria-label="逐条审阅">
 <strong>{['queued','running'].includes(state.status)?'核查进度 · 手动查看原文':'核查已结束 · 阅读审查意见'}</strong>
 <p>{index<0?'选择目录或原文引用进行核对':`当前查看 ${index+1} / ${targets.length}`}</p>
 {guidance&&<div className="review-guidance" data-phase={guidance.phase}><strong>{guidance.reason}</strong><p>{guidance.detail}</p>{guidance.related>0&&<small>需要结合 {guidance.related} 处关联原文核对，可从下方意见查看证据。</small>}</div>}
 <small>{unit?.screening??state.plan.scope}。未产生意见不代表本条无风险。</small>
 <div><button disabled={disabled||index<=0} onClick={()=>onSelect(targets[index-1])}>上一条</button><button disabled={disabled||index>=targets.length-1} onClick={()=>onSelect(targets[index+1])}>下一条</button></div>
 <details><summary>阅读目录（{targets.length}）</summary><ol>{targets.map((t,n)=><li key={t.key}><button disabled={disabled} aria-current={n===index?'step':undefined} onClick={()=>onSelect(t)}>{n+1}. {t.title}</button></li>)}</ol></details>
 {globalTasks.length>0&&<details><summary>全文抽取 · {globalTasks.filter(t=>t.state==='completed').length} / {globalTasks.length} 项完成</summary><ul>{globalTasks.map(t=><li key={t.id}>{t.title??t.id}：{({queued:'等待检查',running:'正在检查',completed:'抽取完成',failed:'未完成'})[t.state]}{t.state==='failed'&&t.message?` · ${t.message}`:''}</li>)}</ul></details>}
 {ruleResults?.length&&!['queued','running'].includes(state.status)?<details><summary>规则核验 · {ruleResults.filter(r=>r.execution_state!=='failed'&&r.execution_state!=='not_run').length} / {ruleResults.length} 项完成</summary><ul>{ruleResults.map(r=><li key={r.rule_id}>{r.rule_id}：{r.execution_state==='failed'||r.execution_state==='not_run'?'核验未完成':r.status==='insufficient_evidence'?'已核验，待补充依据':r.status==='flag'?'已核验，有待处理问题':'本轮规则核验完成'}</li>)}</ul></details>:null}
 {children}
 </section>
}
