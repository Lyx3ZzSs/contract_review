import {AlertCircle,CheckCircle2,ChevronRight,Clock3,FileSearch,RefreshCw,X} from 'lucide-react'
import {Button} from './components/ui/button'

export type SubjectRecord={title:string;fields:{label:string;value:string}[];detail_id?:string}
export type SubjectResult={state:string;message:string;data:any;label?:string;queried_at?:string;last_attempt_at?:string;provider_code?:number;pages?:Record<string,any>;details?:Record<string,SubjectResult>}
export const subjectResultVisible=(result?:SubjectResult)=>result?.provider_code!==300005
export const subjectDate=(s?:string)=>s?new Date(s).toLocaleString('zh-CN'):'未查询'
export const subjectResultMessage=(result:SubjectResult)=>result.provider_code===300005?'暂未获取相关信息。':result.message
export const resultRecords=(result:SubjectResult):SubjectRecord[]=>Object.entries(result.pages??{}).sort(([a],[b])=>Number(a)-Number(b)).flatMap(([,page])=>page.records??[])
export function subjectResultStatus(result:SubjectResult){
 if(result.state==='empty')return '未发现相关记录'
 if(result.state==='ready')return `${result.data?.total??0} 条记录`
 if(result.state==='unavailable')return result.provider_code===300005?'暂未获取':'暂不可查询'
 if(result.state==='failed')return '查询失败'
 return '尚未查询'
}
export function subjectRiskCounts(results:SubjectResult[]){
 results=results.filter(subjectResultVisible)
 return {
  found:results.filter(r=>r.state==='ready'&&r.data?.total>0).length,
  clear:results.filter(r=>r.state==='empty').length,
  unknown:results.filter(r=>!['ready','empty'].includes(r.state)).length,
 }
}
function RiskIcon({state}:{state:string}){
 const Icon=state==='empty'?CheckCircle2:state==='ready'?FileSearch:['failed','unavailable'].includes(state)?AlertCircle:Clock3
 return <Icon aria-hidden="true"/>
}
export function SubjectRiskTile({result,selected,onClick}:{result:SubjectResult;selected:boolean;onClick:()=>void}){
 if(!subjectResultVisible(result))return null
 return <button type="button" className={`subject-risk-tile state-${result.state}`} aria-pressed={selected} aria-controls={selected?'subject-risk-detail':undefined} onClick={onClick}>
  <span className="subject-risk-icon"><RiskIcon state={result.state}/></span><span className="subject-risk-tile-copy"><strong>{result.label}</strong><span>{subjectResultStatus(result)}</span></span><ChevronRight className="subject-tile-chevron" aria-hidden="true"/>
 </button>
}
export function SubjectRecordFields({record}:{record:SubjectRecord}){
 return <dl className="subject-record-fields">{record.fields.map(f=><div key={f.label}><dt>{f.label}</dt><dd>{f.value}</dd></div>)}</dl>
}
export function SubjectRiskCard({module,result,busy,matched,onQuery,onDetail,onClose}:{module:string;result:SubjectResult;busy:boolean;matched:boolean;onQuery:(page?:number,refresh?:boolean)=>void;onDetail:(id:string)=>void;onClose?:()=>void}){
 const records=resultRecords(result),total=result.data?.total
 const failed=['failed','unavailable'].includes(result.state)
 const pages=Object.keys(result.pages??{}).map(Number)
 const next=pages.length?Math.max(...pages)+1:1
 if(!subjectResultVisible(result))return null
 return <section id="subject-risk-detail" className={`subject-risk-card state-${result.state}`} aria-label={`${result.label}详情`}>
  <div className="subject-detail-heading"><div><h4>{result.label}</h4><span className="subject-result-state">{subjectResultStatus(result)}</span></div>{onClose&&<Button variant="ghost" size="icon-sm" aria-label="收起风险详情" onClick={onClose}><X/></Button>}</div>
  {result.state!=='ready'&&result.state!=='empty'&&<p className={failed?'subject-inline-warning':'subject-muted'}>{subjectResultMessage(result)}</p>}
  {result.state==='empty'&&<p className="subject-muted">截至本次查询，天眼查未返回该企业的相关记录。</p>}
  <div className="subject-detail-toolbar"><span className="subject-meta">{failed?'最近尝试':'查询时间'} · {subjectDate(result.last_attempt_at||result.queried_at)}</span><Button variant="ghost" size="sm" disabled={busy||!matched} onClick={()=>onQuery(1,true)}><RefreshCw aria-hidden="true"/>{result.state==='not_queried'?'查询此项':failed?'重试此项':'更新此项'}</Button></div>
  {failed&&pages.length>0&&<p className="subject-inline-warning">本次查询未成功，以下保留 {subjectDate(result.queried_at)} 获取的记录。</p>}
  {records.length>0&&<div className="subject-risk-details"><p className="subject-record-count">已加载 {records.length} / {total} 条 <span>当前或历史状态以记录字段为准</span></p>
   {records.map((record,index)=>{const detail=record.detail_id?result.details?.[record.detail_id]:undefined;return <details className="subject-case" key={`${record.detail_id??record.title}-${index}`} open={index===0}>
    <summary><span className="subject-case-number">{String(index+1).padStart(2,'0')}</span><span>{record.title}</span><ChevronRight aria-hidden="true"/></summary><div className="subject-case-body"><SubjectRecordFields record={record}/>
    {module==='bankruptcy'&&record.detail_id&&<><Button variant="outline" size="sm" disabled={busy||!matched} onClick={()=>onDetail(record.detail_id!)}>{detail?.state==='ready'?'读取案件详情':detail?'重试案件详情':'查询案件详情'}</Button>{detail&&<>{detail.state==='ready'?<><p className="subject-meta">详情查询于 {subjectDate(detail.queried_at)}</p><SubjectRecordFields record={detail.data.record}/></>:<p role="status" className="subject-inline-warning">{subjectResultMessage(detail)}</p>}</>}</>}
   </div></details>})}
   {records.length<total&&<Button className="subject-load-more" variant="outline" disabled={busy||!matched} onClick={()=>onQuery(next,false)}>加载更多记录</Button>}
  </div>}
 </section>
}
