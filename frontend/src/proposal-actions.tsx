import {createContext,useContext,useEffect,useRef,useState,type ReactNode} from 'react'
import {DropdownMenu} from 'radix-ui'
import {Check,ChevronDown,LoaderCircle,Pin,Undo2,FileCheck2} from 'lucide-react'
import {toast} from 'sonner'
import {api,post,type RevisionProposal} from './backend-api'
import type {ReviewEditor,ReviewTarget,ProposalMode,ProposalOperation} from './editors/contract-editor'
// Keep write eligibility on the server; omit this redundant stale-target notice from cards.
export const isChangedTargetNotice=(message?:string)=>message?.trim().replace(/[。.]$/, '')==='目标条款已变化或删除，请按最新原文复核'
const isPendingReviewNotice=(message?:string)=>['审查尚未完成','审查正在进行','本轮审查未完成','部分审查未完成'].includes(message?.trim().replace(/[。.]$/, '')??'')
const proposalReasonTitle=(message:string)=>isChangedTargetNotice(message)?'当前建议不能自动写入，请核对最新正文':message
const modes:{value:ProposalMode;label:string}[]=[{value:'ALL',label:'接受修订并添加批注'},{value:'MODIFY',label:'接受修订'}]
export type ProposalCompletion={comment:boolean;revision:boolean}
export type ProposalRecheck={status:'not_required'|'required'|'running'|'completed'|'failed'|'blocked';message:string;can_retry:boolean;document_version_id:string}
export type ProposalLocation={status:string;message:string;target?:ReviewTarget}
type Availability={document_version_id?:string;recheck?:ProposalRecheck;blocking_operation?:ProposalOperation|null;eligible:string[];proposals:Record<string,{append_paragraphs?:string[];modes:ProposalMode[];reasons:Record<ProposalMode,string>;manual_revision_reason?:string;completed?:ProposalCompletion;location?:ProposalLocation;recheck?:{status:string;reason:string}}>}
const Actions=createContext<{editor:ReviewEditor;mode:ProposalMode;setMode:(mode:ProposalMode)=>void;blocked:boolean;blockedReason:string;pending:string;loaded:boolean;loadError:string;reload:()=>Promise<void>;availability:Availability;ops:ProposalOperation[];perform:(pid:string,mode:ProposalMode,op?:ProposalOperation,undo?:boolean,manualReplacement?:string)=>Promise<boolean>}|null>(null)
export function ProposalActionsProvider({editor,runId,runStatus,blocked,blockedReason='',refresh,children}:{editor:ReviewEditor;runId?:string;runStatus?:string;blocked:boolean;blockedReason?:string;refresh:()=>Promise<void>;children:ReactNode}){
 const [ops,setOps]=useState<ProposalOperation[]>([]),[pending,setPending]=useState(''),[loaded,setLoaded]=useState(false)
 const [mode,changeMode]=useState<ProposalMode>(()=>{try{const m=localStorage.getItem('rixin.proposal.default');return modes.some(x=>x.value===m)?m as ProposalMode:'ALL'}catch{return 'ALL'}})
 const setMode=(value:ProposalMode)=>{changeMode(value);try{localStorage.setItem('rixin.proposal.default',value)}catch{}}
 const [availability,setAvailability]=useState<Availability>({eligible:[],proposals:{}}),[loadError,setLoadError]=useState('')
 const inFlight=useRef(false),scope=useRef(runId);scope.current=runId
 const mounted=useRef(true)
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[])
 const requestToken=useRef(0)
 const generation=useRef(0),attempted=useRef(new Set<string>()),availabilityRef=useRef(availability);availabilityRef.current=availability
 const [recheckBusy,setRecheckBusy]=useState(false),[recheckError,setRecheckError]=useState('')
 const fetchState=async()=>{if(!runId)return null;const [rows,availability]=await Promise.all([api<ProposalOperation[]>(`/runs/${runId}/proposal-operations`),api<Availability>(`/runs/${runId}/proposal-availability`)]);return {rows,availability}}
 const reload=async()=>{const epoch=generation.current;const next=await fetchState();if(next&&scope.current===runId&&epoch===generation.current){setOps(next.rows);setAvailability(next.availability);setLoadError('');setLoaded(true)}}
 useEffect(()=>{let live=true;generation.current++;setLoaded(false);setLoadError('');if(!runId){setOps([]);setAvailability({eligible:[],proposals:{}})}else void fetchState().then(next=>{if(live&&next){setOps(next.rows);setAvailability(next.availability);setLoaded(true)}}).catch(()=>{if(live){setLoaded(false);setLoadError('操作状态加载失败，请重试')}});return()=>{live=false;generation.current++}},[runId,runStatus,editor.saveStatus,blocked])
 const recheck=async(retry=false)=>{
   const version=availability.document_version_id,key=`${runId}:${version}`
   if(!runId||!version||blocked||!loaded||recheckBusy)return
   attempted.current.add(key);setRecheckBusy(true);setRecheckError('');const token=++requestToken.current
   const current=()=>mounted.current&&requestToken.current===token&&scope.current===runId&&availabilityRef.current.document_version_id===version
   await submitProposalRecheck({runId,version,retry,current,request:post,onError:message=>{if(availabilityRef.current.recheck?.status!=='completed')setRecheckError(message)},onDone:async()=>{setRecheckBusy(false);await reload().catch(()=>{})}})
 }
 useEffect(()=>{setRecheckBusy(false);setRecheckError('')},[runId,availability.document_version_id])
 useEffect(()=>{if(availability.recheck&&['completed','failed','blocked','not_required'].includes(availability.recheck.status))setRecheckBusy(false)},[availability.recheck?.status])
 useEffect(()=>{
   const key=`${runId}:${availability.document_version_id}`
   if(loaded&&!blocked&&editor.ready&&editor.saveStatus==='saved'&&availability.recheck?.status==='required'&&!attempted.current.has(key))void recheck()
 },[runId,availability.document_version_id,availability.recheck?.status,loaded,blocked,editor.ready,editor.saveStatus])
 useEffect(()=>{
   if(!recheckBusy&&availability.recheck?.status!=='running')return
   let active=true,running=false
   const timer=setInterval(()=>{if(active&&!running){running=true;void reload().catch(()=>{}).finally(()=>{running=false})}},2000)
   return()=>{active=false;clearInterval(timer)}
 },[runId,availability.document_version_id,availability.recheck?.status,recheckBusy])
 const perform=async(pid:string,mode:ProposalMode,op?:ProposalOperation,undo=false,manualReplacement?:string)=>{
   if(inFlight.current||blocked||!runId)return false
   inFlight.current=true;setPending(pid)
   try{
     let result:ProposalOperation|undefined
     if(op&&undo)await editor.undoProposal!(op)
     else if(op?.state==='prepared')result=await editor.confirmProposal!(op.id)
     else result=await editor.applyProposal!(runId,pid,mode,manualReplacement)
     await reload();await refresh()
     if(result?.state==='cancelled')toast.info('本次操作未写入，可重新操作')
     else if(result?.state==='prepared')toast.error(result.verification_error||'保存结果仍待确认，请重试确认或恢复')
     else if(!undo&&mode==='COMMENT')toast.success('批注已保存并核验')
     return result?.state!=='cancelled'
   }catch(e){toast.error(e instanceof Error?e.message:String(e));await reload().catch(()=>{});return false}
   finally{inFlight.current=false;setPending('')}
 }
 return <Actions.Provider value={{editor,mode,setMode,blocked,blockedReason,pending,loaded,loadError,reload,availability,ops,perform}}><PreviousProposalRecovery runId={runId} operation={availability.blocking_operation} disabled={blocked||!!pending||!loaded||!editor.confirmProposal||!editor.undoProposal} perform={perform}/><ProposalRecheckNotice value={availability.recheck} busy={recheckBusy} error={recheckError} disabled={blocked||!loaded} retry={()=>void recheck(true)}/>{children}</Actions.Provider>
}
export async function submitProposalRecheck({runId,version,retry,current,request,onError,onDone}:{runId:string;version:string;retry:boolean;current:()=>boolean;request:(url:string,body:unknown)=>Promise<unknown>;onError:(message:string)=>void;onDone:()=>Promise<void>}){
 try{await request(`/runs/${runId}/proposal-rechecks`,{expected_version_id:version,retry})}
 catch(e){if(current())onError(e instanceof Error?e.message:String(e))}
 finally{if(current())await onDone()}
}
export function ProposalRecheckNotice({value,busy,error,disabled,retry}:{value?:ProposalRecheck;busy:boolean;error:string;disabled:boolean;retry:()=>void}){
 if(!value||busy||value.status==='running'||value.status==='not_required'||value.status==='completed'||(!error&&isPendingReviewNotice(value.message)))return null
 return <div className="revision-blocker" role="status"><p>{error||value.message}</p>{(value.can_retry||!!error)&&<button type="button" className="proposal-apply" disabled={disabled} onClick={retry}>重试局部复核</button>}</div>
}
export function useProposalLocation(pid:string){
 const c=useContext(Actions),item=c?.availability.proposals[pid],target=item?.location?.target
 const canLocate=!!target&&target.documentVersionId===c?.availability.document_version_id&&!!c?.editor.locateReviewTarget&&c.loaded&&!c.blocked&&!c.pending&&c.editor.ready&&c.editor.saveStatus==='saved'
 return {appended:item?.append_paragraphs,location:item?.location,recheck:item?.recheck,canLocate,locate:async()=>{
   if(!canLocate||!target||!c)return
   try{if(!await c.editor.locateReviewTarget!(target))toast.error('当前位置未能定位，请重新核对')}catch(e){toast.error(e instanceof Error?e.message:String(e))}
 }}
}
export function PreviousProposalRecovery({runId,operation:op,disabled,perform}:{runId?:string;operation?:ProposalOperation|null;disabled:boolean;perform:(pid:string,mode:ProposalMode,op:ProposalOperation,undo?:boolean)=>Promise<unknown>}){
 if(!op||op.state!=='prepared'||op.run_id===runId)return null
 return <div className="revision-blocker" role="status">
   <p>上一轮操作保存结果待确认。{op.verification_error}</p>
   <button type="button" className="proposal-apply" disabled={disabled} onClick={()=>void perform(op.proposal_id,op.mode,op)}>核对保存</button>
   <button type="button" className="proposal-apply" disabled={disabled} onClick={()=>void perform(op.proposal_id,op.mode,op,true)}>撤销未完成操作</button>
 </div>
}
export function useProposalEligible(pid:string){return !!useContext(Actions)?.availability.eligible.includes(pid)}
export function useProposalOperation(pid:string){const c=useContext(Actions);return c?.ops.filter(o=>o.proposal_id===pid&&o.state!=='cancelled'&&o.state!=='reverted').at(-1)}
export function proposalCompletion(ops:ProposalOperation[],pid:string):ProposalCompletion{
 const applied=ops.filter(o=>o.proposal_id===pid&&o.state==='applied')
 return {comment:applied.some(o=>o.mode!=='MODIFY'),revision:applied.some(o=>o.mode!=='COMMENT')}
}
export function useProposalCompletion(pid:string){const c=useContext(Actions);return c?.availability.proposals[pid]?.completed??proposalCompletion(c?.ops??[],pid)}
export function ProposalActionButton({proposal:p}:{proposal:RevisionProposal}){
 return <MarkupActions pid={p.proposal_id??p.id!}/>
}

export function IssueMarkupRecovery({issueId}:{issueId:string}){
 const op=useProposalOperation(issueId)
 if(!op||(op.state!=='prepared'&&!(op.state==='applied'&&op.can_undo)))return null
 return <MarkupActions pid={issueId} recoveryOnly/>
}

function MarkupActions({pid,recoveryOnly=false}:{pid:string;recoveryOnly?:boolean}){
 const ctx=useContext(Actions),op=useProposalOperation(pid)
 const completed=useProposalCompletion(pid)
 if(!ctx?.editor.capabilities.applyTrackedSuggestion||!ctx.editor.applyProposal)return null
 const {mode,setMode}=ctx
 const processing=ctx.pending===pid,disabled=ctx.blocked||!!ctx.pending||!ctx.loaded
 const available=ctx.availability.proposals[pid]
 const allowed=(m:ProposalMode)=>!!available?.modes.includes(m)
 const reason=(m:ProposalMode)=>ctx.blocked?(ctx.blockedReason||'当前文档暂不可写'):ctx.pending?'请等待当前操作保存完成':!ctx.loaded?(ctx.loadError||'正在加载操作状态'):available?.reasons[m]||(!allowed(m)?'该建议暂不可操作':'')
 if(ctx.loadError)return <button type="button" className="proposal-apply" title={ctx.loadError} onClick={()=>void ctx.reload().catch(()=>toast.error('操作状态加载失败，请重试'))}>重试加载操作</button>
 const undo=()=>void ctx.perform(pid,op?.mode??mode,op,true)
 if(recoveryOnly&&op?.state!=='prepared')return op?.state==='applied'&&op.can_undo
   ? <button type="button" className="proposal-apply" disabled={disabled} onClick={undo}><Undo2/>撤销上次操作</button> : null
 return <ProposalActionControls {...{mode,setMode,processing,disabled,allowed,reason,op,completed,undo}}
   execute={value=>void ctx.perform(pid,value)} confirm={()=>void ctx.perform(pid,op?.mode??mode,op)}/>
}

export function ProposalActionControls({mode,setMode,processing,disabled,allowed,reason,op,completed,execute,confirm,undo}:{mode:ProposalMode;setMode:(m:ProposalMode)=>void;processing:boolean;disabled:boolean;allowed:(m:ProposalMode)=>boolean;reason:(m:ProposalMode)=>string;op?:ProposalOperation;completed:ProposalCompletion;execute:(m:ProposalMode)=>void;confirm:()=>void;undo:()=>void}){
 if(op?.state==='prepared')return <div>
   <button type="button" className="proposal-apply" disabled={disabled} onClick={confirm}><LoaderCircle className={processing?'spin':undefined}/>{processing?'正在核对保存结果…':'重试保存确认'}</button>
   <button type="button" className="proposal-apply" disabled={disabled} onClick={undo}>撤销未完成操作</button>
   {op.verification_error&&<p className="revision-blocker" role="status">{op.verification_error}</p>}
 </div>
 const complete=completed.revision
 // A completed default action must not hide another action that is still available.
 const choices=modes
 const preferred=choices.find(m=>m.value===mode)
 const active=preferred&&allowed(mode)?preferred:choices.find(m=>allowed(m.value))??preferred??choices[0]
 const activeMode=active.value
 const label=activeMode==='ALL'?(completed.comment?'补做修订':'接受修注'):active.label
 return <div>
   {complete?<span role="status">{completed.comment?'修订与批注均已保存':'修订已保存'}</span>:<div className="proposal-split-button">
     <button type="button" className="proposal-apply" title={proposalReasonTitle(reason(activeMode))||'采纳后保留修订痕迹，风险确认状态不变'} aria-label={label} disabled={disabled||!allowed(activeMode)} onClick={()=>execute(activeMode)}>{processing?<LoaderCircle className="spin"/>:<FileCheck2/>}{processing?'正在保存确认…':label}</button>
     {choices.length>1&&<DropdownMenu.Root><DropdownMenu.Trigger asChild><button type="button" aria-label="选择修订操作" title={disabled?proposalReasonTitle(reason(activeMode)):'选择修订操作'} className="proposal-mode-trigger" disabled={disabled}><ChevronDown/></button></DropdownMenu.Trigger><DropdownMenu.Portal><DropdownMenu.Content className="proposal-actions-menu" sideOffset={5} align="end">
       {choices.map(m=><div className="proposal-mode-row" key={m.value} title={proposalReasonTitle(reason(m.value))}><DropdownMenu.Item disabled={disabled||!allowed(m.value)} onSelect={()=>execute(m.value)}><FileCheck2/>{m.label}</DropdownMenu.Item><button type="button" aria-label={`将${m.label}设为默认操作`} aria-pressed={mode===m.value} onClick={()=>setMode(m.value)}>{mode===m.value?<Check/>:<Pin/>}</button></div>)}
     </DropdownMenu.Content></DropdownMenu.Portal></DropdownMenu.Root>}
   </div>}
   {op?.state==='applied'&&op.can_undo&&<button type="button" className="proposal-apply" disabled={disabled} onClick={undo}><Undo2/>撤销上次操作</button>}
   {!complete&&reason(activeMode)&&!isPendingReviewNotice(reason(activeMode))&&!isChangedTargetNotice(reason(activeMode))&&<p className="revision-blocker" role="status">{reason(activeMode)}</p>}
 </div>
}
