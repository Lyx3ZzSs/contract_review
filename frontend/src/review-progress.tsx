import { useEffect, useState } from 'react'
import { Check, CircleAlert, Clock3, LoaderCircle } from 'lucide-react'
import type { ServerRun } from './backend-api'
import { hasIncompleteReview } from './review-issues'
import { elapsedLabel, reviewProgressText } from './review-status'

const legacyStages=[['queued','等待执行'],['preparing','准备资料'],['extracting','提取合同事实'],['checking','核验审查规则'],['validating','校验证据与结果']]
export function ReviewProgress({run,paused=false,compact=false}:{run:ServerRun;paused?:boolean;compact?:boolean}){
  const [clock,setClock]=useState(Date.now())
  const active=run.status==='queued'||run.status==='running'
  const failed=run.status==='failed'||hasIncompleteReview(run)
  const completed=!failed&&(run.status==='completed'||run.status==='needs_input')
  useEffect(()=>{if(!active||paused)return;const timer=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer)},[active,paused])
  const phaseOrder=['parse','transaction','rules','discovery','synthesis','drafting','verification']
  const phases=Object.values(run.execution_phases??{}).sort((a,b)=>phaseOrder.indexOf(a.id)-phaseOrder.indexOf(b.id))
  const stages=phases.length?phases.map(p=>[p.id,p.title]):legacyStages
  const current=stages.findIndex(([key])=>key===run.stage)
  const seen=new Set(run.stage_history?.map(item=>item.stage))
  const title=paused?'正在恢复进度同步':failed?'本轮审查未完成':active?(run.status==='queued'?'审查已提交':'AI 正在审查'):completed?'AI 分析已完成':'正在确认审查状态'
  const elapsed=elapsedLabel(run,clock)
  if (completed&&!paused) return <div className="review-progress-complete" role="status"><Check/><span>AI 分析已完成</span>{elapsed&&<span>· {elapsed}</span>}</div>
  return <section className={`review-progress ${failed?'is-failed':active?'is-active':completed?'is-done':'is-unknown'}`} aria-label="审查进度">
    <div className="review-progress-heading">{failed?<CircleAlert/>:paused?<Clock3/>:active?<LoaderCircle className="review-spinner"/>:completed?<Check/>:<Clock3/>}<strong role="status">{title}</strong>{elapsed&&<span>{paused?'最近同步时已用':'已用'} {elapsed}</span>}</div>
    <p>{paused?'当前显示最近一次获取的进度，后台任务可能仍在继续。':failed?(run.module_errors?.map(e=>e.message).join('；')||run.error?.message||'本轮没有可用的执行结果，可重新发起审查。'):active?reviewProgressText(run):completed?'本轮审查结果已生成，请核对证据并处理待办。':'尚未确认本轮结果，请刷新任务状态。'}</p>
    {run.stage&&!compact&&<ol className="review-stages">{stages.map(([key,label],i)=>{
      const phase=run.execution_phases?.[key]
      const reached=seen.has(key)
      const done=phase?phase.state==='completed':reached&&(run.stage==='done'||i<current)
      const here=phase?['running','failed'].includes(phase.state):key===run.stage
      return <li key={key} className={done?'done':here?(failed?'failed':'current'):''} aria-current={here?'step':undefined}><span>{done?<Check/>:here&&failed?<CircleAlert/>:i+1}</span><div>{label}{here&&<small>{failed?'此阶段中断':paused?'待同步':'进行中'}</small>}</div></li>
    })}</ol>}
    {active&&!paused&&!compact&&<p className="review-progress-footnote">可以离开页面，后台将继续处理。完成后进入人工复核。</p>}
    {failed&&run.stage&&<p className="review-progress-footnote">已保存的结果会保留；继续执行将恢复未完成任务。审查版本升级时会创建新批次。</p>}
  </section>
}
