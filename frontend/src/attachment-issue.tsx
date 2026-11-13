import { useState } from 'react'
import { api, type Finding, type IssueHistory } from './backend-api'
import { aiLabels, decisionLabels } from './review-status'
import { historyChanges, supplementAction, type SupplementMode } from './review-issue-presentation'
import { Button } from './components/ui/button'

export function AttachmentIssue({issue,runId,disabled,onSupplement}:{issue:Finding;runId:string;disabled:boolean;onSupplement:(mode:SupplementMode)=>void}){
  const [history,setHistory]=useState<IssueHistory|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[expanded,setExpanded]=useState(false)
  const action=supplementAction(issue)
  async function load(){setBusy(true);setError('');try{setHistory(await api<IssueHistory>(`/runs/${runId}/issues/${issue.id}/history`));setExpanded(true)}catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}}
  return <section className="attachment-issue-actions">
    <div className="review-supplement-actions"><Button size="sm" variant="outline" disabled={disabled} onClick={()=>onSupplement(action.mode)}>{action.label}</Button><Button size="sm" variant="ghost" disabled={busy} aria-expanded={expanded} onClick={()=>history?setExpanded(!expanded):void load()}>{busy?'正在读取…':expanded?'收起处理记录':'处理记录与结论变化'}</Button></div>
    {error&&<p role="alert">{error} <button onClick={()=>void load()}>重试</button></p>}
    {history&&expanded&&<ol className="review-history-timeline" aria-label="审查结论变化">{historyChanges(history).map(item=><li key={`${item.run_id}:${item.issue.id}`}>
      <div className="review-history-heading"><strong>{item.run_id===runId?'本轮':'此前审查'}</strong>{item.created_at&&<time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString('zh-CN')}</time>}</div>
      <p className="review-history-change">{item.change}</p><p>{item.previousStatus&&item.previousStatus!==item.issue.status?`${aiLabels[item.previousStatus]??item.previousStatus} → `:''}{aiLabels[item.issue.status]??item.issue.status}</p>
      <details><summary>查看该轮依据</summary><p>{item.issue.explanation}</p>{item.issue.evidence.map((e,i)=><blockquote key={i}>{e.quote}</blockquote>)}</details>
      {item.decisions.map((d,i)=><p key={i}>人工处理 · {decisionLabels[d.action]??d.action}：{d.note}</p>)}
    </li>)}{history.assertions.map((a,i)=><li key={`assertion-${i}`}><strong>用户说明 · {a.actor??'用户'}</strong><p>{a.statement??a.text}</p><small>用户来源，未经文档证据核验</small></li>)}{!history.items.length&&<li>暂无历史记录。</li>}</ol>}
  </section>
}
