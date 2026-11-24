import {authFetch} from './auth-http'
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
  useEffect(()=>{
    const controller=new AbortController()
    setPreview(null);setOurIndex('');setOtherIndices([]);setError('')
    if(!file){setLoading(false);return ()=>controller.abort()}
    if(!/\.docx?$/i.test(file.name)||file.size>20*1024*1024){setLoading(false);setError('请选择 20 MB 以内的 DOC 或 DOCX。');return ()=>controller.abort()}
    setLoading(true)
    const form=new FormData();form.append('file',file)
    void authFetch('/api/v1/party-previews',{method:'POST',body:form,signal:controller.signal}).then(async response=>{
      const value=await response.json()
      if(!response.ok)throw new Error(typeof value.detail==='string'?value.detail:'主体识别失败，可手动填写。')
      if(!controller.signal.aborted){setPreview(value);if(!value.parties?.length)setManual(true)}
    }).catch(e=>{if(!controller.signal.aborted){setManual(true);setError(e instanceof TypeError?'主体识别服务无法连接，可重试或手动填写。':e.message)}})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false)})
    return ()=>controller.abort()
  },[file,retry])
  const candidates=preview?.parties??[]
  const own=manual?ourText.trim():ourIndex!==''?candidates[Number(ourIndex)]?.name??'':''
  const others=manual?[...new Set(otherText.split('\n').map(s=>s.trim()).filter(Boolean))]:otherIndices.map(i=>candidates[i]?.name).filter(Boolean)
  const invalidParty=others.includes(own)?'合同相对方与我方相同，请核对名称。':
    others.length>20?'最多可填写 20 个相对方。':
    others.some(name=>name.length>200)?'相对方名称不能超过 200 个字符。':''
  const valid=!!file&&!!own&&others.length>0&&!invalidParty
  const result=useMemo<PartyConfirmation|null>(()=>valid?{
    ourName:own,ourRole:manual?null:candidates[Number(ourIndex)]?.role??null,counterpart:others.join('、'),
    selection:{preview_id:manual?null:preview?.id??null,our_index:manual?null:Number(ourIndex),counterparty_indices:manual?[]:otherIndices,
      manual_our_name:manual?own:null,manual_counterparties:manual?others:null},
  }:null,[valid,own,others.join('\n'),ourIndex,manual,preview,otherIndices])
  useEffect(()=>onChange(result),[result,onChange])
  const chooseOur=(value:string)=>{
    setOurIndex(value)
    const ownName=candidates[Number(value)]?.name
    setOtherIndices(value!==''&&preview?.status==='ready'?candidates.flatMap((c,i)=>c.name!==ownName?[i]:[]):[])
  }
  return <section className="party-identification" aria-label="签约主体识别">
    <div className="launch-section-heading"><h3>签约主体</h3><p>选择你代表的签约方，再核对相对方。</p></div>
    <p role="status" className="party-status">{loading?(/\.doc$/i.test(file?.name??'')?'正在转换 DOC 并识别签约主体…':'正在识别签约主体…可先手动填写。'):error||preview?.error?.message||(preview?.status==='ready'?'已识别，待核对':preview?.status==='conflict'?'同一角色出现不同名称，请逐项选择并核对。':preview?.status==='partial'?'仅识别到部分主体，可补充手动填写。':'未识别到明确签约主体，请手动填写。')}</p>
    <div className="party-actions">{!loading&&file&&preview?.status!=='ready'&&<Button type="button" variant="outline" onClick={()=>setRetry(n=>n+1)}>重新识别</Button>}{(!manual||candidates.length>0)&&<Button type="button" variant="outline" onClick={()=>{
      if(!manual&&!ourText&&!otherText){setOurText(own);setOtherText(others.join('\n'))}
      setManual(!manual)
    }}>{manual?'使用识别结果':'手动填写'}</Button>}</div>
    {manual?<div className="party-manual"><label>我方主体全称<input aria-label="我方主体全称" maxLength={200} value={ourText} onChange={e=>{setOurText(e.target.value)}} placeholder="输入我方签约主体全称"/></label><label>合同相对方<textarea aria-label="合同相对方" value={otherText} onChange={e=>{setOtherText(e.target.value)}} placeholder="输入另一方全称；多方合同每行一个主体" maxLength={4200} rows={3}/></label><p>更换文件后需重新选择签约方。</p></div>:candidates.length>0&&<>
      <label>哪一方是我方<select aria-label="哪一方是我方" value={ourIndex} onChange={e=>chooseOur(e.target.value)}><option value="">请选择我方签约主体</option>{candidates.map((p,i)=><option key={i} value={i}>{p.role} · {p.name}</option>)}</select></label>
      {ourIndex!==''&&<fieldset className="party-choices"><legend>合同相对方（可多选）</legend>{candidates.filter(p=>p.name!==own||ourIndex==='').length===0?<p>暂无可选主体，可使用手动填写。</p>:candidates.map((p,i)=>p.name===own&&ourIndex!==''?null:<label key={i}><input type="checkbox" checked={otherIndices.includes(i)} disabled={ourIndex===''} onChange={e=>{setOtherIndices(v=>e.target.checked?[...v,i]:v.filter(n=>n!==i))}}/><span>{p.role} · {p.name}</span></label>)}</fieldset>}
    </>}
    {invalidParty&&<p className="form-error" role="alert">{invalidParty}</p>}
    {!!candidates.length&&<details className="party-evidence"><summary>识别原文与重新识别（{candidates.length} 个候选）</summary>{candidates.map((p,i)=><div key={i}><strong>{p.role} · {p.name}</strong><small>{p.source==='explicit'?'明确标记识别':'模型识别候选'}</small>{p.evidence.map((e,j)=><blockquote key={j}><small>段落 {e.block_id}</small>{e.quote}</blockquote>)}</div>)}{preview?.status==='ready'&&<Button type="button" variant="outline" onClick={()=>setRetry(n=>n+1)}>重新识别</Button>}</details>}
    {preview?.tracked_changes_present&&<p className="party-note">文档含修订：当前按包含插入、不含删除的建议文本识别，请核对最终签约名称。</p>}
    {/\.doc$/i.test(file?.name??'')&&<p className="party-note">DOC 将自动转换为 DOCX，审阅与导出使用转换后的版本。</p>}
  </section>
}
