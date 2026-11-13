import {useEffect,useRef,useState} from 'react'
import {toast} from 'sonner'
import {api,post,serverId,setKnownVersion,knownVersion,type Version,type ServerResult,type ServerRun} from '../backend-api'
import {initialState,type ReviewState} from '../review-state'
import {isCurrentFinalization} from '../review-issues'
import {startWordLoad} from '../word-load-metrics'
import {loadDocs,bridge,type DocsInstance} from './onlyoffice-client'
import type {Snapshot} from './contract-editor'
type Session={id:string;state:string;read_only_reason:'occupied'|'finalized'|null;head_version_id:string;document_key:string;script_url:string;build_id:string;config:Record<string,any>}
type Recovery={session_id:string|null;can_recover:boolean;candidates:{id:string;created_at:string;download_url:string}[]}
type Receipt={id:string;state:string;document_version_id?:string;sha256?:string;error_code?:number}
export function useOnlyoffice(documentId:string,enabled:boolean){
 const host=useRef<HTMLDivElement>(null),toolbar=useRef<HTMLDivElement>(null),instance=useRef<DocsInstance|null>(null)
 const session=useRef<Session|null>(null),wire=useRef<ReturnType<typeof bridge>|null>(null),dirty=useRef(false),epoch=useRef(0),saving=useRef<Promise<boolean>|null>(null),closed=useRef(false),snapshot=useRef<Snapshot|null>(null)
 const [ready,setReady]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState(''),[saveStatus,setSaveStatus]=useState<'loading'|'saving'|'saved'|'error'>('loading'),[review,setReview]=useState<ReviewState>(initialState),[loadStage,setStage]=useState('正在连接文档服务…'),[file,setFile]=useState({name:'正在加载合同.docx',isDemo:false,edited:false})
 const [readOnlyReason,setReadOnlyReason]=useState<Session['read_only_reason']>(null)
 const [recovery,setRecovery]=useState<Recovery|null>(null)
 const storageKey='rixin-oo:'+documentId,dirtyKey=storageKey+':dirty'
 const save=async(reason='review',keepFrozen=false)=>{
   if(session.current?.state==='view')return reason==='finalize'?false:!!snapshot.current
   if(saving.current)return saving.current
   if(!session.current||!wire.current||closed.current)return !dirty.current&&!!snapshot.current
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
   let disposed=false;const trace=startWordLoad(documentId);let heartbeat:ReturnType<typeof setInterval>|undefined,autosave:ReturnType<typeof setInterval>|undefined
   void(async()=>{
     await Promise.resolve();if(disposed)return
     const cid=serverId(documentId)
     const state=await api<{document_version_id:string;draft_state:{review?:ReviewState}|null;results:ServerResult[]}>(`/contracts/${cid}/editor-state`)
     const [v,runs]=await Promise.all([api<Version&{sha256:string}>(`/versions/${state.document_version_id}`),api<ServerRun[]>(`/contracts/${cid}/reviews`)])
     const next=state.draft_state?.review??initialState();next.completed=isCurrentFinalization(state.results[0],runs[0]??null,v.id,next.reopenedAt)
     setReview(next);setFile({name:v.filename,isDemo:false,edited:false});setKnownVersion(documentId,v.id)
     snapshot.current={documentVersionId:v.id,sha256:v.sha256,saveRequestId:'initial'}
     let request: {expected_version_id:string;client_instance_id:string;idempotency_key:string}
     try{request=JSON.parse(sessionStorage.getItem(storageKey)||'null')}catch{request=null as never}
     if(!request){sessionStorage.removeItem(dirtyKey);request={expected_version_id:v.id,client_instance_id:crypto.randomUUID(),idempotency_key:crypto.randomUUID()};sessionStorage.setItem(storageKey,JSON.stringify(request))}
     let s:Session
     try{s=await post<Session>(`/contracts/${cid}/editor-sessions`,request)}catch(err){
       sessionStorage.removeItem(storageKey)
       if(!(err instanceof Error)||!err.message.includes('会话已关闭'))throw err
       sessionStorage.removeItem(dirtyKey)
       request={expected_version_id:v.id,client_instance_id:crypto.randomUUID(),idempotency_key:crypto.randomUUID()}
       sessionStorage.setItem(storageKey,JSON.stringify(request));s=await post<Session>(`/contracts/${cid}/editor-sessions`,request)
     }
     if(disposed)return
     if(s.head_version_id!==v.id){
       const head=await api<Version&{sha256:string}>(`/versions/${s.head_version_id}`)
       snapshot.current={documentVersionId:head.id,sha256:head.sha256,saveRequestId:'resumed'};setKnownVersion(documentId,head.id)
     }
     if(disposed)return
     session.current=s;setReadOnlyReason(s.read_only_reason);closed.current=false;dirty.current=s.state==='open'&&sessionStorage.getItem(dirtyKey)==='1';trace.mark('session.config');setStage('正在打开正文并排版…');await loadDocs(s.script_url);if(disposed||!host.current)return
     trace.mark('api.loaded');const mount=document.createElement('div');mount.id='oo-'+crypto.randomUUID();host.current.replaceChildren(mount)
     const w=bridge(host.current,new URL(s.script_url).origin,s.document_key);wire.current=w
     const config={...s.config,events:{
       onDocumentReady:async()=>{if(disposed)return;try{const hello=await w.send('hello');if(hello.build!==s.build_id)throw Error('编辑器资源版本不匹配');setReady(true);setSaveStatus(dirty.current?'saving':'saved');trace.finish('ready')}catch(e){setError(String(e));trace.finish('error')}},
       onDocumentStateChange:(event:{data:boolean})=>{if(disposed||s.state==='view')return;if(event.data){epoch.current++;dirty.current=true;sessionStorage.setItem(dirtyKey,'1');setSaveStatus('saving');setFile(f=>({...f,edited:true}))}},
       onDownloadAs:(event:{data:{url:string}})=>{try{const url=new URL(event.data.url);if(url.origin!==new URL(s.script_url).origin)throw Error('备份地址与文档服务不一致');const a=document.createElement('a');a.href=url.href;a.download='未入库备份-'+v.filename;a.click();toast.info('此下载仅为备份，不代表正文已保存至业务版本库')}catch(e){toast.error(String(e))}},
       onError:(event:{data:{errorDescription?:string}})=>{if(!disposed){setError(event.data.errorDescription||'文档服务发生错误');setSaveStatus('error')}},
     }}
     instance.current=new window.DocsAPI!.DocEditor(mount.id,config)
     heartbeat=setInterval(()=>void post(`/editor-sessions/${s.id}/heartbeat`,{}).catch(()=>{if(!disposed)setSaveStatus('error')}),30000)
     autosave=setInterval(()=>{if(dirty.current&&!saving.current)void saveRef.current('autosave')},30000)
   })().catch(e=>{if(!disposed){setError(String(e instanceof Error?e.message:e));trace.finish('error')}})
   const warn=(e:BeforeUnloadEvent)=>{if(dirty.current)e.preventDefault()};window.addEventListener('beforeunload',warn)
   return()=>{disposed=true;clearInterval(heartbeat);clearInterval(autosave);window.removeEventListener('beforeunload',warn);wire.current?.dispose();wire.current=null;instance.current?.destroyEditor();instance.current=null;setReady(false);trace.finish('cancelled')}
 },[documentId,enabled])
 const close=async()=>{if(!await save('leave',true))return false;const s=session.current;if(!s)return false;try{await post(`/editor-sessions/${s.id}/close`,{document_version_id:s.head_version_id});closed.current=true;sessionStorage.removeItem(storageKey);return true}catch(e){await wire.current?.send('unfreeze').catch(()=>{});toast.error(String(e));return false}}
 return {engine:'onlyoffice' as const,host,toolbar,instance,ready,busy,error,loadStage,saveStatus,readOnlyReason,readOnly:readOnlyReason!==null,pages:0,review,setReview,file,capabilities:{locateEvidence:true,applyTrackedSuggestion:false},
  flushSave:()=>save(),close,prepareFinalize:()=>save('finalize',true),finalizeSessionId:()=>session.current?.id,cancelFinalize:async()=>{await wire.current?.send('unfreeze')},
  recovery,checkRecovery:async()=>{try{setRecovery(await api<Recovery>(`/contracts/${serverId(documentId)}/editor-recovery`))}catch(e){toast.error(String(e))}},recoverSession:async()=>{if(!recovery?.session_id)return;try{await post(`/editor-sessions/${recovery.session_id}/recover`,{document_version_id:knownVersion(documentId)});sessionStorage.removeItem(storageKey);sessionStorage.removeItem(dirtyKey);window.location.reload()}catch(e){toast.error(String(e))}},
  retrySave:()=>void save(),exportBackup:()=>instance.current?.downloadAs('docx'),
  locateReviewTarget:async(target:{documentVersionId:string;paragraph:string;quote:string})=>{
    if(!ready||dirty.current||saving.current||snapshot.current?.documentVersionId!==target.documentVersionId){toast.error('正文已变化或保存尚未确认，请保存并重新审查');return false}
    const e=epoch.current
    try{const result=await wire.current?.send('locate',{paragraph:target.paragraph,quote:target.quote});
      if(dirty.current||e!==epoch.current||snapshot.current?.documentVersionId!==target.documentVersionId)throw Error('定位期间正文发生变化，请重新审查')
      if(result?.status!=='located')throw Error(result?.status==='ambiguous'?'原文存在重复，无法唯一定位，请手动核对。':'原文已变化或无法定位，请核对。')
      return true
    }catch(error){toast.error(String(error instanceof Error?error.message:error));return false}
  },
  locateEvidence:async(paragraph:string,quote:string,replacement?:string)=>{if(replacement!==undefined){toast.error('请复制建议，在正文中以修订方式修改');return false}try{const result=await wire.current?.send('locate',{paragraph,quote});if(result?.status!=='located')throw Error(result?.status==='ambiguous'?'原文存在重复，无法唯一定位，请使用编辑器查找核对。':'原文已变化或无法定位，请核对并重新审查。');return true}catch(e){toast.error(String(e instanceof Error?e.message:e));return false}},
  exportDocx:async()=>{if(!await save('export'))return;const vid=knownVersion(documentId);const a=document.createElement('a');a.href=`/api/v1/versions/${vid}/file`;a.download=file.name;a.click()},
  openNativeReview:()=>wire.current?.send('review').catch(e=>toast.error(String(e))),openNativeComments:()=>wire.current?.send('comments').catch(e=>toast.error(String(e))),
  freeze:()=>{closed.current=true;sessionStorage.removeItem(storageKey);setReview(r=>({...r,completed:true}));void wire.current?.send('unfreeze').then(()=>wire.current?.send('mode',{mode:'viewing'}))},
  reopen:async()=>{try{await post(`/contracts/${serverId(documentId)}/editor-reopen`,{});sessionStorage.removeItem(storageKey);window.location.reload();return true}catch(e){toast.error(String(e));return false}},
 }
}
