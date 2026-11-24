import {useEffect,useRef,useState} from 'react'
import {FileText,LoaderCircle,Check} from 'lucide-react'
import {Dialog,DialogContent,DialogDescription,DialogHeader,DialogTitle} from './components/ui/dialog'
import {Button} from './components/ui/button'
import {api,post} from './backend-api'
import {downloadExport,exportChoices,finishExport,unavailable,type ExportKind,type ExportOptions,type ExportRecord} from './export-flow'
import './export-dialog.css'

type Props={open:boolean;onOpenChange:(open:boolean)=>void;cid:string;runId?:string;versionId?:string;historical?:boolean;capture?:()=>Promise<{documentVersionId:string}>;release?:()=>Promise<void>}
export function ExportDialog({open,onOpenChange,cid,runId,versionId,historical=false,capture,release}:Props){
 const [kind,setKind]=useState<ExportKind>('contract'),[options,setOptions]=useState<ExportOptions|null>(null)
 const [stage,setStage]=useState(''),[error,setError]=useState(''),[record,setRecord]=useState<ExportRecord|null>(null),[done,setDone]=useState(false),[retry,setRetry]=useState(0)
 const lock=useRef(false),request=useRef<{key:string;version:string;kind:ExportKind;runId?:string}|null>(null)
 const callbacks=useRef({capture,release});callbacks.current={capture,release}
 useEffect(()=>{
  if(!open)return
  let alive=true
  setKind('contract');setOptions(null);setError('');setRecord(null);setDone(false);request.current=null
  lock.current=true;setStage(capture?'正在保存当前文档…':'正在核对导出范围…')
  void(async()=>{
   let vid=versionId
   try{
    if(callbacks.current.capture){try{vid=(await callbacks.current.capture()).documentVersionId}finally{await callbacks.current.release?.()}}
    if(!vid)throw Error('没有可导出的文档版本')
    const value=await api<ExportOptions>(`/contracts/${cid}/export-options?document_version_id=${encodeURIComponent(vid)}${runId?`&run_id=${encodeURIComponent(runId)}`:''}`)
    if(alive)setOptions(value)
   }catch(e){if(alive)setError(e instanceof Error?e.message:'导出范围读取失败')}
   finally{if(alive){lock.current=false;setStage('')}}
  })()
  return()=>{alive=false}
 },[open,cid,runId,versionId,retry])
 const runExport=async()=>{
  if(lock.current)return
  lock.current=true;setDone(false);setError('')
  try{
   let next=record
   if(!next){
    if(!request.current){
     setStage(capture?'正在保存当前文档…':'正在固定文档版本…')
     let vid=versionId??options?.document_version_id
     try{if(capture)vid=(await capture()).documentVersionId}
     finally{await release?.()}
     if(!vid)throw Error('没有可导出的文档版本')
     request.current={key:crypto.randomUUID(),version:vid,kind,runId}
    }
    setStage('正在准备导出…')
    const req=request.current
    next=await post<ExportRecord>(`/contracts/${cid}/exports`,{kind:req.kind,document_version_id:req.version,run_id:req.runId,idempotency_key:req.key})
    setRecord(next)
   }
   setStage(next.state==='ready'?'正在下载…':'正在生成文件…')
   const ready=await finishExport(next,id=>post<ExportRecord>(`/exports/${id}/generate`,{}),downloadExport)
   setRecord(ready);setDone(true)
  }catch(e){setError(e instanceof Error?e.message:'导出失败，请重试')}
  finally{lock.current=false;setStage('')}
 }
 const change=(value:ExportKind)=>{setKind(value);setRecord(null);setError('');setDone(false);request.current=null}
 const busy=!!stage,choice=exportChoices.find(c=>c.kind===kind)!,reason=unavailable(kind,options)
 return <Dialog open={open} onOpenChange={value=>{if(!lock.current)onOpenChange(value)}}><DialogContent className="export-dialog" onInteractOutside={e=>{if(busy)e.preventDefault()}} onEscapeKeyDown={e=>{if(busy)e.preventDefault()}}>
  <DialogHeader><DialogTitle>导出</DialogTitle><DialogDescription>{historical?'导出本轮保存的文档和审查意见':'选择需要交付的文件'}</DialogDescription></DialogHeader>
  <fieldset disabled={busy} className="export-options"><legend className="sr-only">导出内容</legend>{exportChoices.map((c,i)=>{const why=unavailable(c.kind,options);return <div key={c.kind}>
   {(i===0||i===1)&&<h3>{i===0?'合同文件':'审阅说明'}</h3>}
   <label className={`export-choice ${kind===c.kind?'is-selected':''} ${why?'is-unavailable':''}`}>
    <input type="radio" name="export-kind" value={c.kind} checked={kind===c.kind} disabled={!!why} onChange={()=>change(c.kind)}/><FileText aria-hidden="true"/>
    <span><strong>{historical&&c.kind==='contract'?'本轮送审合同':c.title}</strong><span>{c.description}</span>
     {why?<small>{why}</small>:options&&<small>{c.kind==='changes'?`正文修改 ${options.modifications} 处 · 新增或调整批注 ${options.comments} 条 · 删除批注 ${options.removed_comments} 条${options.other_changes?' · 含其他文档变化':''}`:c.kind==='opinions'?`审查意见 ${options.issues} 项${options.round_number?` · 第 ${options.round_number} 轮`:''}`:`文档第 ${options.current_revision} 版`}</small>}
    </span>
   </label></div>})}</fieldset>
  {kind==='changes'&&<p className="export-scope">以{options?.round_number?`第 ${options.round_number} 轮送审版本`:'首次上传版本'}为基准，核对主文档段落、表格文字及批注。字体、图片及页眉页脚请结合合同文件查看。</p>}
  {kind==='opinions'&&options&&options.base_revision!==options.current_revision&&<p className="export-scope">审查意见依据第 {options.base_revision} 版正文；应用状态按本次导出的第 {options.current_revision} 版核对。</p>}
  {stage&&<p className="export-progress" role="status"><LoaderCircle className="spin"/>{stage}</p>}
  {error&&<div className="export-error" role="alert"><p>{error}</p>{!options&&<Button variant="ghost" size="sm" disabled={busy} onClick={()=>setRetry(v=>v+1)}>重新读取导出范围</Button>}{record?<small>重试将沿用本次固定的文档和审查数据。</small>:options&&<Button variant="ghost" size="sm" disabled={busy} onClick={()=>setRetry(v=>v+1)}>重新读取当前版本</Button>}</div>}
  {done&&record&&<p className="export-success" role="status"><Check/>已发起下载：{record.filename}</p>}
  <footer className="export-footer"><Button variant="outline" disabled={busy} onClick={()=>onOpenChange(false)}>{done?'关闭':'取消'}</Button><Button disabled={busy||!!reason} onClick={()=>void runExport()}>{busy?'处理中…':done?'再次下载':error?'重试导出':choice.action}</Button></footer>
 </DialogContent></Dialog>
}
