import {downloadAuthenticated} from '../auth-http'
import {useCallback,useEffect,useRef,useState} from 'react'
import {toast} from 'sonner'
import {api,post,serverId,setKnownVersion,knownVersion,type Version,type ServerResult,type ServerRun} from '../backend-api'
import {initialState,type ReviewState} from '../review-state'
import {isCurrentReviewCompletion} from '../review-issues'
import {startWordLoad} from '../word-load-metrics'
import {loadDocs,bridge,type DocsInstance} from './onlyoffice-client'
import {createReviewReadonly} from './review-readonly'
import {requireNavigationReceipt} from './navigation-error'
import {recoverProposal,inspectProposalFailure,type RecoverableProposal} from './proposal-recovery'
import type {Snapshot,ReviewTarget,ReviewPresentation,ReviewEvidenceContext,ProposalMode,ProposalOperation} from './contract-editor'
type Session={id:string;state:string;read_only_reason:'occupied'|null;head_version_id:string;document_key:string;script_url:string;build_id:string;config:Record<string,any>}
type Recovery={session_id:string|null;can_recover:boolean;candidates:{id:string;created_at:string;download_url:string}[]}
type Receipt={id:string;state:string;document_version_id?:string;sha256?:string;error_code?:number}
export function useOnlyoffice(documentId:string,enabled:boolean){
 const host=useRef<HTMLDivElement>(null),toolbar=useRef<HTMLDivElement>(null),instance=useRef<DocsInstance|null>(null)
 const session=useRef<Session|null>(null),wire=useRef<ReturnType<typeof bridge>|null>(null),dirty=useRef(false),epoch=useRef(0),saving=useRef<Promise<boolean>|null>(null),closed=useRef(false),snapshot=useRef<Snapshot|null>(null)
 const [ready,setReady]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[saveStatus,setSaveStatus]=useState<'loading'|'saving'|'saved'|'error'>('loading'),[review,setReview]=useState<ReviewState>(initialState),[loadStage,setStage]=useState('正在连接文档服务…'),[file,setFile]=useState({name:'正在加载合同.docx',isDemo:false,edited:false})
 const [loadAttempt,setLoadAttempt]=useState(0)
 const [documentVisible,setDocumentVisible]=useState(false),[slow,setSlow]=useState(false),[needsInput,setNeedsInput]=useState(false)
 const [readOnlyReason,setReadOnlyReason]=useState<Session['read_only_reason']>(null)
 const [recovery,setRecovery]=useState<Recovery|null>(null)
 const proposalBusy=useRef(false)
 const [proposalCapable,setProposalCapable]=useState(false)
 const reviewReadonly=useRef(false),boundVersion=useRef<string|undefined>(undefined),navigationEpoch=useRef(0)
 const modeQueue=useRef<ReturnType<typeof createReviewReadonly>|null>(null)
 const setReviewReadonly=useCallback((locked:boolean)=>{
   if(!modeQueue.current)modeQueue.current=createReviewReadonly(async value=>{
     if(saving.current)await saving.current
     const w=wire.current
     if(!w)throw Error('正文尚未就绪')
     // Never unlock an occupied or closed editor session.
     if(session.current?.state==='view'||closed.current){reviewReadonly.current=value&&session.current?.state==='view';return}
     await w.send('mode',{mode:value?'viewing':'suggesting'})
     reviewReadonly.current=value
   })
   return modeQueue.current(locked)
 },[])
 const interactionListeners=useRef(new Set<()=>void>())
 const subscribeDocumentInteraction=useCallback((listener:()=>void)=>{interactionListeners.current.add(listener);return()=>{interactionListeners.current.delete(listener)}},[])
 const notifyInteraction=()=>interactionListeners.current.forEach(listener=>listener())
 const storageKey='rixin-oo:'+documentId,dirtyKey=storageKey+':dirty'
 const save=async(reason='review',keepFrozen=false)=>{
   if(session.current?.state==='view')return reason==='snapshot'?false:!!snapshot.current
   if(saving.current)return saving.current
   if(!session.current||!wire.current||closed.current)return reason!=='snapshot'&&!dirty.current&&!!snapshot.current
   const work=async()=>{
     const s=session.current!;const w=wire.current!;const e=epoch.current;setBusy(true)
     try{
       await w.send('freeze')
       if(!dirty.current&&snapshot.current){if(!keepFrozen)await w.send('unfreeze');return true}
       setSaveStatus('saving')
       let r=await post<Receipt>(`/editor-sessions/${s.id}/save-requests`,{idempotency_key:crypto.randomUUID(),expected_head_version_id:s.head_version_id,purpose:reason})
       const until=Date.now()+65000
       while(r.state==='pending'&&Date.now()<until){await new Promise(x=>setTimeout(x,350));r=await api<Receipt>(`/editor-sessions/${s.id}/save-requests/${r.id}`)}
       if(r.state!=='committed'||!r.document_version_id||!r.sha256)throw Error(r.state==='unconfirmed'?'文档保存尚未确认，请重试；当前修改仍保留在编辑器中。':'文档保存失败或超时，请重试。')
       snapshot.current={documentVersionId:r.document_version_id,sha256:r.sha256,saveRequestId:r.id};s.head_version_id=r.document_version_id;setKnownVersion(documentId,r.document_version_id)
       if(e===epoch.current){dirty.current=false;sessionStorage.removeItem(dirtyKey);setSaveStatus('saved')}else{setSaveStatus('saving');throw Error('保存期间正文发生变化，请再次保存')}
       if(!keepFrozen)await w.send('unfreeze');return true
     }catch(err){setSaveStatus('error');toast.error(String(err instanceof Error?err.message:err));await w.send('unfreeze').catch(()=>{});return false}
     finally{setBusy(false)}
   }
   saving.current=work();try{return await saving.current}finally{saving.current=null}
 }
 const saveRef=useRef(save);saveRef.current=save
 useEffect(()=>{
   if(!enabled)return
   let disposed=false,failed=false,documentReadyHandled=false;const trace=startWordLoad(documentId);let heartbeat:ReturnType<typeof setInterval>|undefined,autosave:ReturnType<typeof setInterval>|undefined
   let slowTimer:ReturnType<typeof setTimeout>,deadline:ReturnType<typeof setTimeout>
   const stopped=()=>disposed||failed
   const clearLoadTimers=()=>{clearTimeout(slowTimer);clearTimeout(deadline)}
   const fail=(error:unknown)=>{if(stopped())return;failed=true;clearLoadTimers();setReady(false);setNeedsInput(false);setSlow(false);setError(error instanceof Error?error.message:String(error));trace.finish('error')}
   const watchLoad=(timeout=45000)=>{clearLoadTimers();slowTimer=setTimeout(()=>{if(!stopped())setSlow(true)},8000);deadline=setTimeout(()=>fail(new Error('正文准备超时，请重新加载；若仍失败，请检查文档服务连接。')),timeout)}
   session.current=null;snapshot.current=null;closed.current=false;setRecovery(null);setProposalCapable(false);setReadOnlyReason(null);setSaveStatus('loading');
   setReady(false);setDocumentVisible(false);setError('');setSlow(false);setNeedsInput(false);setStage('正在连接文档服务…');watchLoad()
   void(async()=>{
     await Promise.resolve();if(stopped())return
     const cid=serverId(documentId)
     const state=await api<{document_version_id:string;draft_state:{review?:ReviewState}|null;results:ServerResult[]}>(`/contracts/${cid}/editor-state`)
     if(stopped())return
     const [v,runs]=await Promise.all([api<Version&{sha256:string}>(`/versions/${state.document_version_id}`),api<ServerRun[]>(`/contracts/${cid}/reviews`)])
     if(stopped())return
     const next=state.draft_state?.review??initialState();next.completed=isCurrentReviewCompletion(state.results[0],runs[0]??null,v.id,next.reopenedAt)
     setReview(next);setFile({name:v.filename,isDemo:false,edited:false});setKnownVersion(documentId,v.id)
     snapshot.current={documentVersionId:v.id,sha256:v.sha256,saveRequestId:'initial'}
     let request: {expected_version_id:string;client_instance_id:string;idempotency_key:string}
     try{request=JSON.parse(sessionStorage.getItem(storageKey)||'null')}catch{request=null as never}
     if(!request){sessionStorage.removeItem(dirtyKey);request={expected_version_id:v.id,client_instance_id:crypto.randomUUID(),idempotency_key:crypto.randomUUID()};sessionStorage.setItem(storageKey,JSON.stringify(request))}
     let s:Session
     try{s=await post<Session>(`/contracts/${cid}/editor-sessions`,request)}catch(err){
       if(stopped())return
       sessionStorage.removeItem(storageKey)
       if(!(err instanceof Error)||!err.message.includes('会话已关闭'))throw err
       sessionStorage.removeItem(dirtyKey)
       request={expected_version_id:v.id,client_instance_id:crypto.randomUUID(),idempotency_key:crypto.randomUUID()}
       sessionStorage.setItem(storageKey,JSON.stringify(request));s=await post<Session>(`/contracts/${cid}/editor-sessions`,request)
     }
     if(stopped())return
     if(s.head_version_id!==v.id){
       const head=await api<Version&{sha256:string}>(`/versions/${s.head_version_id}`)
       snapshot.current={documentVersionId:head.id,sha256:head.sha256,saveRequestId:'resumed'};setKnownVersion(documentId,head.id)
     }
     if(stopped())return
     session.current=s;setReadOnlyReason(s.read_only_reason);closed.current=false;dirty.current=s.state==='open'&&sessionStorage.getItem(dirtyKey)==='1';trace.mark('session.config');setStage('正在打开正文并排版…');await loadDocs(s.script_url);if(stopped()||!host.current)return
     trace.mark('api.loaded');const mount=document.createElement('div');mount.id='oo-'+crypto.randomUUID();host.current.replaceChildren(mount)
     const w=bridge(host.current,new URL(s.script_url).origin,s.document_key);wire.current=w
     const config={...s.config,events:{
       onAppReady:()=>{if(!stopped()){trace.mark('app.ready');setStage('正在打开正文…')}},
       onUserActionRequired:()=>{if(!stopped()){clearLoadTimers();setNeedsInput(true);setSlow(false);setStage('请在文档窗口完成打开操作')}},
       onDocumentReady:async()=>{
         if(stopped()||documentReadyHandled)return
         documentReadyHandled=true;setNeedsInput(false);setDocumentVisible(true);setStage('正在准备审阅功能…');trace.mark('document.visible');watchLoad(25000)
         try{
           const hello=await w.send('hello')
           if(stopped())return
           if(hello.build!==s.build_id)throw Error('编辑器资源版本不匹配')
           if(hello.navigationVersion<28||!hello.structuredAnchors||!hello.evidencePresentation)throw Error('编辑器导航资源已更新，请强制刷新页面（⌘⇧R / Ctrl+Shift+R）后重试')
           setProposalCapable(hello.applyTrackedSuggestion===true)
           // Native content is visible already; unlock interaction only after the
           // bridge and the required editing restriction have been confirmed.
           if(s.state==='open')await w.send('mode',{mode:'suggesting'})
           if(stopped())return
           clearLoadTimers();setSlow(false);setReady(true);setSaveStatus(dirty.current?'saving':'saved');trace.finish('ready')
           // Cosmetic preferences must not delay content or poison readiness.
           // Bound their queue occupancy so saving/navigation can proceed.
           void w.send('disableSpellcheck',{},1500).catch(()=>{if(!stopped())toast.warning('拼写提示未能关闭，可在编辑器中手动设置。')})
           if(s.state==='open')void w.send('review',{},1500).catch(()=>{if(!stopped())toast.warning('请点击编辑器上方“审阅”页签打开审阅工具。')})
         }catch(e){fail(e)}
       },
       onDocumentStateChange:(event:{data:boolean})=>{if(disposed||closed.current||s.state==='view')return;if(event.data){notifyInteraction();epoch.current++;boundVersion.current=undefined;dirty.current=true;sessionStorage.setItem(dirtyKey,'1');setSaveStatus('saving');setFile(f=>({...f,edited:true}))}},
       onDownloadAs:(event:{data:{url:string}})=>{try{const url=new URL(event.data.url);if(url.origin!==new URL(s.script_url).origin)throw Error('备份地址与文档服务不一致');const a=document.createElement('a');a.href=url.href;a.download='未入库备份-'+v.filename;a.click();toast.info('此下载仅为备份，不代表正文已保存至业务版本库')}catch(e){toast.error(String(e))}},
       onError:(event:{data:{errorDescription?:string}})=>{if(!disposed){setDocumentVisible(false);fail(new Error(event.data.errorDescription||'文档服务发生错误'))}},
     }}
     instance.current=new window.DocsAPI!.DocEditor(mount.id,config)
     heartbeat=setInterval(()=>void post(`/editor-sessions/${s.id}/heartbeat`,{}).catch(()=>{if(!stopped())setSaveStatus('error')}),30000)
     autosave=setInterval(()=>{if(dirty.current&&!saving.current&&!proposalBusy.current)void saveRef.current('autosave')},30000)
   })().catch(fail)
   const interaction=(e:MessageEvent)=>{if(e.source===host.current?.querySelector('iframe')?.contentWindow&&e.origin===new URL(session.current?.script_url||location.href).origin&&e.data?.channel==='rixin-editor-v1'&&e.data?.documentKey===session.current?.document_key&&e.data?.event==='user_scroll')notifyInteraction()}
   window.addEventListener('message',interaction)
   const warn=(e:BeforeUnloadEvent)=>{if(dirty.current)e.preventDefault()};window.addEventListener('beforeunload',warn)
   return()=>{disposed=true;clearLoadTimers();window.removeEventListener('message',interaction);clearInterval(heartbeat);clearInterval(autosave);window.removeEventListener('beforeunload',warn);wire.current?.dispose();wire.current=null;boundVersion.current=undefined;modeQueue.current=null;reviewReadonly.current=false;instance.current?.destroyEditor();instance.current=null;setReady(false);trace.finish('cancelled')}
 },[documentId,enabled,loadAttempt])
 const assertProposalWritable=()=>{
   if(!ready||!wire.current||!session.current||session.current.state!=='open'||closed.current||reviewReadonly.current||!proposalCapable)throw Error('当前正文不可应用建议')
   if(proposalBusy.current)throw Error('请等待当前修改完成')
 }
 const confirmProposal=async(operationId:string):Promise<ProposalOperation>=>{
   assertProposalWritable();proposalBusy.current=true;setBusy(true)
   try{
     return await recoverProposal({
       confirm:()=>post<ProposalOperation>(`/proposal-operations/${operationId}/confirm`,{session_id:session.current!.id,allow_cancel:false}),
       load:()=>api<RecoverableProposal>(`/proposal-operations/${operationId}`),
       inspect:op=>wire.current!.send('inspectProposal',{id:op.id,bookmark:op.bookmark}),
       state:()=>wire.current!.send('state'),
       cancel:op=>post<ProposalOperation>(`/proposal-operations/${op.id}/cancel`,{session_id:session.current!.id,expected_version_id:session.current!.head_version_id,editor_result:'absent'}),
       markClean:()=>{dirty.current=false;sessionStorage.removeItem(dirtyKey);setSaveStatus('saved')},
       saveAndConfirm:async()=>{
         dirty.current=true;sessionStorage.setItem(dirtyKey,'1')
         if(!await save('review'))throw Error('修改仍保留在正文中，请重试保存确认')
         return await post<ProposalOperation>(`/proposal-operations/${operationId}/confirm`,{session_id:session.current!.id,save_request_id:snapshot.current?.saveRequestId==='resumed'?'':snapshot.current?.saveRequestId})
       },
     })
   }finally{proposalBusy.current=false;setBusy(false)}
 }
 const applyProposal=async(runId:string,proposalId:string,mode:ProposalMode,manualReplacement?:string):Promise<ProposalOperation>=>{
   assertProposalWritable()
   if(dirty.current||saving.current)throw Error('正文存在未确认修改，请先保存')
   proposalBusy.current=true;setBusy(true)
   try{
     const op=await post<any>(`/runs/${runId}/proposals/${encodeURIComponent(proposalId)}/operations`,{session_id:session.current!.id,expected_version_id:session.current!.head_version_id,mode,idempotency_key:crypto.randomUUID(),manual_replacement:manualReplacement})
     let result
     try{result=await wire.current!.send('applyProposal',op)}catch{
       // This is a read-only inspection, never a replay of a possibly applied edit.
       const cancelled=await inspectProposalFailure({
         inspect:()=>wire.current!.send('inspectProposal',{id:op.id,bookmark:op.bookmark}),
         cancel:()=>post<ProposalOperation>(`/proposal-operations/${op.id}/cancel`,{session_id:session.current!.id,expected_version_id:session.current!.head_version_id,editor_result:'absent'}),
       })
       if(cancelled)return cancelled
       result={status:'uncertain'}
     }
     if(result.status==='rejected'){
       await post(`/proposal-operations/${op.id}/cancel`,{session_id:session.current!.id,expected_version_id:session.current!.head_version_id,editor_result:'rejected'})
       throw Error(result.reason||'原文无法安全修改')
     }
     // Native state events can arrive after the command receipt. Force the save
     // barrier even when the event has not reached the host yet.
     dirty.current=true;boundVersion.current=undefined;sessionStorage.setItem(dirtyKey,'1');setSaveStatus('saving')
     if(!await save('review'))throw Error('修改已发送，保存尚未确认；请重试保存确认，不要重复应用')
     const confirmed=await post<ProposalOperation>(`/proposal-operations/${op.id}/confirm`,{session_id:session.current!.id,save_request_id:snapshot.current!.saveRequestId})
     return confirmed
   }finally{proposalBusy.current=false;setBusy(false)}
 }
 const undoProposal=async(op:ProposalOperation)=>{
   assertProposalWritable();proposalBusy.current=true;setBusy(true)
   try{
     if(!await save('review',true))throw Error('撤销前保存未确认')
     const restored=await post<{reverted_version_id:string}>(`/proposal-operations/${op.id}/undo`,{session_id:session.current!.id,expected_version_id:session.current!.head_version_id})
     closed.current=true
     dirty.current=false
     snapshot.current=null
     boundVersion.current=undefined
     navigationEpoch.current++
     sessionStorage.removeItem(storageKey)
     sessionStorage.removeItem(dirtyKey)
     setKnownVersion(documentId,restored.reverted_version_id)
     setReady(false)
     setSaveStatus('loading')
     setLoadAttempt(n=>n+1)
   }catch(error){await wire.current?.send('unfreeze').catch(()=>{});throw error}
   finally{proposalBusy.current=false;setBusy(false)}
 }
 const close=async()=>{if(!ready&&!dirty.current){const s=session.current;if(s){await post(`/editor-sessions/${s.id}/close`,{document_version_id:s.head_version_id});closed.current=true;sessionStorage.removeItem(storageKey)}return true}if(!await save('leave',true))return false;const s=session.current;if(!s)return false;try{await post(`/editor-sessions/${s.id}/close`,{document_version_id:s.head_version_id});closed.current=true;sessionStorage.removeItem(storageKey);return true}catch(e){await wire.current?.send('unfreeze').catch(()=>{});toast.error(String(e));return false}}
 return {engine:'onlyoffice' as const,host,toolbar,instance,ready,documentVisible,slow,needsInput,busy,error,loadStage,saveStatus,readOnlyReason,readOnly:readOnlyReason!==null,pages:0,review,setReview,file,capabilities:{locateEvidence:true,applyTrackedSuggestion:proposalCapable,nativeReferenceSelection:true},
  reload:async()=>{if(saving.current)await saving.current;if(dirty.current&&!await save())return;setReady(false);setLoadAttempt(n=>n+1)},
  applyProposal,confirmProposal,undoProposal,
  setReviewReadonly,canAutomaticallyLocate:()=>!dirty.current&&!saving.current&&!closed.current,
  subscribeDocumentInteraction,flushSave:()=>save(),close,prepareSnapshot:async()=>{if(proposalBusy.current)return false;if(saving.current)await saving.current;return save('snapshot',true)},snapshotSessionId:()=>session.current?.id,releaseSnapshot:async()=>{await wire.current?.send('unfreeze')},
  recovery,checkRecovery:async()=>{try{setRecovery(await api<Recovery>(`/contracts/${serverId(documentId)}/editor-recovery`))}catch(e){toast.error(String(e))}},recoverSession:async()=>{if(!recovery?.session_id)return;try{await post(`/editor-sessions/${recovery.session_id}/recover`,{document_version_id:knownVersion(documentId)});sessionStorage.removeItem(storageKey);sessionStorage.removeItem(dirtyKey);window.location.reload()}catch(e){toast.error(String(e))}},
  captureExportSnapshot:async()=>{if(proposalBusy.current)throw Error('请等待当前修订操作保存完成');if(saving.current)await saving.current;if(!await save('export',true)||!snapshot.current)throw Error('文档保存尚未确认，请重试');return {...snapshot.current}},
  retrySave:()=>void save(),exportBackup:()=>instance.current?.downloadAs('docx'),
  cancelReviewNavigation:()=>{navigationEpoch.current++;void wire.current?.send('cancelNavigation').catch(()=>{})},
  clearReviewEvidence:()=>{void wire.current?.send('clearEvidence').catch(()=>{})},
  updateReviewEvidenceContext:(blockId:string,context:ReviewEvidenceContext)=>{if(!dirty.current&&snapshot.current)void wire.current?.send('evidenceContext',{version:snapshot.current.documentVersionId,blockId,context}).catch(()=>{})},
  presentReviewEvidence:async({current:target,related=[],reveal,context}:ReviewPresentation)=>{
    const failed={ok:false,visible:false,moved:false},n=navigationEpoch.current,e=epoch.current
    if(!ready||dirty.current||saving.current||snapshot.current?.documentVersionId!==target.documentVersionId)return failed
    try{
      if(related.some(t=>t.documentVersionId!==target.documentVersionId))return failed
      if(boundVersion.current!==target.documentVersionId){
        const mapped=await wire.current?.send('bindAnchors',{version:target.documentVersionId,blocks:target.blocks})
        if(mapped?.status!=='bound')return {...failed,status:mapped?.status,reason:mapped?.reason}
        boundVersion.current=target.documentVersionId
      }
      if(n!==navigationEpoch.current||e!==epoch.current||dirty.current)return failed
      const result=await wire.current?.send('presentEvidence',{reveal,context,targets:[target,...related].slice(0,8).map(t=>({version:t.documentVersionId,blockId:t.blockId,paragraph:t.paragraph,quote:t.quote,start:t.start,end:t.end}))})
      if(n!==navigationEpoch.current||e!==epoch.current||dirty.current||snapshot.current?.documentVersionId!==target.documentVersionId)return failed
      return {ok:result?.status==='presented',visible:!!result?.visible,moved:!!result?.moved,status:result?.status,reason:result?.reason,geometry:result?.geometry}
    }catch(error){return {...failed,status:'error',reason:error instanceof Error?error.message:'编辑器未响应'}}
  },
  locateReviewTarget:async(target:ReviewTarget)=>{
    if(!ready)throw Error('正文尚未加载完成，请稍后重新定位。')
    if(dirty.current||saving.current||snapshot.current?.documentVersionId!==target.documentVersionId)throw Error('正文已变化或保存尚未确认，请保存后重新定位。')
    const e=epoch.current,n=navigationEpoch.current
    try{
      if(boundVersion.current!==target.documentVersionId){
        const mapped=await wire.current?.send('bindAnchors',{version:target.documentVersionId,blocks:target.blocks.map(({id,text})=>({id,text})),allowPartial:true})
        requireNavigationReceipt(mapped,'bind')
        boundVersion.current=target.documentVersionId
      }
      if(n!==navigationEpoch.current)return false
      if(dirty.current||e!==epoch.current)throw Error('定位期间正文发生变化，请保存后重新定位。')
      const result=await wire.current?.send('locate',{version:target.documentVersionId,blockId:target.blockId,start:target.start,end:target.end,paragraph:target.paragraph,quote:target.quote});
      if(n!==navigationEpoch.current)return false
      if(dirty.current||e!==epoch.current||snapshot.current?.documentVersionId!==target.documentVersionId)throw Error('定位期间正文发生变化，请保存后重新定位。')
      if(result?.status==='located'&&result.centered===false&&!result.boundary&&!result.interrupted)toast.info('已定位原文；当前编辑器无法自动居中')
      requireNavigationReceipt(result,'locate')
      return true
    }catch(error){if(n!==navigationEpoch.current)return false;boundVersion.current=undefined;throw error}
  },
  locateEvidence:async(paragraph:string,quote:string,replacement?:string)=>{if(replacement!==undefined){toast.error('请复制建议，在正文中以修订方式修改');return false}try{const result=await wire.current?.send('locate',{paragraph,quote});if(result?.status!=='located')throw Error(result?.status==='ambiguous'?'原文存在重复，无法唯一定位，请使用编辑器查找核对。':'原文已变化或无法定位，请在正文中查找并核对。');return true}catch(e){toast.error(String(e instanceof Error?e.message:e));return false}},
  exportDocx:async()=>{if(!await save('export'))return;const vid=knownVersion(documentId);await downloadAuthenticated(`/api/v1/versions/${vid}/file`,file.name)},
  openNativeReview:()=>wire.current?.send('review').catch(e=>toast.error(String(e))),openNativeComments:()=>wire.current?.send('comments').catch(e=>toast.error(String(e))),
  setReviewCompleted:(completed:boolean)=>setReview(r=>r.completed===completed?r:{...r,completed}),
 }
}
