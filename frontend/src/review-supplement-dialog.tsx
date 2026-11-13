import { issuePresentation, type SupplementMode } from './review-issue-presentation'
import { linkedBodyBlocks } from './review-issues'
import { useEffect, useRef, useState } from 'react'
import { api, post, type SupplementReceipt, type AttachmentLink, type Finding, type MaterialBundle, type MaterialVersion, type ServerRun, type Version } from './backend-api'
import { Button } from './components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from './components/ui/dialog'

export function ReviewSupplementDialog({cid,run,issue,initialMode,onClose,onSubmitted}:{cid:string;run:ServerRun;issue:Finding;initialMode:SupplementMode;onClose:()=>void;onSubmitted:(receipt:SupplementReceipt)=>Promise<void>}) {
  const [mode,setMode]=useState<SupplementMode>(initialMode)
  const baseline=useRef('')
  const [materials,setMaterials]=useState<MaterialVersion[]>([]),[blocks,setBlocks]=useState<Version['blocks']>([])
  const [selected,setSelected]=useState<string[]>([]),[linked,setLinked]=useState<string[]>([]),[statement,setStatement]=useState('')
  const [existingLinks,setExistingLinks]=useState<AttachmentLink[]>([])
  const [loaded,setLoaded]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('')
  const lock=useRef(false),request=useRef<{signature:string;key:string}|null>(null)
  const uploadKeys=useRef(new Map<string,string>())
  async function load(){
    setError('')
    try {
      const [rows,version,bundle]=await Promise.all([api<MaterialVersion[]>(`/contracts/${cid}/materials`),api<Version>(`/versions/${run.document_version_id}`),api<MaterialBundle>(`/contracts/${cid}/material-bundles/${run.material_bundle_id}`)])
      baseline.current=JSON.stringify({selected:[...bundle.material_version_ids].sort(),linked:[...linkedBodyBlocks(issue,bundle.links,version.blocks)].sort()});setMaterials(rows);setBlocks(version.blocks);setSelected(bundle.material_version_ids);setLinked(linkedBodyBlocks(issue,bundle.links,version.blocks));setExistingLinks(bundle.links.filter(l=>l.reference_name===(issue.attachment_name??issue.reference_name)&&!!l.target_material_version_id));setLoaded(true)
    }catch(e){setError(e instanceof Error?e.message:String(e))}
  }
  useEffect(()=>{void load()},[])
  const toggle=(values:string[],value:string)=>values.includes(value)?values.filter(x=>x!==value):[...values,value]
  async function upload(file:File){
    if(lock.current)return
    lock.current=true;setBusy(true);setError('')
    try{
      if(file.size>20*1024*1024)throw new Error('单个补充文件不能超过 20MB')
      const identity=`${file.name}:${file.size}:${file.lastModified}`
      if(!uploadKeys.current.has(identity))uploadKeys.current.set(identity,crypto.randomUUID())
      const form=new FormData();form.append('file',file);form.append('idempotency_key',uploadKeys.current.get(identity)!)
      const material=await api<MaterialVersion>(`/contracts/${cid}/materials`,{method:'POST',body:form})
      setMaterials(rows=>[...rows.filter(x=>x.id!==material.id),material]);setSelected(ids=>[...new Set([...ids,material.id])])
    }catch(e){setError(e instanceof Error?e.message:String(e))}finally{lock.current=false;setBusy(false)}
  }
  async function save(){
    if(lock.current)return
    lock.current=true;setBusy(true);setError('')
    try{
      const body={expected_bundle_id:run.material_bundle_id,material_version_ids:[...selected].sort(),linked_block_ids:[...new Set([...linked,...existingLinks.filter(l=>selected.includes(l.target_material_version_id!)).flatMap(l=>l.target_block_ids)])].sort(),statement:statement.trim(),actor:'法务审阅员'}
      const signature=JSON.stringify(body),storageKey=`review-supplement:${run.id}:${issue.id}`
      if(request.current?.signature!==signature){
        let saved=null
        try{saved=JSON.parse(sessionStorage.getItem(storageKey)??'null')}catch{}
        request.current=saved?.signature===signature?saved:{signature,key:crypto.randomUUID()}
        try{sessionStorage.setItem(storageKey,JSON.stringify(request.current))}catch{}
      }
      const result=await post<SupplementReceipt>(`/runs/${run.id}/issues/${issue.id}/supplements`,{...body,idempotency_key:request.current!.key})
      await onSubmitted(result);onClose()
    }catch(e){setError(e instanceof Error?e.message:String(e))}finally{lock.current=false;setBusy(false)}
  }
  const changed=!!statement.trim()||JSON.stringify({selected:[...selected].sort(),linked:[...linked].sort()})!==baseline.current
  const title=issuePresentation(issue,run.rule_snapshot?.rules.find(r=>r.id===issue.rule_id)?.title??issue.rule_id).title
  return <Dialog open onOpenChange={open=>{if(!open&&!busy)onClose()}}><DialogContent className="review-supplement-dialog"><DialogHeader><DialogTitle>补充核验信息</DialogTitle><DialogDescription>{title}。保存后对本轮正文和资料包重新审查；说明与关联仍需核验。</DialogDescription></DialogHeader>
    {error&&<div role="alert" className="form-error">{error}{!loaded&&<Button variant="outline" onClick={()=>void load()}>重新加载</Button>}</div>}
    {!loaded?<p role="status">正在读取本轮资料…</p>:<>
      <div className="review-supplement-tabs" role="group" aria-label="补充方式">{([['statement','添加说明'],['material','补充文件'],...(issue.attachment_name||issue.reference_name?[['link','关联内容']]:[])] as [SupplementMode,string][]).map(([key,label])=><button type="button" key={key} disabled={busy} aria-pressed={mode===key} onClick={()=>setMode(key)}>{label}</button>)}</div>
      <section hidden={mode==='statement'}><h3>已收材料</h3><p>选择本轮需要保留或关联的材料。仅 DOCX 可解析，其他格式登记为不可读。</p><div className="review-material-list">{materials.map(m=><label key={m.id}><input type="checkbox" disabled={busy} checked={selected.includes(m.id)} onChange={()=>setSelected(toggle(selected,m.id))}/><span>{m.filename}<small>{m.id.slice(0,8)} · {({parsed:'已解析',complete:'已解析',unsupported:'格式不支持 · 内容未核验',failed:'解析失败 · 内容未核验',partial:'部分可读 · 含无法读取内容'} as Record<string,string>)[m.parse_status]??m.parse_status}</small></span></label>)}{!materials.length&&<p>尚无外部补充材料。</p>}</div><label className="review-upload">上传补充文件<input type="file" disabled={busy} onChange={e=>{const f=e.target.files?.[0];if(f)void upload(f);e.target.value=''}}/></label></section>
      {(issue.attachment_name||issue.reference_name)&&<details className="review-block-picker" open={mode==='link'} hidden={mode!=='link'}><summary>关联正文中的附件内容（已选 {linked.length} 段）</summary><div className="review-material-list">{blocks.map(b=><label key={b.id}><input type="checkbox" disabled={busy} checked={linked.includes(b.id)} onChange={()=>setLinked(toggle(linked,b.id))}/><span><small>{b.id}</small>{b.text}</span></label>)}</div></details>}
      <label hidden={mode!=='statement'}>用户说明<textarea aria-label="用户说明" disabled={busy} rows={4} value={statement} onChange={e=>setStatement(e.target.value)} placeholder="例如：线下已提供，请核验本次上传的对应文件"/></label><p className="review-source-note">已选 {selected.length} 份材料、{linked.length} 段正文{statement.trim()?'，并附用户说明':''}。说明单独保存，不作为已核验的文档证据。</p>
      <Button disabled={busy||!changed} onClick={()=>void save()}>{busy?'正在保存…':'保存并重新核验'}</Button>
    </>}
  </DialogContent></Dialog>
}
