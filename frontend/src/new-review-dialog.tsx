import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowLeft, ArrowRight, BookOpen, Check, ChevronRight, FileText, ShieldCheck, Upload } from 'lucide-react'
import { Button } from './components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from './components/ui/dialog'
import { contractTypes, owners, type WorkbenchContract } from './workbench-data'
import { loadRules, positions, type Position, type ReviewConfiguration, type RulePack } from './rule-data'
import { cn } from './lib/utils'
import './rules.css'
import { PartyIdentification, type PartyConfirmation } from './party-identification'
import type { PartySelection } from './party-types'

export interface ReviewSubmission {
  requestId:string;partySelection:PartySelection;title:string;counterpart:string;type:string;owner:string;deadline:string;file:File;configuration:ReviewConfiguration
}
export function NewReviewDialog({item,preset,onClose,onSubmit}: {
  item:WorkbenchContract|null;preset?:string;onClose:()=>void;onSubmit:(submission:ReviewSubmission)=>Promise<void>
}) {
  const [step,setStep] = useState(0)
  const [file,setFile] = useState<File|null>(null)
  const [title,setTitle] = useState(item?.title??'')
  const [partyConfirmation,setPartyConfirmation] = useState<PartyConfirmation|null>(null)
  const counterpart=partyConfirmation?.counterpart??''
  const [owner,setOwner] = useState(item?.owner??'我')
  const [deadline,setDeadline] = useState(item?.deadline??new Date(Date.now()+7*86400000).toLocaleDateString('sv-SE'))
  const [type,setType] = useState(item?.type??contractTypes[0])
  const [position,setPosition] = useState<Position>(positions.includes(item?.position as Position)?item!.position as Position:positions[0])
  const identify=useCallback((value:PartyConfirmation|null)=>{
    setPartyConfirmation(value)
    if(value?.ourRole==='甲方')setPosition(p=>p==='中立审查'?p:positions[1])
    if(value?.ourRole==='乙方')setPosition(p=>p==='中立审查'?p:positions[0])
  },[])
  const [pack,setPack] = useState<RulePack|null>(null)
  const [loading,setLoading] = useState(true)
  const [loadError,setLoadError] = useState(false)
  const [error,setError] = useState('')
  const [busy,setBusy] = useState(false)
  const pending = useRef(false)
  const submissionKey=useRef({signature:'',id:'',createdAt:''})
  const trigger = useRef(document.activeElement as HTMLElement)
  const panel = useRef<HTMLDivElement>(null)
  const load = async () => {
    setLoading(true);setLoadError(false)
    try {setPack(await loadRules())} catch {setPack(null);setLoadError(true)} finally {setLoading(false)}
  }
  useEffect(()=>{void load()},[])
  useEffect(()=>{panel.current?.scrollTo({top:0})},[step])
  const changeFile = (next:File|null) => {
    setFile(next);setPartyConfirmation(null);setError('')
    if(next&&!title)setTitle(next.name.replace(/\.docx$/i,''))
  }
  const validateFile = async () => {
    if(!file)throw new Error('请选择一份 DOCX 合同正文。')
    if(!file.name.toLowerCase().endsWith('.docx'))throw new Error('请选择 .docx 格式的 Word 文档。')
    if(file.size>20*1024*1024)throw new Error('请选择 20 MB 以内的 DOCX。')
    const bytes=new Uint8Array(await file.slice(0,4).arrayBuffer())
    if(bytes[0]!==80||bytes[1]!==75)throw new Error('文件内容不是有效的 DOCX，请重新选择。')
    if(!title.trim()||!deadline)throw new Error('请填写合同名称与期望完成日期。')
  }
  const submit = async (event:FormEvent) => {
    event.preventDefault();if(pending.current)return
    pending.current=true;setBusy(true);setError('')
    try {
      if(step===0){await validateFile();setStep(1);return}
      if(!pack?.rules.length||loadError)throw new Error('请先读取服务端审查规则。')
      if(!partyConfirmation)throw new Error('请确认我方签约主体与合同相对方。')
      if(partyConfirmation.ourRole==='甲方'&&position.startsWith('乙方')||partyConfirmation.ourRole==='乙方'&&position.startsWith('甲方'))throw new Error('审查立场与已确认的我方角色不一致，请核对。')
      if(step===1){setStep(2);return}
      await validateFile()
      const latest=await loadRules()
      if(latest.pack_sha256!==pack.pack_sha256||latest.execution_policy.prompt_sha256!==pack.execution_policy.prompt_sha256){
        setPack(latest);setStep(1);throw new Error('服务端执行规则已更新，请重新确认。')
      }
      const signature=JSON.stringify({title,counterpart,type,owner,deadline,position,party:partyConfirmation.selection,file:[file!.name,file!.size,file!.lastModified],rules:pack.pack_sha256,policy:pack.execution_policy.prompt_sha256})
      if(submissionKey.current.signature!==signature)submissionKey.current={signature,id:crypto.randomUUID(),createdAt:new Date().toISOString()}
      const configuration:ReviewConfiguration={mode:'rules',position,contractType:type,createdAt:submissionKey.current.createdAt,policyVersion:pack.execution_policy.version,rulePackVersion:pack.version}
      await onSubmit({requestId:submissionKey.current.id,partySelection:partyConfirmation.selection,title:title.trim(),counterpart:counterpart.trim(),type,owner,deadline,file:file!,configuration})
    } catch(error) {setError(error instanceof Error?error.message:'无法保存，请重试。')}
    finally {pending.current=false;setBusy(false)}
  }
  return <Dialog open onOpenChange={open=>{if(!open&&!busy)onClose()}}><DialogContent className="review-launch-dialog" showCloseButton={!busy} onCloseAutoFocus={event=>{event.preventDefault();if(trigger.current?.isConnected&&trigger.current!==document.body)trigger.current.focus();else document.querySelector<HTMLButtonElement>('.workbench-title-actions button:last-child')?.focus()}} onInteractOutside={event=>event.preventDefault()} onEscapeKeyDown={event=>{if(busy)event.preventDefault()}}><DialogHeader><DialogTitle>新建合同审阅</DialogTitle><DialogDescription>确认合同信息与审查标准，再开始逐条审阅。</DialogDescription></DialogHeader>
    <ol className="review-launch-steps" aria-label="新建审阅步骤">{['上传合同','审查设置','确认发起'].map((label,index)=><li key={label} aria-current={step===index?'step':undefined} className={cn(step===index&&'current',step>index&&'complete')}><span>{step>index?<Check/>:index+1}</span>{label}{index<2&&<ChevronRight/>}</li>)}</ol>
    <form className="review-launch-form" onSubmit={event=>void submit(event)}><div className="review-launch-body" ref={panel}><fieldset disabled={busy}>
      {step===0&&<div className="launch-upload-step"><label className="launch-file-upload" onDragOver={event=>event.preventDefault()} onDrop={event=>{event.preventDefault();if(!busy)changeFile(event.dataTransfer.files[0]??null)}}><Upload/><strong>{file?file.name:'上传合同正文'}</strong><span>点击选择或拖入 DOCX 文件 · 最大 20 MB</span><input type="file" accept=".docx" aria-label="上传合同正文" onChange={event=>changeFile(event.target.files?.[0]??null)}/></label><label>合同名称<input required maxLength={100} value={title} onChange={event=>setTitle(event.target.value)} placeholder="例如：功率预测技术服务合同"/></label><p className="launch-helper">上传后自动识别签约主体，在下一步确认我方与相对方。</p><div className="launch-form-columns"><label>负责人<select value={owner} onChange={event=>setOwner(event.target.value)}>{owners.map(owner=><option key={owner}>{owner}</option>)}</select></label><label>期望完成日期<input required type="date" value={deadline} onChange={event=>setDeadline(event.target.value)}/></label></div><p className="launch-helper"><ShieldCheck/>正文与配置保存在服务端。</p></div>}
      <div hidden={step!==1}><PartyIdentification file={file} onChange={identify}/></div>
      {step===1&&<div className="launch-settings-step"><div className="launch-section-heading"><h3>审查范围</h3><p>审查规则由服务端统一维护。</p></div><div className="launch-form-columns"><label>合同类型<select aria-label="合同类型" value={type} onChange={e=>setType(e.target.value)}>{contractTypes.map(t=><option key={t}>{t}</option>)}</select></label><label>我方立场<select aria-label="我方立场" value={position} onChange={e=>setPosition(e.target.value as Position)}>{positions.map(p=><option key={p}>{p}</option>)}</select></label></div>
        {loading?<p role="status">正在读取服务端规则…</p>:loadError?<div role="alert"><p>规则暂时无法读取。</p><Button type="button" variant="outline" onClick={()=>void load()}>重试</Button></div>:pack&&<section className="launch-confirm-rules"><h3>合同审查规则 · {pack.version}</h3><p>执行口径 {pack.execution_policy.version}</p>{pack.rules.map(r=><p key={r.id}>{r.id} · {r.title}</p>)}</section>}</div>}
      {step===2&&<div className="launch-confirm-step"><div className="launch-confirm-document"><FileText/><div><h3>{title}</h3><p>{file?.name}</p></div><span>DOCX</span></div><dl className="launch-confirm-fields"><div><dt>我方主体</dt><dd>{partyConfirmation?.ourName}</dd></div><div><dt>合同相对方</dt><dd>{counterpart}</dd></div><div><dt>合同类型</dt><dd>{type}</dd></div><div><dt>我方立场</dt><dd>{position}</dd></div><div><dt>负责人 / 期望完成</dt><dd>{owner} · {deadline}</dd></div></dl><section className="launch-confirm-rules"><header><BookOpen/><h3>合同审查规则</h3><button type="button" onClick={()=>setStep(1)}>查看</button></header><p>规则 {pack?.version} · 执行口径 {pack?.execution_policy.version}</p><p>确认后自动启动合同审查，并进入审阅室查看进度。系统将保存本次使用的合同与规则版本，结果需人工复核。</p></section></div>}
    </fieldset>{error&&<p className="form-error" role="alert">{error}</p>}</div><footer className="review-launch-footer"><Button type="button" variant="ghost" disabled={busy} onClick={()=>{if(step>0){setStep(step-1);setError('')}else onClose()}}>{step>0?<><ArrowLeft/>上一步</>:'取消'}</Button><span>{step+1} / 3</span><Button type="submit" disabled={busy||(step>0&&(loading||loadError||!pack?.rules.length))}>{busy?(step===2?'正在提交审查…':'正在检查…'):step===2?'确认并开始审查':'下一步'}<ArrowRight/></Button></footer></form>
  </DialogContent></Dialog>
}
