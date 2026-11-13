import { ReviewExecutionPanel } from './review-execution-panel'
import { reduceExecution, type ExecutionState, type ExecutionEvent } from './review-execution'
import { hasIncompleteReview } from './review-issues'
import { FileClock } from 'lucide-react'
import { ReviewPanelHeading, ReviewPanelFooter, ReviewVersionNotice } from './review-panel-chrome'
import { DropdownMenu } from 'radix-ui'
import { LegalFeedbackForm } from './legal-feedback-form'
import { ReviewSupplementDialog } from './review-supplement-dialog'
import { isInteractive, reviewItems, ruleResults, isReviewStale, previousCompletedRun, acceptSubmittedReview } from './review-issues'
import { useEffect, useRef, useState } from 'react'
import type { SupplementMode } from './review-issue-presentation'
import { ReviewResultsList } from './review-results-list'
import { ReviewRuleCoverage } from './review-rule-coverage'
import { ReviewProgress } from './review-progress'
import { decisionLabels, summarizeReview } from './review-status'
import './review-flow.css'
import './review-results.css'
import './review-result-panel.css'
import { createReviewPoller } from './review-polling'
import { Button } from './components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from './components/ui/dialog'
import { toast } from 'sonner'
import { api, post, serverId, knownVersion, type ServerRun, type Finding, type Version, type ServerResult } from './backend-api'
import type { ReviewEditor } from './editors/contract-editor'

export function ServerReview({id,editor,position,finishRequest,onFinishConsumed,onSummary,onShowDocument,onRules,onRevisions}:{id:string;position?:string;editor:ReviewEditor;finishRequest:number;onFinishConsumed:()=>void;onSummary:(value:{total:number;pending:number;hasResult:boolean;active:boolean})=>void;onShowDocument:()=>void;onRules:()=>void;onRevisions?:()=>void}){
  const cid=serverId(id)
  const [run,setRun]=useState<ServerRun|null>(null),[version,setVersion]=useState<Version|null>(null)
  const [results,setResults]=useState<ServerResult[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState('')
  const [syncError,setSyncError]=useState('')
  const [submittingReview,setSubmittingReview]=useState(false)
  const liveEnabled=import.meta.env.VITE_LIVE_REVIEW!=='0'
  const [executionSyncError,setExecutionSyncError]=useState('')
  const [execution,setExecution]=useState<ExecutionState|null>(null)
  const [previousRun,setPreviousRun]=useState<ServerRun|null>(null),[supplement,setSupplement]=useState<{issue:Finding;mode:SupplementMode}|null>(null)
  const [historyOpen,setHistoryOpen]=useState(false),[feedbackOpen,setFeedbackOpen]=useState(false)
  const [finish,setFinish]=useState(false),[loaded,setLoaded]=useState(false)
  const requestKey=useRef<{version:string;key:string}|null>(null)
  const actionLock=useRef(false)
  const [opinion,setOpinion]=useState(''),[reservations,setReservations]=useState(''),[decision,setDecision]=useState<{finding:Finding;action:string}|null>(null),[note,setNote]=useState('')
  const submittedRunId=useRef<string|null>(null)
  const refresher=useRef<()=>Promise<void>>(async()=>{})
  const executionRefresh=useRef<()=>Promise<void>>(async()=>{})
  const refresh=()=>Promise.all([refresher.current(),executionRefresh.current()]).then(()=>undefined)
  useEffect(()=>{
    let disposed=false
    let cachedVersion:Version|null=null
    let discover=true
    let cachedRuns:ServerRun[]|null=null,cachedHistory:ServerResult[]=[],cachedPrevious:ServerRun|null=null
    const poller=createReviewPoller(async()=>{
      if(!cachedRuns||discover){
        discover=false;
        [cachedRuns,cachedHistory]=await Promise.all([api<ServerRun[]>(`/contracts/${cid}/reviews`),api<ServerResult[]>(`/contracts/${cid}/results`)])
      }
      const runs=cachedRuns

      const targetId=submittedRunId.current??runs[0]?.id
      const latest=targetId?await api<ServerRun>(`/runs/${targetId}`):null
      if(latest&&!['queued','running'].includes(latest.status)&&runs[0]?.status!==latest.status){
        [cachedRuns,cachedHistory]=await Promise.all([api<ServerRun[]>(`/contracts/${cid}/reviews`),api<ServerResult[]>(`/contracts/${cid}/results`)])
      }
      let previous:ServerRun|null=null
      if(latest&&['queued','running','failed'].includes(latest.status)){
        const older=previousCompletedRun(runs)??runs.find(r=>r.id===latest.parent_run_id)
        if(older){if(cachedPrevious?.id!==older.id)cachedPrevious=await api<ServerRun>(`/runs/${older.id}`);previous=cachedPrevious}
      }
      if(latest&&cachedVersion?.id!==latest.document_version_id)cachedVersion=await api<Version>(`/versions/${latest.document_version_id}`)
      if(disposed)return false
      if(submittedRunId.current&&latest?.id!==submittedRunId.current)return true
      submittedRunId.current=null
      setRun(latest);setPreviousRun(previous);setVersion(latest?cachedVersion:null);setResults(cachedHistory);setSyncError('');setLoaded(true)
      return latest?.status==='queued'||latest?.status==='running'
    },e=>{if(!disposed)setSyncError(e instanceof Error?e.message:String(e))})
    refresher.current=()=>{discover=true;return poller.refresh()}
    void poller.refresh()
    const resume=()=>{if(document.visibilityState==='visible')void refresh()}
    window.addEventListener('focus',resume);document.addEventListener('visibilitychange',resume)
    return()=>{disposed=true;poller.stop();window.removeEventListener('focus',resume);document.removeEventListener('visibilitychange',resume)}
  },[cid])
  useEffect(()=>{
    if(!run||!liveEnabled){setExecution(null);return}
    let disposed=false,source:EventSource|null=null,currentState:ExecutionState|null=null
    const rid=run.id
    const sync=createReviewPoller(async()=>{
      let value:ExecutionState|null=currentState
      let more=false
      if(currentState){
        const batch=await api<{events:ExecutionEvent[];seq:number;reset:boolean;status:string;stale:boolean}>(`/runs/${rid}/execution-events?after=${currentState.seq}`)
        value=currentState
        if(batch.reset)value=null
        else for(const event of batch.events){if(value)value=reduceExecution(value,event)}
        if(value&&batch.seq>=value.seq){more=value.seq<batch.seq;value={...value,stale:batch.stale,status:more?value.status:batch.status}}
      }
      if(!value)value=await api<ExecutionState>(`/runs/${rid}/execution-state`)
      if(disposed)return false
      setExecutionSyncError('')
      if(!currentState||value.seq>=currentState.seq){currentState=value;setExecution(value)}
      return more||value.status==='queued'||value.status==='running'
    },()=>{if(!disposed)setExecutionSyncError('任务明细同步暂时中断，正在保留最近状态。')})
    executionRefresh.current=sync.refresh
    void sync.refresh().then(()=>{
      if(disposed||!currentState||!['queued','running'].includes(currentState.status)||typeof EventSource==='undefined'||import.meta.env.VITE_REVIEW_SSE==='0')return
      source=new EventSource(`/api/v1/runs/${rid}/execution-stream?after=${currentState.seq}`)
      source.onmessage=e=>{
        if(disposed||!currentState)return
        try{const event=JSON.parse(e.data) as ExecutionEvent,next=reduceExecution(currentState,event)
          if(next){currentState=next;setExecution(next)}else{void sync.refresh();void refresh()}
          if(event.type.startsWith('run_'))source?.close()
        }catch{void sync.refresh()}
      }
      source.addEventListener('reset',()=>{source?.close();void sync.refresh()})
      source.onerror=()=>{source?.close();void sync.refresh()}
    })
    return()=>{disposed=true;source?.close();sync.stop();executionRefresh.current=async()=>{}}
  },[run?.id,liveEnabled])
  useEffect(()=>{if(finishRequest>0){setFinish(true);onFinishConsumed()}},[finishRequest])
  const perform=async(fn:()=>Promise<void>)=>{if(actionLock.current)return;actionLock.current=true;setBusy(true);setError('');try{await fn()}catch(e){setError(e instanceof Error?e.message:String(e))}finally{actionLock.current=false;setBusy(false)}}
  const waiting=run?.status==='queued'||run?.status==='running'
  const stale=isReviewStale(run,knownVersion(id))
  const live=execution?.run_id===run?.id?execution:null
  const liveIssues=live?Object.values(live.issues).sort((a,b)=>((a as Finding&{first_seq?:number}).first_seq??0)-((b as Finding&{first_seq?:number}).first_seq??0)):[]
  const displayRun=run&&waiting&&live?{...run,issues:liveIssues as typeof run.issues,findings:liveIssues}:run
  const items=reviewItems(displayRun)
  const rules=ruleResults(displayRun)
  const unsaved=!!run&&editor.ready&&['saving','error'].includes(editor.saveStatus)
  const {pending}=summarizeReview(displayRun)
  const locked=!!editor.readOnly||busy||stale||unsaved||waiting||!!syncError||editor.review.completed
  useEffect(()=>{onSummary({total:items.length,pending,hasResult:results.length>0,active:waiting})},[run,pending,results,onSummary])
  async function current(){if(!await editor.flushSave())throw new Error('请先保存正文');const info=await api<{current_document_version_id:string}>(`/contracts/${cid}`);if(info.current_document_version_id!==run?.document_version_id)throw new Error('正文已更新，请重新审查后处理或定稿。')}
  const locate=async(f:Finding,replace=false,index=0)=>{
    if(replace&&displayRun?.result_schema_version==='interactive-review-v3')throw new Error('请复制结构化建议，在正文中手工修订。')
    if(replace)await current()
    else {
      const [fresh,contract]=await Promise.all([api<ServerRun>(`/runs/${run!.id}`),api<{current_document_version_id:string}>(`/contracts/${cid}`)])
      if(fresh.stale||contract.current_document_version_id!==run?.document_version_id||editor.saveStatus!=='saved')throw new Error('正文或资料已变化，请保存并重新审查。')
    }
    const e=index===-1?f.event_anchor:f.evidence[index],block=version?.blocks.find(b=>b.id===e?.block_id)
    if(!e||!block)throw new Error('本项缺少可定位原文，请补充材料。')
    if([...block.text].slice(e.start,e.end).join('')!==e.quote)throw new Error('证据校验失败')
    onShowDocument()
    if(!replace&&editor.locateReviewTarget){await editor.locateReviewTarget({documentVersionId:run!.document_version_id,paragraph:block.text,quote:e.quote});return}
    if(!await editor.locateEvidence(block.text,e.quote,replace?f.suggested_text??undefined:undefined))return
    if(replace){await editor.flushSave();toast.success('建议已写入修订；正文已变化，定稿前请重新审查。')}
  }
  async function startReview(){
    setSubmittingReview(true)
    try{await enqueueReview()}finally{setSubmittingReview(false)}
  }
  async function enqueueReview(){
    if(editor.readOnly)throw new Error('当前为只读查看，无法发起审查。')
    if(!await editor.flushSave())throw new Error('正文保存失败，请先重试保存。')
    const info=await api<{current_document_version_id:string}>(`/contracts/${cid}`)
    const versionId=info.current_document_version_id
    if(!requestKey.current||requestKey.current.version!==versionId)requestKey.current={version:versionId,key:crypto.randomUUID()}
    try {
      const next=await post<ServerRun>(`/contracts/${cid}/reviews`,{document_version_id:versionId,idempotency_key:requestKey.current.key})
      if(run&&['completed','needs_input'].includes(run.status))setPreviousRun(run)
      submittedRunId.current=next.id;setRun(next);requestKey.current=null
    } finally {await refresh()}
  }
  const openDecision=(finding:Finding,action:string)=>{setDecision({finding,action});setNote('');setError('')}
  const canStart=loaded&&!waiting&&!editor.review.completed
  const startDisabled=!!editor.readOnly||busy||!!run&&!editor.ready
  const notices=<>
    {run&&(waiting||!!syncError)&&<ReviewProgress run={run} paused={!!syncError} compact={!!live&&Object.keys(live.tasks).length>0}/>}
    {waiting&&executionSyncError&&<p role="status" className="review-notice">{executionSyncError}</p>}
    {waiting&&live&&<ReviewExecutionPanel state={live} canLocate={editor.ready&&!stale&&!unsaved&&!live.stale&&!syncError&&!executionSyncError} onLocate={anchor=>void perform(()=>locate({event_anchor:anchor,evidence:[anchor]} as Finding,false,-1))}/>}
    {run&&!waiting&&!syncError&&(run.status==='failed'||hasIncompleteReview(run))&&<details className="result-failure-notice"><summary><strong>本轮审查未完成</strong><span>部分检查未完成 · 查看原因</span></summary><ReviewProgress run={run}/></details>}
    {(stale||unsaved)&&<ReviewVersionNotice disabled={startDisabled} onReview={canStart?()=>void perform(startReview):undefined} submitting={submittingReview}>{stale?'正文或资料已修改，以下为上一版本结果':'正文有待保存修改，请保存后重新审查'}</ReviewVersionNotice>}
    {error&&<p role="alert" className="form-error">{error}</p>}
    {syncError&&<div role="alert" className="review-notice"><strong>进度同步中断</strong><p>{syncError}</p><Button size="sm" variant="outline" onClick={()=>void refresh()}>刷新任务状态</Button></div>}
  </>
  return <div className="server-review review-flow results-workspace review-results-redesign">
    <div className="results-scroll">
    <ReviewPanelHeading position={position}>
        <DropdownMenu.Item onSelect={()=>setHistoryOpen(true)}>审查记录与范围</DropdownMenu.Item>
        <DropdownMenu.Item onSelect={onRules}>查看审查规则</DropdownMenu.Item>
        {onRevisions&&<DropdownMenu.Item onSelect={onRevisions}>修订与批注</DropdownMenu.Item>}
        {canStart&&<DropdownMenu.Item disabled={startDisabled} onSelect={()=>void perform(startReview)}>{submittingReview?'正在提交…':stale||unsaved?'保存并重审':run?'重新审查':'开始审查'}</DropdownMenu.Item>}
      </ReviewPanelHeading>
      {displayRun&&(rules.length>0||items.length>0||['completed','needs_input'].includes(displayRun.status))?<ReviewResultsList key={`${cid}:${displayRun.id}`} run={displayRun} version={version} cid={cid} locked={locked} ready={editor.ready} active={waiting} locateLocked={busy||stale||unsaved||!!syncError||!!live?.stale||!!executionSyncError} canApply={editor.capabilities.applyTrackedSuggestion} notice={notices} onLocate={(f,index,replace)=>void perform(()=>locate(f,replace,index))} onDecision={openDecision} onSupplement={(issue,mode)=>setSupplement({issue,mode})}/>:<div className="result-start-state">{notices}
        {!loaded&&!syncError&&<p role="status">正在恢复审查状态…</p>}
        {loaded&&!run&&<div className="result-empty"><FileClock/><strong>这份合同尚未发起审查</strong><p>启动后，审查进度与结果将显示在这里。</p>{canStart&&<Button disabled={startDisabled} onClick={()=>void perform(startReview)}>开始审查当前合同</Button>}</div>}
      </div>}
    {previousRun&&waiting&&<details className="review-notice"><summary>查看上一轮意见（仅供参考）</summary><p>上一轮版本 {previousRun.document_version_id.slice(0,8)}，不代表本轮结论。</p>{reviewItems(previousRun).filter(f=>['flag','insufficient_evidence'].includes(f.status)).map(f=><article key={f.id}><strong>{f.title??f.rule_id}</strong><p>{f.explanation}</p></article>)}</details>}
    </div>
    <ReviewPanelFooter disabled={!displayRun||locked} onSupplement={()=>setFeedbackOpen(true)} onHistory={()=>setHistoryOpen(true)}/>
    <Dialog open={feedbackOpen} onOpenChange={setFeedbackOpen}><DialogContent className="result-aux-dialog"><DialogHeader><DialogTitle>补充审查意见</DialogTitle><DialogDescription>记录人工发现的漏审问题，保留原文位置和反馈依据。</DialogDescription></DialogHeader>{displayRun&&<LegalFeedbackForm key={displayRun.id} run={displayRun} version={version} disabled={locked} initiallyOpen hideTrigger/>}</DialogContent></Dialog>
    <Dialog open={historyOpen} onOpenChange={setHistoryOpen}><DialogContent className="result-aux-dialog"><DialogHeader><DialogTitle>审查记录</DialogTitle><DialogDescription>查看本轮范围、版本与已保存的处理记录。</DialogDescription></DialogHeader>
      {displayRun?<><ReviewRuleCoverage run={displayRun}/><div className="review-version-details"><p>规则 {displayRun.rule_snapshot?.version??'历史版本未记录'} · 执行口径 {displayRun.review_prompt_version??'历史版本未记录'}</p><p>正文版本 {displayRun.document_version_id.slice(0,8)}{displayRun.material_bundle_id?` · 资料包 ${displayRun.material_bundle_id.slice(0,8)}`:''}</p></div><h3>本轮处理记录</h3>{displayRun.decisions?.length?displayRun.decisions.map((d,i)=><article className="review-decision-record" key={`${d.finding_id}:${i}`}><strong>{decisionLabels[d.action]??d.action} · {items.find(f=>f.id===d.finding_id)?.title??d.finding_id}</strong><p>{d.note}</p><small>{d.created_at?new Date(d.created_at).toLocaleString('zh-CN'):''}</small></article>):<p>暂无人工处理记录。</p>}</>:<p>暂无审查记录。</p>}
    {results.length>0&&<section className="review-summary"><h3>定稿结果与历史版本</h3>{results.map((r,i)=><article key={r.id}><strong>R{results.length-i} · {new Date(r.created_at).toLocaleString('zh-CN')}</strong><p>{r.opinion}</p><p>保留事项：{r.reservations}</p><a href={`/api/v1/versions/${r.document_version_id}/file`}>下载对应 DOCX</a><Button size="sm" variant="ghost" onClick={()=>{const blob=new Blob([JSON.stringify(r,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='审阅结果.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}}>下载结果记录</Button></article>)}{editor.review.completed&&<Button variant="outline" disabled={busy} onClick={()=>void perform(async()=>{if(await editor.reopen())toast.success('可继续编辑或发起新审查，历史定稿保留。')})}>重新开启审阅</Button>}</section>}
    </DialogContent></Dialog>
    {supplement&&run&&<ReviewSupplementDialog key={`${run.id}:${supplement.issue.id}`} cid={cid} run={run} issue={supplement.issue} initialMode={supplement.mode} onClose={()=>setSupplement(null)} onSubmitted={receipt=>acceptSubmittedReview(run,receipt,pending=>{submittedRunId.current=pending.id;setPreviousRun(run);setRun(pending);setSupplement(null);toast.success('补充资料已保存，正在重新核验')},refresh,setSyncError)}/>}
    <Dialog open={!!decision} onOpenChange={open=>{if(!open&&!busy)setDecision(null)}}><DialogContent><DialogHeader><DialogTitle>{decision?decisionLabels[decision.action]:'记录处理意见'}</DialogTitle><DialogDescription>{decision?.action==='needs_business_confirmation'?'记录待确认事项。该项仍保持待处理，确认前不能定稿。':'记录核对依据和处理结论，不会自动修改合同或覆盖 AI 原判断。'}</DialogDescription></DialogHeader><textarea aria-label="处理意见" rows={4} value={note} onChange={e=>setNote(e.target.value)}/><Button disabled={locked||!note.trim()} onClick={()=>void perform(async()=>{await current();await post(`/runs/${run!.id}/${isInteractive(run)?'issues':'findings'}/${decision!.finding.id}/decisions`,{action:decision!.action,note,actor:'法务审阅员'});setDecision(null);await refresh()})}>保存处理意见</Button></DialogContent></Dialog>
    <Dialog open={finish} onOpenChange={open=>{if(!busy)setFinish(open)}}><DialogContent><DialogHeader><DialogTitle>完成审阅</DialogTitle><DialogDescription>保存当前文档版本、审查发现与人工处理记录。</DialogDescription></DialogHeader><p>{!run?'请先发起审查。':stale||unsaved?'正文已变化，请保存并重新审查。':waiting?'审查尚未完成。':`还有 ${pending} 项待处理。`}</p><label>最终意见<textarea aria-label="最终意见" rows={3} value={opinion} onChange={e=>setOpinion(e.target.value)}/></label><label>保留事项<textarea aria-label="保留事项" rows={3} value={reservations} onChange={e=>setReservations(e.target.value)}/></label><Button disabled={editor.readOnly||busy||!run||waiting||stale||unsaved||!!syncError||pending>0||run?.status==='failed'||!!run&&hasIncompleteReview(run)||!opinion.trim()||!reservations.trim()} onClick={()=>void perform(async()=>{await current();if(editor.prepareFinalize&&!await editor.prepareFinalize())throw new Error('定稿前保存未确认');try{await post(`/runs/${run!.id}/results`,{opinion,reservations,reviewer:'法务审阅员',editor_session_id:editor.finalizeSessionId?.()})}catch(e){await editor.cancelFinalize?.();throw e}editor.freeze();setFinish(false);await refresh();toast.success('定稿已保存至服务端')})}>保存定稿</Button>{error&&<p role="alert">{error}</p>}</DialogContent></Dialog>
  </div>
}
