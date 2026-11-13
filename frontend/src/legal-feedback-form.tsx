import { useEffect, useRef, useState } from 'react'
import { api, post, type Finding, type LegalFeedback, type LegalFeedbackInput, type LegalVerdict, type RevisionProposal, type ServerRun, type Version } from './backend-api'
import { Button } from './components/ui/button'

export const verdictLabels:Record<LegalVerdict,string>={agree:'同意判断',modify_suggestion:'修改建议文本',false_positive:'AI 判断错误（误报）',not_applicable:'本案不适用',business_acceptance:'商务接受风险',missed_issue:'补充漏审问题'}
export function LegalFeedbackForm({run,finding,proposal,version,disabled=false,initiallyOpen=false,hideTrigger=false}:{run:ServerRun;finding?:Finding;proposal?:RevisionProposal;version:Version|null;disabled?:boolean;initiallyOpen?:boolean;hideTrigger?:boolean}){
  const [open,setOpen]=useState(initiallyOpen),[verdict,setVerdict]=useState<LegalVerdict>(finding?'agree':'missed_issue')
  const [reason,setReason]=useState(''),[corrected,setCorrected]=useState(proposal?.after_text??finding?.suggested_text??''),[actor,setActor]=useState(''),[basis,setBasis]=useState('')
  const [blockId,setBlockId]=useState(''),[quote,setQuote]=useState('')
  const [history,setHistory]=useState<LegalFeedback[]>([]),[error,setError]=useState(''),[saving,setSaving]=useState(false),[saved,setSaved]=useState(false)
  const attempt=useRef<{serialized:string;key:string}|null>(null)
  useEffect(()=>{if(!open)return;let live=true;api<{items:LegalFeedback[]}>(`/runs/${run.id}/legal-feedback`).then(data=>{if(live)setHistory(data.items)}).catch(e=>{if(live)setError(String(e.message))});return()=>{live=false}},[open,run.id])
  async function submit(){
    setError('');setSaved(false)
    // Attachment evidence is outside the body version accepted by the feedback endpoint.
    let anchor=finding?.event_anchor??finding?.evidence.find(e=>version?.blocks.some(b=>b.id===e.block_id))
    if(verdict==='missed_issue'){
      const text=version?.blocks.find(b=>b.id===blockId)?.text??''
      const start=text.indexOf(quote)
      if(!quote||start<0||text.indexOf(quote,start+1)>=0){setError('请选择段落并填写可唯一定位的原文片段。');return}
      const charStart=[...text.slice(0,start)].length
      anchor={block_id:blockId,start:charStart,end:charStart+[...quote].length,quote}
    }
    if(!actor.trim()||!reason.trim()){setError('请填写填写人和反馈理由。');return}
    const body:Omit<LegalFeedbackInput,'idempotency_key'>={issue_id:verdict==='missed_issue'?undefined:finding?.id,proposal_id:verdict==='missed_issue'?undefined:(proposal?.proposal_id??proposal?.id),event_anchor:anchor,verdict,reason:reason.trim(),actor:actor.trim(),document_version_id:run.document_version_id,basis_refs:basis.split('\n').map(s=>s.trim()).filter(Boolean),...(verdict==='modify_suggestion'?{corrected_text:corrected}:{})}
    const serialized=JSON.stringify(body)
    if(attempt.current?.serialized!==serialized)attempt.current={serialized,key:crypto.randomUUID()}
    setSaving(true)
    try{
      const record=await post<LegalFeedback>(`/runs/${run.id}/legal-feedback`,{...body,idempotency_key:attempt.current.key})
      setHistory(items=>[...items.filter(item=>item.id!==record.id),record]);setSaved(true)
    }catch(e){setError(e instanceof Error?e.message:String(e))}finally{setSaving(false)}
  }
  const records=history.filter(item=>proposal?item.proposal_id===(proposal.proposal_id??proposal.id):finding?item.issue_id===finding.id:!item.issue_id)
  return <section className="legal-feedback">{!hideTrigger&&<Button variant="outline" size="sm" onClick={()=>setOpen(!open)}>{finding?'法务反馈与历史':'补充漏审问题与历史'}</Button>}{open&&<div className="legal-feedback-fields">
    <p>反馈用于积累待确认经验；处理状态请另行记录。填写人是自报标识。</p>
    <label>反馈结论<select value={verdict} disabled={disabled||saving} onChange={e=>setVerdict(e.target.value as LegalVerdict)}>{Object.entries(verdictLabels).filter(([key])=>finding||key==='missed_issue').map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
    {verdict==='missed_issue'&&<><label>原文段落<select value={blockId} disabled={disabled||saving} onChange={e=>setBlockId(e.target.value)}><option value="">请选择</option>{version?.blocks.map(b=><option key={b.id} value={b.id}>{b.text.slice(0,100)}</option>)}</select></label><label>精确原文片段<textarea value={quote} disabled={disabled||saving} onChange={e=>setQuote(e.target.value)}/></label></>}
    <label>反馈理由<textarea value={reason} disabled={disabled||saving} onChange={e=>setReason(e.target.value)}/></label>
    {verdict==='modify_suggestion'&&<label>修订文本（留空表示删除）<textarea value={corrected} disabled={disabled||saving} onChange={e=>setCorrected(e.target.value)}/></label>}
    <label>依据引用（每行一条）<textarea value={basis} disabled={disabled||saving} onChange={e=>setBasis(e.target.value)}/></label>
    <label>填写人<input value={actor} disabled={disabled||saving} onChange={e=>setActor(e.target.value)}/></label>
    <Button size="sm" disabled={disabled||saving} onClick={()=>void submit()}>{saving?'保存中…':'保存法务反馈'}</Button>
    {error&&<p role="alert">{error}</p>}{saved&&<p role="status">法务反馈已保存，正文与处理状态未改变。</p>}
    <h4>法务反馈历史（{records.length}）</h4>{records.map(item=><div key={item.id} className="review-decision-record"><strong>{verdictLabels[item.verdict]}</strong><p>{item.reason}</p>{item.corrected_text!==undefined&&item.corrected_text!==null&&<p>修订文本：{item.corrected_text===''?'（删除）':item.corrected_text}</p>}<small>{item.actor} · {new Date(item.created_at).toLocaleString('zh-CN')}</small></div>)}
  </div>}</section>
}
