import {AuthEventSource} from './auth-events'
import {CONFIGURED_REVIEW_POLICY,isVerifiedLiveIssue,showReviewResults} from './review-process'
import {prepareReviewNavigation} from './prepare-review-navigation'
import {reviewNavigationTarget} from './review-navigation-target'
import {ProposalActionsProvider} from './proposal-actions'
import { ReviewAgentPanel } from './review-agent-panel'
import {useResultScroll} from './use-result-scroll'
import {evidenceFeedback} from './review-evidence-feedback'
import {evidenceLabel} from './review-card-content'
import type {ReviewEvidenceContext} from './editors/contract-editor'
import { ReviewReadingIssues } from './review-reading-issues'
import {ReviewMatterPanel} from './review-matter-panel'
import {buildReviewMatters,selectMatter,type ReviewMatter} from './review-matters'
import { useReviewReference } from './use-review-reference'
import { followTargets, anchorKey, type FollowTarget } from './review-follow'
import { ReviewExecutionPanel } from './review-execution-panel'
import { reduceExecution, type ExecutionState, type ExecutionEvent } from './review-execution'
import { hasIncompleteReview } from './review-issues'
import { FileClock } from 'lucide-react'
import { ReviewPanelActions, ReviewVersionNotice } from './review-panel-chrome'
import { DropdownMenu } from 'radix-ui'
import { AttachmentIssue } from './attachment-issue'
import { ReviewSupplementDialog } from './review-supplement-dialog'
import { isInteractive, reviewItems, ruleResults, isReviewStale, previousCompletedRun, acceptSubmittedReview, isCurrentReviewCompletion } from './review-issues'
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { SupplementMode } from './review-issue-presentation'
import { ReviewResultsList } from './review-results-list'
import { ReviewProgress } from './review-progress'
import {needsReview, decisionLabels, summarizeReview } from './review-status'
import './review-flow.css'
import './review-results.css'
import './review-result-panel.css'
import './review-stream.css'
import './review-card.css'
import { createReviewPoller } from './review-polling'
import { Button } from './components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from './components/ui/dialog'
import { toast } from 'sonner'
import { api, post, serverId, knownVersion, type ServerRun, type Finding, type Version, type ServerResult } from './backend-api'
import type { ReviewEditor } from './editors/contract-editor'

export function ServerReview({id,editor,actionsHost,onRunChange,onSummary,onShowDocument,onRules}:{id:string;editor:ReviewEditor;actionsHost:HTMLElement|null;onRunChange?:(id:string|undefined)=>void;onSummary:(value:{total:number;pending:number;hasResult:boolean;active:boolean})=>void;onShowDocument:()=>void;onRules:()=>void}){
  const cid=serverId(id)
  const [run,setRun]=useState<ServerRun|null>(null),[version,setVersion]=useState<Version|null>(null)
  const [results,setResults]=useState<ServerResult[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState('')
  const [syncError,setSyncError]=useState('')
  const [submittingReview,setSubmittingReview]=useState(false)
  const liveEnabled=import.meta.env.VITE_LIVE_REVIEW!=='0'
  const [executionSyncError,setExecutionSyncError]=useState('')
  const [execution,setExecution]=useState<ExecutionState|null>(null)
  const [previousRun,setPreviousRun]=useState<ServerRun|null>(null),[supplement,setSupplement]=useState<{issue:Finding;mode:SupplementMode}|null>(null)
  const [finish,setFinish]=useState(false),[loaded,setLoaded]=useState(false)
  const [opinion,setOpinion]=useState(''),[reservations,setReservations]=useState('')
  const requestKey=useRef<{version:string;key:string}|null>(null)
  const actionLock=useRef(false)
  const [decision,setDecision]=useState<{finding:Finding;action:string}|null>(null),[note,setNote]=useState('')
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
      const versionId=latest?.document_version_id
      if(versionId&&cachedVersion?.id!==versionId)cachedVersion=await api<Version>(`/versions/${versionId}`)
      if(disposed)return false
      if(submittedRunId.current&&latest?.id!==submittedRunId.current)return true
      submittedRunId.current=null
      setRun(latest);setPreviousRun(previous);setVersion(versionId?cachedVersion:null);setResults(cachedHistory);setSyncError('');setLoaded(true)
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
    let disposed=false,source:AuthEventSource|null=null,currentState:ExecutionState|null=null
    let reconnectTimer:ReturnType<typeof setTimeout>|undefined,reconnectDelay=1000
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
      if(!['queued','running'].includes(value.status))source?.close()
      return more||value.status==='queued'||value.status==='running'
    },()=>{if(!disposed)setExecutionSyncError('任务明细同步暂时中断，正在保留最近状态。')})
    executionRefresh.current=sync.refresh
    const connect=()=>{
      if(disposed||!currentState||!['queued','running'].includes(currentState.status)||import.meta.env.VITE_REVIEW_SSE==='0')return
      clearTimeout(reconnectTimer);source?.close()
      source=new AuthEventSource(`/api/v1/runs/${rid}/execution-stream?after=${currentState.seq}`)
      source.onopen=()=>{reconnectDelay=1000}
      source.onmessage=e=>{
        if(disposed||!currentState)return
        try{const event=JSON.parse(e.data) as ExecutionEvent,next=reduceExecution(currentState,event)
          if(next){currentState=next;setExecution(next)}else{void sync.refresh();void refresh()}
          if(event.type.startsWith('run_'))source?.close()
        }catch{void sync.refresh()}
      }
      source.addEventListener('reset',()=>{source?.close();currentState=null;void sync.refresh().then(connect)})
      // Some failures leave native EventSource CLOSED, so retry explicitly from
      // the latest durable cursor while polling continues to deliver results.
      source.onerror=()=>{source?.close();void sync.refresh();clearTimeout(reconnectTimer);reconnectTimer=setTimeout(()=>{void sync.refresh().then(connect)},reconnectDelay);reconnectDelay=Math.min(10000,reconnectDelay*2)}
    }
    void sync.refresh().then(connect)
    return()=>{disposed=true;clearTimeout(reconnectTimer);source?.close();sync.stop();executionRefresh.current=async()=>{}}
  },[run?.id,liveEnabled])
  useEffect(()=>{onRunChange?.(run?.id)},[run?.id,onRunChange])
  const perform=async(fn:()=>Promise<void>)=>{if(actionLock.current)return;actionLock.current=true;setBusy(true);setError('');try{await fn()}catch(e){setError(e instanceof Error?e.message:String(e))}finally{actionLock.current=false;setBusy(false)}}
  const waiting=run?.status==='queued'||run?.status==='running'
  const stale=isReviewStale(run,knownVersion(id))
  const contextStale=!!run?.context_stale
  const live=execution?.run_id===run?.id&&!(run?.status==='queued'&&execution?.status!=='queued')?execution:null
  const configured=run?.review_prompt_version===CONFIGURED_REVIEW_POLICY
  const liveIssues=useMemo(()=>live?Object.values(live.issues).filter(issue=>!configured||isVerifiedLiveIssue(issue)).sort((a,b)=>((a as Finding&{first_seq?:number}).first_seq??0)-((b as Finding&{first_seq?:number}).first_seq??0)):[],[configured,live?.issues])
  const displayRun=run&&waiting&&live?{...run,stale,issues:liveIssues as typeof run.issues,findings:liveIssues}:run
  const draftIssues=useMemo(()=>waiting&&live?Object.values(live.drafts??{}).filter(d=>!live.issues[d.issue.id]).map(d=>({...d.issue,first_seq:d.first_seq})):[],[waiting,live?.drafts,live?.issues])
  const panelIssues=useMemo(()=>[...liveIssues,...draftIssues].sort((a,b)=>((a as Finding&{first_seq?:number}).first_seq??0)-((b as Finding&{first_seq?:number}).first_seq??0)),[liveIssues,draftIssues])
  const panelRun=displayRun&&waiting&&live?{...displayRun,issues:panelIssues,findings:panelIssues,revision_proposals:Object.values(live.proposals??{})}:displayRun
  const analysisActive=Object.values(live?.phases??{}).some(p=>['transaction','discovery','synthesis'].includes(p.id)&&p.state==='running')
  const overviewStreaming=['generating','validating'].includes(live?.artifacts?.['transaction-overview']?.state??'')
  const followSelector=configured?'.agent-current':analysisActive?'.review-agent-panel':waiting?'.stream-card.stream-generating, .stream-card.stream-validating':undefined
  const resultScope=run?`${run.id}:${run.recovery_count??0}`:undefined
  const [surfaceChoice,setSurfaceChoice]=useState<{scope:string;surface:'process'|'results'}>()
  const [automaticResults,setAutomaticResults]=useState<string>()
  const [watchedRun,setWatchedRun]=useState<string>()
  const resultScroll=useResultScroll(`${cid}:${resultScope??''}`,waiting,live?.seq??0,followSelector)
  const terminalResults=run?.status==='completed'||run?.status==='needs_input'
  const canViewResults=terminalResults||liveIssues.length>0||(run?.status==='failed'&&!!run.findings.length)
  const confirmedRisk=liveIssues.some(issue=>issue.status==='flag')
  const manualSurface=surfaceChoice?.scope===resultScope?surfaceChoice?.surface:undefined
  const resultsVisible=configured&&canViewResults&&(manualSurface?manualSurface==='results':
    automaticResults===resultScope||(terminalResults&&watchedRun!==resultScope))
  function selectSurface(surface:'process'|'results'){
    if(resultScope)setSurfaceChoice({scope:resultScope,surface})
  }
  useLayoutEffect(()=>{
    if(!configured||!resultScope)return
    if(waiting&&watchedRun!==resultScope)setWatchedRun(resultScope)
    if(!canViewResults||manualSurface||resultsVisible||(!confirmedRisk&&overviewStreaming)||!resultScroll.following.current)return
    if(resultScroll.ref.current?.contains(document.activeElement))return
    if(window.getSelection()?.isCollapsed===false)return
    setAutomaticResults(resultScope)
  },[configured,resultScope,waiting,watchedRun,canViewResults,manualSurface,resultsVisible,confirmedRisk,overviewStreaming,live?.seq])
  const items=reviewItems(displayRun)
  const matters=buildReviewMatters(live,items)
  const matterScope=run&&live?.attempt_id?`${run.id}:${run.document_version_id}:${live.attempt_id}`:undefined
  const rememberedMatter=useMemo(()=>{if(!matterScope)return undefined;try{return sessionStorage.getItem('review-matter:1:'+matterScope)??undefined}catch{return undefined}},[matterScope])
  const [matterChoice,setMatterChoice]=useState<{scope?:string;id:string}|null>(null)
  const chosenMatter=matterChoice?.scope===matterScope?matterChoice?.id:rememberedMatter
  const [readingTarget,setReadingTarget]=useState<FollowTarget>()
  useEffect(()=>{setReadingTarget(undefined)},[run?.id,run?.document_version_id])
  const [activeEvidenceKey,setActiveEvidenceKey]=useState<string>(),[evidenceStatus,setEvidenceStatus]=useState('')
  const manualFinding=useRef<string|undefined>(undefined)
  useEffect(()=>{setActiveEvidenceKey(undefined);setEvidenceStatus('');manualFinding.current=undefined},[run?.id,run?.document_version_id])
  const rules=ruleResults(displayRun)
  const unsaved=!!run&&editor.ready&&['saving','error'].includes(editor.saveStatus)
  const {pending,handled}=summarizeReview(displayRun)
  const locked=!!editor.readOnly||busy||contextStale||unsaved||waiting||!!syncError
  useEffect(()=>{onSummary({total:pending+handled,pending,hasResult:results.length>0,active:waiting})},[run,pending,handled,results,onSummary])
  const completion=results.find(result=>(result.run_id??result.review_snapshot?.id)===run?.id);
  useEffect(()=>{editor.setReviewCompleted?.(isCurrentReviewCompletion(completion,run,knownVersion(id)))},[completion,run?.id,run?.status]);
  async function current(){if(!await editor.flushSave())throw new Error('请先保存正文');const info=await api<{current_document_version_id:string}>(`/contracts/${cid}`);if(info.current_document_version_id!==knownVersion(id))throw new Error('正文已有新版本，请重新加载正文后继续。')}
  const locate=async(f:Finding,replace=false,index=0,valid:()=>boolean=()=>true,reveal:'never'|'if-needed'|'center'='center',related:Finding['evidence']=[],context?:ReviewEvidenceContext):Promise<boolean>=>{
    if(replace&&displayRun?.result_schema_version==='interactive-review-v3')throw new Error('请复制结构化建议，在正文中手工修订。')
    let navigationVersion=version
    if(replace){await current();if(knownVersion(id)!==run?.document_version_id)throw new Error('正文已更新，请核对当前原文后手工修订。')}
    else {
      if(!await prepareReviewNavigation(editor,valid,setEvidenceStatus))return false
      const contract=await api<{current_document_version_id:string}>(`/contracts/${cid}`)
      if(contract.current_document_version_id!==knownVersion(id))throw new Error('正文已有新版本，请重新加载正文后定位。')
      if(contract.current_document_version_id!==version?.id)navigationVersion=await api<Version>(`/versions/${contract.current_document_version_id}`)
    }
    const e=index===-1?f.event_anchor:f.evidence[index],block=version?.blocks.find(b=>b.id===e?.block_id)
    if(!e||!block)throw new Error('本项缺少可定位原文，请补充材料。')
    const navigationTarget=reviewNavigationTarget(e,version!,navigationVersion!)
    if(!valid())return false
    if(reveal!=='never')onShowDocument()
    // Explicit references use the editor's real text selection, as in a word
    // processor. Keep background updates from selecting or moving the document.
    if(!replace&&editor.capabilities.nativeReferenceSelection&&editor.locateReviewTarget){
      if(reveal==='never')return false
      const ok=await editor.locateReviewTarget(navigationTarget)
      if(!valid())return false
      setActiveEvidenceKey(ok?anchorKey(e):undefined)
      setEvidenceStatus(ok?navigationTarget.navigationNotice??'':'原文定位未完成，请重新点击原文引用。')
      if(ok&&navigationTarget.navigationNotice)toast.info(navigationTarget.navigationNotice)
      return ok
    }
    if(!replace&&editor.presentReviewEvidence){
      const others=related.filter(r=>anchorKey(r)!==anchorKey(e)).flatMap(r=>{
        try{return [reviewNavigationTarget(r,version!,navigationVersion!)]}catch{return []}
      }).slice(0,7)
      const result=await editor.presentReviewEvidence({current:navigationTarget,related:others,reveal,context:context??{phase:'context',title:f.title||'核对原文证据'}})
      if(!valid())return false
      const ok=result.ok&&(reveal==='never'||result.visible)
      if(reveal!=='never'){setActiveEvidenceKey(ok?anchorKey(e):undefined);setEvidenceStatus(ok?navigationTarget.navigationNotice??evidenceFeedback(result,reveal):evidenceFeedback(result,reveal))}
      if(!ok&&result.status!=='interrupted')throw new Error(evidenceFeedback(result,reveal))
      return ok
    }
    if(reveal==='never')return false
    if(!replace&&editor.locateReviewTarget){
      const ok=await editor.locateReviewTarget(navigationTarget)
      if(valid()&&ok){setEvidenceStatus(navigationTarget.navigationNotice??'');if(navigationTarget.navigationNotice)toast.info(navigationTarget.navigationNotice)}
      return ok
    }
    if(!await editor.locateEvidence(replace?block.text:navigationTarget.paragraph,replace?e.quote:navigationTarget.quote,replace?f.suggested_text??undefined:undefined))return false
    if(replace){await editor.flushSave();toast.success('建议已写入修订。')}
    else if(valid()){setActiveEvidenceKey(anchorKey(e));setEvidenceStatus(navigationTarget.navigationNotice??'');if(navigationTarget.navigationNotice)toast.info(navigationTarget.navigationNotice)}
    return true
  }
  const followBlocked=!editor.ready?'正文尚未就绪':undefined
  const readingUnit=live?.plan?.units.find(u=>u.id===readingTarget?.unitId)
  const activeMatter=selectMatter(matters,chosenMatter,readingUnit?.block_ids??(readingTarget?[readingTarget.anchor.block_id]:[]))
  useEffect(()=>{if(activeMatter&&matterScope){setMatterChoice({scope:matterScope,id:activeMatter.id});try{sessionStorage.setItem('review-matter:1:'+matterScope,activeMatter.id)}catch{/* Optional opaque focus memory. */}}},[activeMatter?.id,matterScope])
  const reference=useReviewReference({scope:run?`${run.id}:${run.document_version_id}:${live?.attempt_id??'pending'}:${live?.plan?.revision??1}`:undefined,
    locations:[...followTargets(live),...matters.map(m=>({anchor:m.anchor,title:m.title})),...items.flatMap(f=>[...(f.event_anchor?[f.event_anchor]:[]),...f.evidence].map(anchor=>({anchor,title:f.title||f.rule_id})))],
    locate:(target,valid)=>locate({title:target.title,event_anchor:target.anchor,evidence:[target.anchor]} as Finding,false,-1,valid,'center',target.related??activeMatter?.evidence),
    pause:()=>{},cancel:editor.cancelReviewNavigation,subscribe:editor.subscribeDocumentInteraction,blocked:followBlocked})
  useEffect(()=>{
    if(reference.visit?.phase==='error'){setActiveEvidenceKey(undefined);setEvidenceStatus(reference.visit.message||'原文定位未完成，请重新点击原文引用。');toast.error(reference.visit.message||'原文定位未完成，请重新点击原文引用。')}
    else if(reference.visit?.phase==='paused'){setActiveEvidenceKey(undefined);setEvidenceStatus('')}
  },[reference.visit?.phase,reference.visit?.message])
  useEffect(()=>{if(followBlocked){setActiveEvidenceKey(undefined);setEvidenceStatus('')}},[followBlocked])
  const openEvidence=(anchor:Finding['event_anchor'],title:string)=>{
    if(!anchor){toast.error('本项没有可定位的原文引用。');return}
    const origin=reference.visit?.origin??(activeMatter?{anchor:activeMatter.anchor,title:activeMatter.title}:readingTarget)
    if(reference.visit&&origin&&anchorKey(origin.anchor)===anchorKey(anchor))void reference.back()
    else void reference.open(origin??{anchor,title},{anchor,title,related:activeMatter?.evidence})
  }
  const manualLocate=(f:Finding,index:number,replace=false)=>{
    if(!replace){
      const anchor=index===-1?f.event_anchor:f.evidence[index],primary=f.event_anchor??f.evidence[0]
      if(!anchor||!primary){toast.error('本项没有可定位的原文引用。');return}
      if(manualFinding.current!==f.id){reference.clear();manualFinding.current=f.id}
      const title=f.title||f.rule_id,related=[...(f.event_anchor?[f.event_anchor]:[]),...f.evidence].filter((e,i,all)=>all.findIndex(other=>anchorKey(other)===anchorKey(e))===i)
      setEvidenceStatus('正在定位所选原文…');setActiveEvidenceKey(undefined)
      void reference.open({anchor:primary,title,related},{anchor,title,related})
      return
    }
    reference.clear();void perform(async()=>{await locate(f,replace,index)})
  }
  const selectReadingTarget=async(target:FollowTarget)=>{
    reference.clear();manualFinding.current=undefined
    if(await reference.open(target,target))setReadingTarget(target)
  }
  const selectCurrentMatter=(matter:ReviewMatter)=>{
    setMatterChoice({scope:matterScope,id:matter.id})
    const unit=live?.plan?.units.find(u=>u.block_ids.includes(matter.anchor.block_id))
    void selectReadingTarget({key:anchorKey(matter.anchor),anchor:matter.anchor,title:matter.title,unitId:unit?.id})
  }
  useEffect(()=>{if(followBlocked)editor.clearReviewEvidence?.()},[followBlocked])
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
  const canComplete=!!run&&['needs_input','completed'].includes(run.status)&&!contextStale&&!syncError&&editor.ready&&!editor.readOnly&&!editor.busy
  async function completeRound(){
    if(!run||!canComplete)return
    const saved=editor.prepareSnapshot ? await editor.prepareSnapshot() : await editor.flushSave()
    if(!saved)throw new Error('正文保存未确认，请重试。')
    try {
      const result=await post<ServerResult>(`/runs/${run.id}/results`,{
        opinion,reservations,editor_session_id:editor.snapshotSessionId?.(),expected_document_version_id:knownVersion(id),
      })
      setResults(previous=>[result,...previous.filter(item=>item.id!==result.id)])
      setFinish(false)
      toast.success('本轮审阅已标记完成')
    } finally {
      if(editor.prepareSnapshot)await editor.releaseSnapshot?.()
    }
    await refresh()
  }
  const openDecision=(finding:Finding,action:string)=>{setDecision({finding,action});setNote('');setError('')}
  const canStart=loaded&&!waiting
  const startDisabled=!!editor.readOnly||busy||!editor.ready
  const commonNotices=<>
    {evidenceStatus&&<p role="status" className="evidence-location-status">{evidenceStatus}</p>}
    {waiting&&stale&&<ReviewVersionNotice>本轮仍在审查提交时的正文。当前已保存新版本，请核对相关意见的原文位置。</ReviewVersionNotice>}
    {waiting&&executionSyncError&&<p role="status" className="review-notice">{executionSyncError}</p>}
    {run&&!waiting&&!syncError&&(run.status==='failed'||hasIncompleteReview(run))&&<details className="result-failure-notice"><summary>查看执行详情</summary><ReviewProgress run={run} compact={!!Object.keys(live?.phases??{}).length}/>{run.review_prompt_version&&<Button disabled={busy||waiting||unsaved||!!run.stale||!!editor.readOnly} onClick={()=>void perform(async()=>{const next=await post<ServerRun>(`/runs/${run.id}/resume`,{});submittedRunId.current=next.id;setRun(next);await refresh()})}>重试审查</Button>}</details>}
    {(contextStale||unsaved)&&<ReviewVersionNotice>{contextStale?'审查资料或主体已修改，请重新审查。':'正文有待保存修改，请先保存。'}</ReviewVersionNotice>}
    {error&&<p role="alert" className="form-error">{error}</p>}
    {syncError&&<div role="alert" className="review-notice"><strong>进度同步中断</strong><p>{syncError}</p><Button size="sm" variant="outline" onClick={()=>void refresh()}>刷新任务状态</Button></div>}
  </>
  const processFallback=(!live||(!Object.keys(live.phases??{}).length&&!Object.keys(live.artifacts??{}).length))&&run&&(waiting||syncError)&&<ReviewProgress run={run} paused={!!syncError}/>
  const resultProgress=live?.phases?.drafting?.state==='running'&&live.phases.rules?.state!=='running'
    ?'正在生成修改建议':'审查继续进行'
  const matterPanel=<>
    {run&&liveEnabled&&displayRun&&!!activeMatter&&<ReviewMatterPanel matters={matters} current={activeMatter} visit={reference.visit} disabled={false} onSelect={selectCurrentMatter} onReturn={()=>void reference.back()} onRetry={()=>void reference.retry()}>
      {activeMatter&&<ReviewReadingIssues key={`${run.id}:${live?.attempt_id}:${activeMatter.id}`} matter issues={activeMatter.issues.filter(needsReview)} run={displayRun} version={version} cid={cid} blockIds={[activeMatter.anchor.block_id]} disabled={false} locked={locked} onEvidence={openEvidence} onDecision={openDecision} onInteract={()=>{}}/>}
    </ReviewMatterPanel>}
  </>
  const processPanel=live&&(Object.keys(live.phases??{}).length>0||Object.keys(live.artifacts??{}).length>0)
    ? <ReviewAgentPanel policyVersion={CONFIGURED_REVIEW_POLICY} key={resultScope} state={{...live,status:run?.status??live.status}}
      run={run??undefined} sources={{version,cid,bundleId:run?.material_bundle_id}} disabled={!editor.ready}
      executionDetails={Object.keys(live.tasks).length>0&&<ReviewExecutionPanel state={live} canLocate={editor.ready} onLocate={anchor=>manualLocate({event_anchor:anchor,evidence:[anchor]} as Finding,-1)}/>}
      onLocate={anchor=>manualLocate({id:anchorKey(anchor),title:evidenceLabel(version,anchor),event_anchor:anchor,evidence:[anchor]} as Finding,-1)}/>
    : processFallback
  const uncheckedAttachments = isInteractive(run) && !waiting
    ? reviewItems(run).filter(f => f.rule_id === 'RL-04' && f.status === 'insufficient_evidence'
      && f.review_state !== 'merged' && f.review_state !== 'retracted' && (f.attachment_name || f.reference_name))
    : []
  const attachmentChecks = run && uncheckedAttachments.length > 0 && <details className="review-process-detail">
    <summary>待核验附件（{uncheckedAttachments.length}）</summary>
    {uncheckedAttachments.map(issue => <section key={issue.id}>
      <h4>{issue.attachment_name || issue.reference_name}</h4>
      <p>{issue.explanation}</p>
      <AttachmentIssue runId={run.id} issue={issue} disabled={locked} onSupplement={mode => setSupplement({issue, mode})}/>
    </section>)}
  </details>
  const legacyNotices=<>
    {live&&<ReviewAgentPanel policyVersion={run?.review_prompt_version} key={`${live.run_id}:${live.attempt_id}`} state={{...live,status:waiting?'running':run?.status??live.status}}
      run={run??undefined} sources={{version,cid,bundleId:run?.material_bundle_id}} disabled={!editor.ready}
      onLocate={anchor=>manualLocate({id:anchorKey(anchor),title:evidenceLabel(version,anchor),event_anchor:anchor,evidence:[anchor]} as Finding,-1)}/>}
    {run&&!Object.keys(live?.phases??{}).length&&(syncError||(waiting&&!Object.keys(live?.artifacts??{}).length))&&<ReviewProgress run={run} paused={!!syncError} compact={!!live&&Object.keys(live.tasks).length>0}/>}
    {commonNotices}{matterPanel}{attachmentChecks}
    {waiting&&live&&<details className="stream-task-details"><summary>核查任务与执行情况</summary><ReviewExecutionPanel state={live} canLocate={true} onLocate={anchor=>manualLocate({event_anchor:anchor,evidence:[anchor]} as Finding,-1)}/></details>}
  </>
  const canRenderList=showReviewResults(waiting,live,run?.review_prompt_version)&&displayRun&&(rules.length>0||items.length>0||draftIssues.length>0||terminalResults)
  const renderList=(primary:boolean)=>canRenderList&&<ReviewResultsList key={`${cid}:${displayRun.id}`} run={panelRun!}
    drafts={waiting?live?.drafts:undefined} version={version} cid={cid} locked={locked} ready={editor.ready} active={waiting}
    locateLocked={false} canApply={false} compactStream={primary} notice={primary?undefined:legacyNotices}
    activeEvidenceKey={activeEvidenceKey} focusedBlockId={readingTarget?.anchor.block_id}
    onLocate={(f,index,replace)=>manualLocate(f,index,replace)} onDecision={openDecision} onSupplement={(issue,mode)=>setSupplement({issue,mode})}/>
  const previousReview=previousRun&&waiting&&<details className="review-notice"><summary>查看上一轮意见</summary>
    <p>上一轮版本 {previousRun.document_version_id.slice(0,8)}</p>
    {reviewItems(previousRun).filter(needsReview).map(f=><article key={f.id}><strong>{f.title??f.rule_id}</strong><p>{f.explanation}</p></article>)}
  </details>
  const proposalBlockedReason=editor.readOnly?'当前为只读查看，请在可编辑会话中操作':!editor.ready?'文档正在加载':waiting?'审查正在进行':unsaved?'正文有未确认修改，请先保存':syncError?'文档同步失败，请重试保存':busy?'正在处理文档，请稍候':''
  return <ProposalActionsProvider editor={editor} runId={displayRun?.id} runStatus={displayRun?.status} blocked={!!proposalBlockedReason} blockedReason={proposalBlockedReason} refresh={refresh}><div className="server-review review-flow results-workspace review-results-redesign">
    <ReviewPanelActions host={actionsHost}>
        <DropdownMenu.Item onSelect={onRules}>查看审查规则</DropdownMenu.Item>
        {!completion&&run&&['completed','needs_input'].includes(run.status)&&<DropdownMenu.Item disabled={!canComplete||busy} onSelect={()=>{setOpinion('');setReservations('');setError('');setFinish(true)}}>标记本轮审阅完成</DropdownMenu.Item>}
        {completion&&<DropdownMenu.Item onSelect={()=>setFinish(true)}>查看历史审阅记录</DropdownMenu.Item>}
        {canStart&&!unsaved&&<DropdownMenu.Item disabled={startDisabled} onSelect={()=>void perform(startReview)}>{submittingReview?'正在提交…':run?'重新审查':'开始审查'}</DropdownMenu.Item>}
      </ReviewPanelActions>
    {configured ? <>
      <nav className="review-surface-switch" aria-label="审查视图">
        <button type="button" aria-pressed={!resultsVisible} onClick={()=>selectSurface('process')}>审查过程</button>
        <button type="button" aria-pressed={resultsVisible} disabled={!canViewResults} onClick={()=>selectSurface('results')}>审查结果{liveIssues.length>0&&waiting&&<small>{liveIssues.length}</small>}</button>
        {resultsVisible&&waiting&&<span role="status">{resultProgress}</span>}
      </nav>
      <div className="review-surface-notices">{commonNotices}</div>
      <div className="results-scroll review-process-surface" ref={resultScroll.ref} hidden={resultsVisible}>
        {processPanel}{attachmentChecks}
        {!!activeMatter&&<details className="review-process-detail"><summary>按原文核查</summary>{matterPanel}</details>}
        {previousReview}
      </div>
      {canViewResults&&<div className="results-scroll review-result-surface" hidden={!resultsVisible}>
        {reference.visit&&<div className="review-reference-return"><button type="button" onClick={()=>void reference.back()}>返回事项原文</button>
          {['error','paused'].includes(reference.visit.phase)&&<button type="button" onClick={()=>void reference.retry()}>重新定位证据</button>}
        </div>}
        {renderList(true)}
      </div>}
    </> : <>
      <div className="results-scroll" ref={resultScroll.ref}>
        {canRenderList?renderList(false):<div className="result-start-state">{legacyNotices}
          {!loaded&&!syncError&&<p role="status">正在恢复审查状态…</p>}
          {loaded&&!run&&<div className="result-empty"><FileClock/><strong>这份合同尚未发起审查</strong><p>启动后，审查进度与结果将显示在这里。</p>{canStart&&<Button disabled={startDisabled} onClick={()=>void perform(startReview)}>开始审查当前合同</Button>}</div>}
        </div>}
        {previousReview}
      </div>
      {resultScroll.unseen&&<button className="stream-new-content" onClick={resultScroll.resume}>有新内容 · 回到最新位置 ↓</button>}
    </>}
    {supplement&&run&&<ReviewSupplementDialog key={`${run.id}:${supplement.issue.id}`} cid={cid} run={run} issue={supplement.issue} initialMode={supplement.mode} onClose={()=>setSupplement(null)} onSubmitted={receipt=>acceptSubmittedReview(run,receipt,pending=>{submittedRunId.current=pending.id;setPreviousRun(run);setRun(pending);setSupplement(null);toast.success('补充资料已保存，正在重新核验')},refresh,setSyncError)}/>}
    <Dialog open={!!decision} onOpenChange={open=>{if(!open&&!busy)setDecision(null)}}><DialogContent><DialogHeader><DialogTitle>{decision?decisionLabels[decision.action]:'记录处理意见'}</DialogTitle><DialogDescription>{decision?.action==='needs_business_confirmation'?'记录待确认事项。该项仍保持待处理，后续可继续补充确认。':'记录核对依据和处理结论，不会自动修改合同或覆盖 AI 原判断。'}</DialogDescription></DialogHeader><textarea aria-label="处理意见" rows={4} value={note} onChange={e=>setNote(e.target.value)}/><Button disabled={locked||!note.trim()} onClick={()=>void perform(async()=>{await current();await post(`/runs/${run!.id}/${isInteractive(run)?'issues':'findings'}/${decision!.finding.id}/decisions`,{action:decision!.action,note});setDecision(null);await refresh()})}>保存处理意见</Button></DialogContent></Dialog>
    <Dialog open={finish} onOpenChange={open=>{if(!busy)setFinish(open)}}><DialogContent><DialogHeader><DialogTitle>{completion?'历史审阅记录':'标记本轮审阅完成'}</DialogTitle><DialogDescription>{completion?'本轮已保存的人工记录':`将保存当前正文版本和处理意见。尚有 ${pending} 项待处理。`}</DialogDescription></DialogHeader>{completion?<>{completion.reviewer&&<p>记录人：{completion.reviewer}</p>}<p>记录时间：{new Date(completion.created_at).toLocaleString()}</p>{completion.opinion&&<p>审阅意见：{completion.opinion}</p>}{completion.reservations&&<p>保留事项：{completion.reservations}</p>}</>:<>
      <label>审阅意见（选填）<textarea value={opinion} maxLength={10000} onChange={e=>setOpinion(e.target.value)}/></label>
      <label>保留事项（选填）<textarea value={reservations} maxLength={10000} onChange={e=>setReservations(e.target.value)}/></label>
      {error&&<p role="alert">{error}</p>}
      <Button disabled={!canComplete||busy} onClick={()=>void perform(completeRound)}>确认完成</Button>
    </>}</DialogContent></Dialog>
  </div></ProposalActionsProvider>
}
