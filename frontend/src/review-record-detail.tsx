import {useEffect,useState} from 'react'
import {ArrowLeft,ArrowRight} from 'lucide-react'
import {Button} from './components/ui/button'
import {api,type ServerRun,type ServerResult,type ReviewDecision,type Version} from './backend-api'
import {ExportDialog} from './export-dialog'
import {reviewItems} from './review-issues'
import {ReviewRecordBadge} from './review-records-page'
import {createReviewPoller} from './review-polling'
import type {ReviewRecord} from './review-records-data'
import {contractRoute} from './app-route'
import {decisionLabels} from './review-status'
interface RecordSnapshot {record:ReviewRecord;run:ServerRun;version:Version;result:(ServerResult&{decisions?:ReviewDecision[]})|null}
export function ReviewRecordDetail({id,onNavigate}:{id:string;onNavigate:(hash:string)=>void}){
 const [exportOpen,setExportOpen]=useState(false)
 const [snapshot,setSnapshot]=useState<RecordSnapshot|null>(null),[error,setError]=useState(''),[retry,setRetry]=useState(0)
 useEffect(()=>{let alive=true;const poller=createReviewPoller(async()=>{
   const record=await api<ReviewRecord>(`/review-records/${id}`)
   const [run,version,result]=await Promise.all([api<ServerRun>(`/runs/${id}`),api<Version>(`/versions/${record.document_version_id}`),record.result_id?api<ServerResult&{decisions?:ReviewDecision[]}>(`/results/${record.result_id}`):Promise.resolve(null)])
   if(!alive)return false
   setSnapshot({record,run,version,result});setError('');return ['queued','running'].includes(record.status)
 },e=>{if(alive)setError(e instanceof Error?e.message:'记录无法读取')},4000);void poller.refresh();const refresh=()=>{if(document.visibilityState==='visible')void poller.refresh()};window.addEventListener('focus',refresh);document.addEventListener('visibilitychange',refresh);return()=>{alive=false;poller.stop();window.removeEventListener('focus',refresh);document.removeEventListener('visibilitychange',refresh)}},[id,retry])
 if(!snapshot||error)return <section className="record-detail"><Button variant="ghost" onClick={()=>onNavigate('#/records')}><ArrowLeft/>返回审查记录</Button><div className="records-empty" role={error?'alert':'status'}>{error||'正在读取本轮记录…'}{error&&<Button variant="outline" onClick={()=>setRetry(n=>n+1)}>重试</Button>}</div></section>
 const {record,run,version,result}=snapshot
 const frozen=result?.review_snapshot??run
 const decisions=result?.decisions??frozen.decisions??run.decisions??[]
 const last=new Map(decisions.map(d=>[d.finding_id,d]))
 const issues=reviewItems(frozen).filter(f=>!['merged','retracted'].includes(f.review_state??''))
 return <section className="record-detail"><Button variant="ghost" onClick={()=>onNavigate('#/records')}><ArrowLeft/>返回审查记录</Button><header className="record-detail-header"><div><h1>{record.title}</h1><p>第 {record.round_number} 轮 · {new Date(record.created_at).toLocaleString('zh-CN')} · {record.counterpart}</p></div><div><ReviewRecordBadge record={record}/><Button variant="outline" onClick={()=>setExportOpen(true)}>导出本轮文件</Button></div></header><ExportDialog open={exportOpen} onOpenChange={setExportOpen} cid={record.contract_id} runId={record.id} versionId={record.document_version_id} historical/><div className="record-detail-note">本页只读展示本轮送审正文与{result?'标记完成时保存的':'本轮'}审查意见。{!record.is_latest?'该合同已有更新轮次，可在记录列表中查看。':'继续处理请进入当前审阅室。'}</div>
 {record.is_latest&&<div style={{marginTop:16}}><Button onClick={()=>onNavigate(contractRoute(record.contract_id))}>进入当前审阅室<ArrowRight/></Button></div>}
 {result&&<section className="record-completion"><h2>人工审阅记录</h2><p>{result.reviewer&&<>{result.reviewer} · </>}标记完成于 {new Date(result.created_at).toLocaleString('zh-CN')} · 标记完成不等同于无风险。</p>{result.opinion&&<p>审阅意见：{result.opinion}</p>}{result.reservations&&<p>保留事项：{result.reservations}</p>}<a href={`/api/v1/versions/${encodeURIComponent(result.document_version_id)}/file`}>下载标记完成时的 DOCX</a></section>}
 <div className="record-detail-grid"><section className="record-document"><h2>本轮送审正文</h2><article aria-label="本轮送审正文文本">{version.blocks.length?version.blocks.map(b=><p key={b.id}>{b.text}</p>):<p>该版本没有可展示的正文文字，请下载原始文件查看。</p>}</article><a href={`/api/v1/versions/${encodeURIComponent(version.id)}/file`}>下载本轮送审 DOCX</a></section><section className="record-findings" aria-label="本轮审查意见"><h2>{result?'完成时保存的审查意见':'本轮审查意见'}</h2>{run.error&&<p role="alert" className="form-error">{run.error.message}</p>}{['queued','running'].includes(run.status)&&<p role="status">{run.progress||'AI 审查进行中，结果将自动更新。'}</p>}{run.module_errors?.map((e,i)=><p className="form-error" key={i}>{e.message}</p>)}{!issues.length&&!['queued','running'].includes(run.status)&&<p>{run.status==='failed'?'本轮未生成可展示的审查意见。':'本轮没有可展示的审查意见，请结合执行状态核对。'}</p>}{issues.map(f=><article className="record-finding" key={f.id}><h3>{f.presentation?.title||f.title||f.rule_id}</h3><p>{f.explanation}</p>{f.evidence?.map((e,i)=><blockquote key={i}>{e.quote}</blockquote>)}{f.suggested_text&&<p>修改建议：{f.suggested_text}</p>}<small>{last.has(f.id)?decisionLabels[last.get(f.id)!.action]??'已记录处理意见':['flag','insufficient_evidence'].includes(f.status)?'待处理':'无需处理'}</small>{last.get(f.id)?.note&&<p>处理说明{last.get(f.id)?.actor&&`（${last.get(f.id)!.actor}）`}：{last.get(f.id)!.note}</p>}</article>)}</section></div></section>
}
