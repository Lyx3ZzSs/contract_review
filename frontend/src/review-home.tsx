import {useEffect,useRef,useState} from 'react'
import {FileUp} from 'lucide-react'
import {NewReviewDialog,type ReviewSubmission} from './new-review-dialog'
import {createRemote} from './backend-api'
import {validateContractFile} from './review-records-data'
import type {WorkbenchContract} from './workbench-data'
export function ReviewHome({onOpen,registerNavigationGuard}:{onOpen:(item:WorkbenchContract)=>void;registerNavigationGuard:(guard:()=>Promise<boolean>)=>()=>void}){
 const [file,setFile]=useState<File|null>(null),[error,setError]=useState(''),[checking,setChecking]=useState(false),[busy,setBusy]=useState(false),[dragging,setDragging]=useState(false)
 const submitted=useRef(false),selection=useRef(0)
 const guardRef=useRef(async()=>true)
 guardRef.current=async()=>submitted.current||(!busy&&!checking&&(!file||window.confirm('合同尚未发起审查，离开将丢弃本次上传设置。是否继续？')))
 useEffect(()=>registerNavigationGuard(()=>guardRef.current()),[registerNavigationGuard])
 const pick=async(files:FileList|null)=>{const next=files?.[0];if(!next)return;const seq=++selection.current;setChecking(true);setError('');try{if(files!.length!==1)throw new Error('每次请选择一份合同。');await validateContractFile(next);if(seq===selection.current)setFile(next)}catch(e){if(seq===selection.current)setError(e instanceof Error?e.message:'文件无法读取')}finally{if(seq===selection.current)setChecking(false)}}
 const save=async(s:ReviewSubmission)=>{
  const item:WorkbenchContract={id:s.requestId,number:`RX-${new Date(s.configuration.createdAt).toLocaleDateString('sv-SE').replaceAll('-','')}-${s.requestId.slice(0,4).toUpperCase()}`,title:s.title,counterpart:s.counterpart,type:s.type,owner:s.owner,department:'待确认',deadline:s.deadline,updated:s.configuration.createdAt,status:'待审阅',amount:'待确认',project:'待确认',position:s.configuration.position,high:0,medium:0,low:0,processed:0,total:0,hasDocument:true,example:false,note:'审查已提交',reviewConfig:s.configuration}
  const saved=await createRemote(item,s.file,s.partySelection,s.requestId);submitted.current=true;onOpen(saved)
 }
 if(file)return <NewReviewDialog item={null} initialFile={file} embedded onBusyChange={setBusy} onSubmit={save} onClose={()=>{setFile(null);setError('')}}/>
 return <div className="home-start"><div className="home-hero"><header className="home-heading"><h1>上传合同</h1><p>上传后选择你代表的签约方，即可开始审查。</p></header><label className={`home-dropzone ${dragging?'is-dragging':''}`} onDragOver={e=>{e.preventDefault();setDragging(true)}} onDragLeave={e=>{if(!(e.relatedTarget instanceof Node && e.currentTarget.contains(e.relatedTarget)))setDragging(false)}} onDrop={e=>{e.preventDefault();setDragging(false);if(!checking)void pick(e.dataTransfer.files)}}><FileUp/><strong>{checking?'正在检查文件…':<>拖拽合同到这里，或<span>选择文件</span></>}</strong><p>支持 DOC / DOCX 格式 · 单个文件不超过 20 MB</p><input type="file" accept=".doc,.docx" disabled={checking} aria-label="选择合同文件" onChange={e=>{void pick(e.target.files);e.target.value=''}}/></label>{error&&<p role="alert" className="form-error">{error}</p>}</div></div>
}
