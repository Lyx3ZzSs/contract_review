import { useState } from 'react'
import { api, type Evidence, type MaterialBundle } from './backend-api'
import { materialEvidence } from './review-issues'
import { Button } from './components/ui/button'

export function MaterialEvidencePreview({cid,bundleId,evidence}:{cid:string;bundleId?:string;evidence:Evidence}) {
  const [source,setSource]=useState<ReturnType<typeof materialEvidence>>(null)
  const [busy,setBusy]=useState(false),[error,setError]=useState('')
  async function load(){
    setBusy(true);setError('')
    try{
      if(!bundleId)throw new Error('历史记录未保存材料快照，无法读取此证据来源。')
      const bundle=await api<MaterialBundle>(`/contracts/${cid}/material-bundles/${bundleId}`)
      const resolved=materialEvidence(evidence,bundle.materials??[])
      if(!resolved)throw new Error('证据与本轮材料内容不一致或来源不可读，请核验原文件。')
      setSource(resolved)
    }catch(e){setError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}
  }
  return <div className="review-material-evidence"><Button size="sm" variant="ghost" disabled={busy} onClick={()=>void load()}>{busy?'正在读取材料…':source?'重新读取材料证据':'查看材料证据与来源'}</Button>{error&&<p role="alert">{error} <button onClick={()=>void load()}>重试</button></p>}{source&&<section><strong>外部材料 · {source.material.filename}</strong><p>只读预览 · 本轮资料快照</p><blockquote>{source.before}<mark>{source.quote}</mark>{source.after}</blockquote><a href={`/api/v1/contracts/${cid}/materials/${source.material.id}/file`} download={source.material.filename}>下载对应材料</a></section>}</div>
}
