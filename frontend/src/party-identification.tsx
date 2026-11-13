import { useEffect, useMemo, useState } from 'react'
import { Button } from './components/ui/button'
import type { PartyPreview, PartySelection } from './party-types'

export interface PartyConfirmation {selection: PartySelection; counterpart: string; ourName: string; ourRole: string | null}
export function PartyIdentification({file,onChange}: {file: File|null; onChange:(value:PartyConfirmation|null)=>void}) {
  const [preview,setPreview]=useState<PartyPreview|null>(null)
  const [loading,setLoading]=useState(false)
  const [error,setError]=useState('')
  const [retry,setRetry]=useState(0)
  const [manual,setManual]=useState(false)
  const [ourIndex,setOurIndex]=useState('')
  const [otherIndices,setOtherIndices]=useState<number[]>([])
  const [ourText,setOurText]=useState('')
  const [otherText,setOtherText]=useState('')
  const [confirmed,setConfirmed]=useState(false)
  useEffect(()=>{
    const controller=new AbortController()
    setPreview(null);setOurIndex('');setOtherIndices([]);setConfirmed(false);setError('')
    if(!file){setLoading(false);return ()=>controller.abort()}
    if(!file.name.toLowerCase().endsWith('.docx')||file.size>20*1024*1024){setLoading(false);setError('请选择 20 MB 以内的 DOCX。');return ()=>controller.abort()}
    setLoading(true)
    const form=new FormData();form.append('file',file)
    void fetch('/api/v1/party-previews',{method:'POST',body:form,signal:controller.signal}).then(async response=>{
      const value=await response.json()
      if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'主体识别失败，可手动填写。')
      if(!controller.signal.aborted)setPreview(value)
    }).catch(e=>{if(!controller.signal.aborted)setError(e instanceof TypeError?'主体识别服务无法连接，可重试或手动填写。':e.message)})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return ()=>controller.abort()
  },[file,retry])
  const candidates=preview?.parties??[]
  const own=manual?ourText.trim():ourIndex!==''?candidates[Number(ourIndex)]?.name??'':''
  const others=manual?[...new Set(otherText.split('\n').map(s=>s.trim()).filter(Boolean))]:otherIndices.map(i=>candidates[i]?.name).filter(Boolean)
  const valid=!!file&&!!own&&others.length>0&&others.length<=20&&!others.includes(own)&&others.every(n=>n.length<=200)&&(manual||ourIndex!=='')
  const result=useMemo<PartyConfirmation|null>(()=>confirmed&&valid?{
    ourName:own,ourRole:manual?null:candidates[Number(ourIndex)]?.role??null,counterpart:others.join('、'),
    selection:{preview_id:manual?null:preview?.id??null,our_index:manual?null:Number(ourIndex),counterparty_indices:manual?[]:otherIndices,
      manual_our_name:manual?own:null,manual_counterparties:manual?others:null},
  }:null,[confirmed,valid,own,others.join('\n'),ourIndex,manual,preview,otherIndices])
  useEffect(()=>onChange(result),[result,onChange])
  const chooseOur=(value:string)=>{
    setOurIndex(value);setConfirmed(false)
    const ownName=candidates[Number(value)]?.name
    setOtherIndices(value!==''&&preview?.status==='ready'?candidates.flatMap((c,i)=>c.name!==ownName?[i]:[]):[])
  }
  return <section className="party-identification" aria-label="签约主体识别">
    <div className="launch-section-heading"><h3>签约主体</h3><p>先确认哪一方是我方，再核对合同相对方。审查立场单独设置。</p></div>
    <p role="status" className="party-status">{loading?'正在识别签约主体…可先手动填写。':error||preview?.error?.message||(preview?.status==='ready'?'已识别，待核对':preview?.status==='conflict'?'同一角色出现不同名称，请逐项选择并核对。':preview?.status==='partial'?'仅识别到部分主体，可补充手动填写。':'未识别到明确签约主体，请手动填写。')}</p>
    <div className="party-actions"><Button type="button" variant="outline" disabled={loading||!file} onClick={()=>setRetry(n=>n+1)}>重新识别</Button><Button type="button" variant="outline" onClick={()=>{
      if(!manual){setOurText(own);setOtherText(others.join('\n'))}
      setManual(!manual);setConfirmed(false)
    }}>{manual?'使用识别结果':'手动填写'}</Button></div>
    {manual?<div className="party-manual"><label>我方主体全称<input aria-label="我方主体全称" maxLength={200} value={ourText} onChange={e=>{setOurText(e.target.value);setConfirmed(false)}} placeholder="输入我方签约主体全称"/></label><label>合同相对方<textarea aria-label="合同相对方" value={otherText} onChange={e=>{setOtherText(e.target.value);setConfirmed(false)}} placeholder="输入另一方全称；多方合同每行一个主体" maxLength={4200} rows={3}/></label><p>手填内容不会被识别结果覆盖。更换文件后需重新确认。</p></div>:<>
      <label>哪一方是我方<select aria-label="哪一方是我方" value={ourIndex} onChange={e=>chooseOur(e.target.value)}><option value="">请选择我方签约主体</option>{candidates.map((p,i)=><option key={i} value={i}>{p.role} · {p.name}</option>)}</select></label>
      <fieldset className="party-choices"><legend>合同相对方（可多选）</legend>{candidates.filter(p=>p.name!==own||ourIndex==='').length===0?<p>暂无可选主体，可使用手动填写。</p>:candidates.map((p,i)=>p.name===own&&ourIndex!==''?null:<label key={i}><input type="checkbox" checked={otherIndices.includes(i)} disabled={ourIndex===''} onChange={e=>{setOtherIndices(v=>e.target.checked?[...v,i]:v.filter(n=>n!==i));setConfirmed(false)}}/><span>{p.role} · {p.name}</span></label>)}</fieldset>
    </>}
    {!!candidates.length&&<details className="party-evidence"><summary>查看识别原文（{candidates.length} 个候选）</summary>{candidates.map((p,i)=><div key={i}><strong>{p.role} · {p.name}</strong><small>{p.source==='explicit'?'明确标记识别':'模型识别候选'}</small>{p.evidence.map((e,j)=><blockquote key={j}><small>段落 {e.block_id}</small>{e.quote}</blockquote>)}</div>)}</details>}
    {preview?.tracked_changes_present&&<p className="party-note">文档含修订：当前按包含插入、不含删除的建议文本识别，请核对最终签约名称。</p>}
    <p className="party-note">当前读取正文及表格文字，不读取图片和页眉页脚。未识别不代表合同未写明。</p>
    <label className="party-confirm"><input type="checkbox" checked={confirmed} disabled={!valid} onChange={e=>setConfirmed(e.target.checked)}/><span>我已核对本次文件中的我方主体与合同相对方</span></label>
  </section>
}
