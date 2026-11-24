import { useEffect, useRef, useState, type FormEvent } from 'react'
import { ArrowLeft, ArrowRight, BookOpen, Check, ChevronRight, FileText, ShieldCheck, Upload } from 'lucide-react'
import { Button } from './components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from './components/ui/dialog'
import { owners, type WorkbenchContract } from './workbench-data'
import { loadRules, positions, type Position, type ReviewConfiguration, type RulePack } from './rule-data'
import { cn } from './lib/utils'
import './rules.css'
import { PartyIdentification, type PartyConfirmation } from './party-identification'
import {validateContractFile} from './review-records-data'
import type { PartySelection } from './party-types'

export interface ReviewSubmission {
  requestId:string;partySelection:PartySelection;title:string;counterpart:string;type:string;owner:string;deadline:string;file:File;configuration:ReviewConfiguration
}
export function NewReviewDialog({item,preset,onClose,onSubmit,embedded=false,initialFile,onBusyChange}: {
  item:WorkbenchContract|null;preset?:string;embedded?:boolean;initialFile?:File;onBusyChange?:(busy:boolean)=>void;onClose:()=>void;onSubmit:(submission:ReviewSubmission)=>Promise<void>
}) {
  const [dialogOpen,setDialogOpen] = useState(true)
  const [step,setStep] = useState(embedded?2:0)
  const [file,setFile] = useState<File|null>(initialFile??null)
  const [title,setTitle] = useState(item?.title??initialFile?.name.replace(/\.docx?$/i,'')??'')
  const [partyConfirmation,setPartyConfirmation] = useState<PartyConfirmation|null>(null)
  const counterpart=partyConfirmation?.counterpart??''
  const [owner,setOwner] = useState(item?.owner??'我')
  const [deadline,setDeadline] = useState(item?.deadline??new Date(Date.now()+7*86400000).toLocaleDateString('sv-SE'))
  const type = item?.type??'未分类'
  const [fileRevision,setFileRevision]=useState(0)
  const [preferredPosition,setPosition]=useState<Position|null>(positions.includes(item?.position as Position)?item!.position as Position:null)
  const role=partyConfirmation?.ourRole
  const knownRole=role==='甲方'||role==='乙方'
  const availablePositions=positions.filter(p=>!knownRole||p==='中立审查'||p.startsWith(role))
  const position=preferredPosition&&availablePositions.includes(preferredPosition)?preferredPosition:knownRole?availablePositions[0]:null
  const [pack,setPack] = useState<RulePack|null>(null)
  const [loading,setLoading] = useState(true)
  const [loadError,setLoadError] = useState(false)
  const [error,setError] = useState('')
  const [busy,setBusy] = useState(false)
  const [replacing,setReplacing] = useState(false)
  const fileSelection=useRef(0)
  const pending = useRef(false)
  const submissionKey=useRef({signature:'',id:'',createdAt:''})
  const heading=useRef<HTMLHeadingElement>(null)
  useEffect(()=>{if(embedded)heading.current?.focus()},[embedded])
  const trigger = useRef(document.activeElement as HTMLElement)
  const panel = useRef<HTMLDivElement>(null)
  const load = async () => {
    setLoading(true);setLoadError(false)
    try {setPack(await loadRules())} catch {setPack(null);setLoadError(true)} finally {setLoading(false)}
  }
  useEffect(()=>{void load()},[])
  useEffect(()=>{onBusyChange?.(busy||replacing)},[busy,replacing,onBusyChange])
  useEffect(()=>{panel.current?.scrollTo({top:0})},[step])
  const changeFile = (next:File|null) => {
    setFile(next);setFileRevision(n=>n+1);setPosition(null);setPartyConfirmation(null);setError('')
    if(next&&!title)setTitle(next.name.replace(/\.docx?$/i,''))
  }
  const validateFile = async () => {
    if(!file)throw new Error('请选择一份 DOC 或 DOCX 合同正文。')
    await validateContractFile(file)
    if(!title.trim()||!deadline)throw new Error('请填写合同名称与期望完成日期。')
  }
  const submit = async (event:FormEvent) => {
    event.preventDefault();if(pending.current||replacing)return
    pending.current=true;setBusy(true);setError('')
    try {
      if(step===0){await validateFile();setStep(1);return}
      if(!pack?.rules.length||loadError)throw new Error('请先读取服务端审查规则。')
      if(!partyConfirmation)throw new Error('请确认我方签约主体与合同相对方。')
      if(!position)throw new Error('请选择本轮审查立场。')
      if(partyConfirmation.ourRole==='甲方'&&position.startsWith('乙方')||partyConfirmation.ourRole==='乙方'&&position.startsWith('甲方'))throw new Error('审查立场与已确认的我方角色不一致，请核对。')
      if(step===1&&!embedded){setStep(2);return}
      await validateFile()
      const latest=await loadRules()
      if(latest.pack_sha256!==pack.pack_sha256||latest.execution_policy.prompt_sha256!==pack.execution_policy.prompt_sha256){
        setPack(latest);setStep(1);throw new Error('服务端执行规则已更新，请重新确认。')
      }
      const signature=JSON.stringify({title,counterpart,type,owner,deadline,position,party:partyConfirmation.selection,file:[file!.name,file!.size,file!.lastModified],rules:pack.pack_sha256,policy:pack.execution_policy.prompt_sha256})
      if(submissionKey.current.signature!==signature)submissionKey.current={signature,id:crypto.randomUUID(),createdAt:new Date().toISOString()}
      const configuration:ReviewConfiguration={mode:'rules',position,createdAt:submissionKey.current.createdAt,policyVersion:pack.execution_policy.version,rulePackVersion:pack.version}
      await onSubmit({requestId:submissionKey.current.id,partySelection:partyConfirmation.selection,title:title.trim(),counterpart:counterpart.trim(),type,owner,deadline,file:file!,configuration})
    } catch(error) {setError(error instanceof Error?error.message:'无法保存，请重试。')}
    finally {pending.current=false;setBusy(false)}
  }
  if(embedded)return <form className="home-confirm" onSubmit={event=>void submit(event)}><header className="home-heading"><h1 ref={heading} tabIndex={-1}>确认合同，开始审查</h1><p>核对签约方后，点击“确认并开始审查”。</p></header><fieldset disabled={busy}>
    <div className="home-file"><FileText/><div><strong>{file?.name}</strong><small>{/\.doc$/i.test(file?.name??'')?'DOC':'DOCX'} · {Math.max(1,Math.round((file?.size??0)/1024))} KB</small></div><label className="home-file-change">更换文件<input type="file" accept=".doc,.docx" aria-label="更换合同文件" disabled={replacing} onChange={async e=>{const next=e.target.files?.[0];e.target.value='';if(!next)return;const sequence=++fileSelection.current;setReplacing(true);try{await validateContractFile(next);if(sequence!==fileSelection.current)return;changeFile(next);setTitle(next.name.replace(/\.docx?$/i,''))}catch(err){if(sequence===fileSelection.current)setError(err instanceof Error?err.message:'文件无法读取')}finally{if(sequence===fileSelection.current)setReplacing(false)}}}/></label></div>
    <label className="home-field">合同名称<input required maxLength={100} value={title} onChange={e=>setTitle(e.target.value)}/></label>
    <PartyIdentification key={fileRevision} file={file} onChange={setPartyConfirmation}/>
    {partyConfirmation&&<fieldset className="home-position"><legend>{knownRole?'审查立场':'请选择审查立场'}</legend>{availablePositions.map(p=><label key={p}><input type="radio" name="review-position" value={p} checked={position===p} onChange={()=>setPosition(p)}/><span>{p}</span></label>)}{position==='中立审查'&&<small>中立审查不判断仅适用于甲方或乙方的风险。</small>}</fieldset>}
    <details className="home-rule-summary" key={loadError?'error':'rules'} open={loadError||undefined}><summary><BookOpen/><span>合同审查规则<small>{loading?'正在读取规则…':loadError?'规则读取失败':'使用当前规则执行审查'}</small></span><span>查看规则</span></summary>{pack?.rules.map(r=><p key={r.id}>{r.title}</p>)}{loadError&&<Button type="button" variant="outline" onClick={()=>void load()}>重新加载规则</Button>}</details>
    <details className="home-more"><summary>更多信息 <span>负责人：{owner} · 期望完成：{deadline}</span></summary><div><label className="home-field">负责人<select value={owner} onChange={e=>setOwner(e.target.value)}>{owners.map(o=><option key={o}>{o}</option>)}</select></label><label className="home-field">期望完成日期<input required type="date" value={deadline} onChange={e=>setDeadline(e.target.value)}/></label></div></details>
    {error&&<p role="alert" className="form-error">{error}</p>}
    <footer className="home-confirm-actions"><Button type="button" variant="outline" disabled={replacing} onClick={()=>{if(window.confirm('放弃本次合同和已填写的设置，返回上传？'))onClose()}}>返回上传</Button><Button type="submit" disabled={busy||replacing||loading||loadError||!pack?.rules.length||!partyConfirmation||!position}>{busy?'正在提交审查…':'确认并开始审查'}<ArrowRight/></Button></footer><p className="home-note">将保存本次合同与审查配置，结果需人工复核。</p>
    </fieldset></form>
  return <Dialog open={dialogOpen} onOpenChange={open=>{if(!busy)setDialogOpen(open)}}><DialogContent className="review-launch-dialog" showCloseButton={!busy} onCloseAutoFocus={event=>{event.preventDefault();if(dialogOpen)return;onClose();if(trigger.current?.isConnected&&trigger.current!==document.body)trigger.current.focus();else document.querySelector<HTMLButtonElement>('.workbench-title-actions button:last-child')?.focus()}} onInteractOutside={event=>event.preventDefault()} onEscapeKeyDown={event=>{if(busy)event.preventDefault()}}><DialogHeader><DialogTitle>新建合同审阅</DialogTitle><DialogDescription>确认合同信息与审查标准，再开始逐条审阅。</DialogDescription></DialogHeader>
    <ol className="review-launch-steps" aria-label="新建审阅步骤">{['上传合同','审查设置','确认发起'].map((label,index)=><li key={label} aria-current={step===index?'step':undefined} className={cn(step===index&&'current',step>index&&'complete')}><span>{step>index?<Check/>:index+1}</span>{label}{index<2&&<ChevronRight/>}</li>)}</ol>
    <form className="review-launch-form" onSubmit={event=>void submit(event)}><div className="review-launch-body" ref={panel}><fieldset disabled={busy}>
      {step===0&&<div className="launch-upload-step"><label className="launch-file-upload" onDragOver={event=>event.preventDefault()} onDrop={event=>{event.preventDefault();if(!busy)changeFile(event.dataTransfer.files[0]??null)}}><Upload/><strong>{file?file.name:'上传合同正文'}</strong><span>点击选择或拖入 DOC / DOCX 文件 · 最大 20 MB</span><input type="file" accept=".doc,.docx" aria-label="上传合同正文" onChange={event=>changeFile(event.target.files?.[0]??null)}/></label><label>合同名称<input required maxLength={100} value={title} onChange={event=>setTitle(event.target.value)} placeholder="例如：功率预测技术服务合同"/></label><p className="launch-helper">上传后自动识别签约主体，在下一步确认我方与相对方。</p><div className="launch-form-columns"><label>负责人<select value={owner} onChange={event=>setOwner(event.target.value)}>{owners.map(owner=><option key={owner}>{owner}</option>)}</select></label><label>期望完成日期<input required type="date" value={deadline} onChange={event=>setDeadline(event.target.value)}/></label></div><p className="launch-helper"><ShieldCheck/>正文与配置保存在服务端。</p></div>}
      <div hidden={step!==1}><PartyIdentification key={fileRevision} file={file} onChange={setPartyConfirmation}/></div>
      {step===1&&<div className="launch-settings-step"><div className="launch-section-heading"><h3>审查立场</h3><p>根据已确认的我方主体设置。</p></div><div className="launch-form-columns"><label>我方立场<select aria-label="我方立场" value={position??''} onChange={e=>setPosition(e.target.value as Position)}><option value="" disabled>请选择审查立场</option>{availablePositions.map(p=><option key={p}>{p}</option>)}</select></label></div>
        {loading?<p role="status">正在读取服务端规则…</p>:loadError?<div role="alert"><p>规则暂时无法读取。</p><Button type="button" variant="outline" onClick={()=>void load()}>重试</Button></div>:pack&&<section className="launch-confirm-rules"><h3>合同审查规则 · {pack.version}</h3><p>执行口径 {pack.execution_policy.version}</p>{pack.rules.map(r=><p key={r.id}>{r.id} · {r.title}</p>)}</section>}</div>}
      {step===2&&<div className="launch-confirm-step"><div className="launch-confirm-document"><FileText/><div><h3>{title}</h3><p>{file?.name}</p></div><span>{/\.doc$/i.test(file?.name??'')?'DOC':'DOCX'}</span></div><dl className="launch-confirm-fields"><div><dt>我方主体</dt><dd>{partyConfirmation?.ourName}</dd></div><div><dt>合同相对方</dt><dd>{counterpart}</dd></div><div><dt>我方立场</dt><dd>{position}</dd></div><div><dt>负责人 / 期望完成</dt><dd>{owner} · {deadline}</dd></div></dl><section className="launch-confirm-rules"><header><BookOpen/><h3>合同审查规则</h3><button type="button" onClick={()=>setStep(1)}>查看</button></header><p>规则 {pack?.version} · 执行口径 {pack?.execution_policy.version}</p><p>确认后自动启动合同审查，并进入审阅室查看进度。系统将保存本次使用的合同与规则版本，结果需人工复核。</p></section></div>}
    </fieldset>{error&&<p className="form-error" role="alert">{error}</p>}</div><footer className="review-launch-footer"><Button type="button" variant="ghost" disabled={busy} onClick={()=>{if(step>0){setStep(step-1);setError('')}else setDialogOpen(false)}}>{step>0?<><ArrowLeft/>上一步</>:'取消'}</Button><span>{step+1} / 3</span><Button type="submit" disabled={busy||(step>0&&(loading||loadError||!pack?.rules.length))}>{busy?(step===2?'正在提交审查…':'正在检查…'):step===2?'确认并开始审查':'下一步'}<ArrowRight/></Button></footer></form>
  </DialogContent></Dialog>
}
