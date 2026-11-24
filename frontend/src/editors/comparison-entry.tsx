import {authFetch} from '../auth-http'
// Isolated development harness. No production route, model calls, save, or review writes.
import {useEffect,useRef,useState} from 'react'
import ReactDOM from 'react-dom/client'
import {api,type Version} from '../backend-api'
import {createReviewFollower,followTargets,type FollowStatus} from '../review-follow'
import {reduceExecution,type ExecutionState} from '../review-execution'
import {useOnlyoffice} from './use-onlyoffice'
import type {mountEigenpal} from './eigenpal-editor'
import type {ReviewEditor,ReviewTarget} from './contract-editor'
import './comparison.css'

if(!import.meta.env.DEV)throw Error('对照入口仅在开发环境可用')
const params=new URLSearchParams(location.search),cid=params.get('id'),engine=params.get('engine')==='onlyoffice'?'onlyoffice':'eigenpal'
const contract=await api<{id:string;title:string;data_purpose:string;current_document_version_id:string}>(`/contracts/${cid}`)
if(contract.data_purpose!=='test')throw Error('仅接受合成测试合同')
const version=await api<Version>(`/versions/${contract.current_document_version_id}`)
const response=await authFetch(`/api/v1/versions/${version.id}/file`)
if(!response.ok)throw Error('测试快照下载失败')
const bytes=new Uint8Array(await response.arrayBuffer())
const target=(index:number):ReviewTarget=>{const b=version.blocks[index];return {documentVersionId:version.id,blockId:b.id,paragraph:b.text,quote:b.text,start:0,end:Array.from(b.text).length,blocks:version.blocks}}
function initial():ExecutionState{return {schema_version:1,run_id:'controlled-comparison',document_version_id:version.id,attempt_id:'controlled',seq:0,status:'running',issues:{},tasks:{},plan:{revision:1,scope:'受控事件验证',units:version.blocks.map((b,i)=>({id:b.id,title:b.text.slice(0,34),source_order:i,block_ids:[b.id],anchor:{block_id:b.id,start:0,end:Array.from(b.text).length,quote:b.text},task_ids:['task-'+i],screening:'controlled'}))}}}
type Mounted=Awaited<ReturnType<typeof mountEigenpal>>
function Comparison(){
 const host=useRef<HTMLDivElement>(null),runtime=useRef<Mounted|null>(null),office=useOnlyoffice('server:'+cid,engine==='onlyoffice')
 const [adapter,setAdapter]=useState<ReviewEditor|null>(null),[error,setError]=useState(''),[status,setStatus]=useState<FollowStatus>({mode:'paused',message:'正在加载只读快照'}),[execution,setExecution]=useState(initial),[chosen,setChosen]=useState(1),[reference,setReference]=useState(false)
 const current=useRef(execution);current.current=execution
 const follower=useRef<ReturnType<typeof createReviewFollower>|null>(null),referenceReturn=useRef<ReviewTarget|null>(null)
 const metrics=useRef<{blockId:string;ms:number;ok:boolean}[]>([]),loaded=useRef(performance.now()),loadMs=useRef(0)
 useEffect(()=>{
  if(engine!=='eigenpal'||!host.current)return
  let disposed=false
  void (async()=>{
   const [{mountEigenpal},{packagedFonts},{cjkFonts},{composeFontOrigins,defineFontResolver}]=await Promise.all([import('./eigenpal-editor'),import('@docx-editor.dev/fonts'),import('@docx-editor.dev/fonts-cjk/browser'),import('@docx-editor.dev/core/editor')])
   if(disposed||!host.current)return
   const r=await mountEigenpal(host.current,bytes,version.id,version.blocks,defineFontResolver(request=>composeFontOrigins([packagedFonts(),cjkFonts({loading:'wait'})],request)))
   if(disposed){r.destroy();return}runtime.current=r;loadMs.current=performance.now()-loaded.current;setAdapter(r.adapter)
  })().catch(e=>setError(String(e)))
  return()=>{disposed=true;runtime.current?.destroy()}
 },[])
 useEffect(()=>{if(engine==='onlyoffice'&&office.ready)void office.setReviewReadonly(true).then(()=>{loadMs.current=performance.now()-loaded.current;setAdapter(office)}).catch(e=>setError(String(e)))},[office.ready])
 useEffect(()=>{
  if(!adapter)return
  const locate=async(t:ReviewTarget,context?:import('./contract-editor').ReviewEvidenceContext)=>{const start=performance.now();const ok=adapter.presentReviewEvidence?(await adapter.presentReviewEvidence({current:t,reveal:'if-needed',context})).ok:await adapter.locateReviewTarget!(t);metrics.current.push({blockId:t.blockId,ms:performance.now()-start,ok});return ok}
  const f=createReviewFollower(async(t,valid)=>{const b=version.blocks.find(b=>b.id===t.anchor.block_id);if(!b||!valid())return false;return locate({documentVersionId:version.id,blockId:b.id,paragraph:b.text,start:t.anchor.start,end:t.anchor.end,quote:t.anchor.quote,blocks:version.blocks},{title:t.guidance?.reason||t.title,phase:t.guidance?.phase==='clear'?'finished':t.guidance?.phase??'context'})},setStatus,450,adapter.canAutomaticallyLocate,adapter.cancelReviewNavigation)
  follower.current=f;f.update(followTargets(current.current),true)
  const off=adapter.subscribeDocumentInteraction?.(()=>f.pause())
  // Explicitly DEV-only diagnostics and controlled events for repeatable UI verification.
  Object.assign(window,{__editorComparison:{engine,version,locate,emit,diagnostics:()=>({loadMs:loadMs.current,metrics:metrics.current,eigenpal:runtime.current?.diagnostics(),status:document.querySelector('[data-status]')?.textContent}),native:runtime.current?.native,adapter}})
  return()=>{off?.();f.dispose();delete (window as any).__editorComparison}
 },[adapter])
 useEffect(()=>{follower.current?.update(followTargets(execution),!reference,undefined,execution.status==='completed')},[execution,reference])
 function emit(type:string,index:number){
  setExecution(s=>{
   if(type==='run_completed')return {...s,status:'completed',seq:s.seq+1}
   const t=target(index),anchor={block_id:t.blockId,start:t.start,end:t.end,quote:t.quote}
   const payload=type==='issue_upserted'?{issue:{id:'issue-'+index,rule_id:'controlled',status:'flag',title:'付款条件需要核对',explanation:'合成事件：请结合验收条款核对付款触发条件。',evidence:[anchor],suggested_text:null}}:{task_id:'task-'+index,title:'核对第 '+(index+1)+' 个阅读单元',anchor}
   return reduceExecution(s,{run_id:s.run_id,document_version_id:s.document_version_id,attempt_id:s.attempt_id,seq:s.seq+1,type,payload})??s
  })
 }
 async function visit(){
  const key=follower.current?.checkpoint().targetKey,b=version.blocks.find(b=>key?.startsWith(b.id+':'))
  if(!b||!adapter)return
  referenceReturn.current=target(version.blocks.indexOf(b));follower.current?.pause('正在核对关联条款');setReference(true)
  const t=target(version.blocks.length-2);runtime.current?.highlightRelated([t]);if(!await adapter.locateReviewTarget!(t))setError('关联证据定位失败')
 }
 async function back(){if(referenceReturn.current&&adapter){await adapter.locateReviewTarget!(referenceReturn.current);setReference(false);follower.current?.toggle()}}
 return <main><header><div><b>合同审查 · 阅读引擎对照</b><small>{engine==='eigenpal'?'EigenPal 2.37.0':'OnlyOffice'} · 只读快照 · 合成合同</small></div><a href={`http://127.0.0.1:${engine==='eigenpal'?5175:5176}/editor-comparison.html?id=${cid}&engine=${engine==='eigenpal'?'onlyoffice':'eigenpal'}`}>切换引擎</a></header><section className="comparison-layout"><div className="document-host" ref={engine==='eigenpal'?host:office.host}/><aside><span className="badge">受控事件验证 · 不调用模型</span><h2>正在核查什么</h2><p data-status>{error||office.error||status.message}</p><p className="detail">{status.target?.guidance?.detail||'事件到达时更新状态；没有新结果时保留阅读位置。'}</p><div className="actions"><button disabled={!adapter} onClick={()=>follower.current?.advance()}>下一个核查点</button><button disabled={!status.target} onClick={()=>void (reference?back():visit())}>{reference?'返回核查点':'查看关联条款'}</button></div><h3>持续更新的审查事项</h3>{Object.values(execution.issues).map(i=><article key={i.id}><strong>{i.title}</strong><p>{i.explanation}</p></article>)}<h3>验证控制</h3><select aria-label="阅读单元" value={chosen} onChange={e=>setChosen(Number(e.target.value))}>{version.blocks.map((b,i)=><option value={i} key={b.id}>{i+1}. {b.text.slice(0,22)}</option>)}</select><div className="actions">{[['task_started','开始核查'],['task_completed','任务返回'],['issue_upserted','形成意见'],['task_failed','核查失败'],['run_completed','结束审查']].map(([event,label])=><button disabled={!adapter} key={event} onClick={()=>emit(event,chosen)}>{label}</button>)}</div><h3>阅读目录</h3><nav>{version.blocks.map((b,i)=><button key={b.id} onClick={()=>{follower.current?.setPace('manual');follower.current?.select(followTargets(current.current)[i])}}>{i+1}. {b.text.slice(0,28)}</button>)}</nav></aside></section></main>
}
ReactDOM.createRoot(document.getElementById('root')!).render(<Comparison/> )
