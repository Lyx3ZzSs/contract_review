import {ChevronRight,RefreshCw,UsersRound} from 'lucide-react'
import {Button} from './components/ui/button'
import {subjectDate,subjectResultMessage,subjectResultVisible,type SubjectResult} from './subject-risk-card'
export const extraNames:Record<string,string>={ownership:'企业属性',scale:'企业规模',shareholders:'股东信息'}
const types:Record<number,string>={1:'中央企业',2:'地方国有企业',3:'中央部委',4:'地方政府',5:'民营企业',6:'其他',7:'事业单位',8:'个体工商户'}
function extraSummary(key:string,result?:SubjectResult){
 if(!result)return '尚未查询'
 if(result.state==='unavailable')return result.provider_code===300005?'暂未获取':'暂不可查询'
 if(result.state==='failed')return '查询失败'
 if(result.state==='empty')return '未发现记录'
 if(result.state==='ready')return key==='ownership'?types[result.data.companyType]??'未提供':key==='scale'?String(result.data):`${result.data.total} 位股东`
 return '尚未查询'
}
const contributions=(items:any[]|undefined)=>(items??[]).map(c=>[c.amomon,c.percent,c.time].filter(v=>v!==null&&v!==undefined&&v!=='').join(' · ')).join('；')||'未提供'
export function SubjectCompanyDetails({modules,busy,matched,onQuery}:{modules:Record<string,SubjectResult>;busy:boolean;matched:boolean;onQuery:(module:string,page:number,refresh:boolean)=>void}){
 const entries=Object.entries(extraNames).filter(([key])=>subjectResultVisible(modules[key]))
 if(!entries.length)return null
 return <section className="subject-section" aria-label="企业资料"><div className="subject-section-heading"><h3>企业资料</h3><span className="subject-meta">股权与经营信息</span></div><div className="subject-extra-list">
 {entries.map(([key,label])=>{
  const result=modules[key],pages=result?.pages??{},items=Object.entries(pages).sort(([a],[b])=>Number(a)-Number(b)).flatMap(([,p])=>p.items??[]),failed=result&&['failed','unavailable'].includes(result.state)
  return <details key={key} className={`subject-extra state-${result?.state??'not_queried'}`}>
   <summary><span className="subject-extra-label">{key==='shareholders'&&<UsersRound aria-hidden="true"/>}{label}</span><span className="subject-extra-value">{extraSummary(key,result)}</span><ChevronRight aria-hidden="true"/></summary>
   <div className="subject-extra-body"><div className="subject-detail-toolbar"><span className="subject-meta">{key==='shareholders'?'工商登记来源':'来源：天眼查'}{result?.queried_at&&` · ${subjectDate(result.queried_at)}`}</span><Button variant="ghost" size="sm" disabled={busy||!matched} onClick={()=>onQuery(key,1,true)}><RefreshCw aria-hidden="true"/>{!result?'查询':failed?'重试':'更新'}</Button></div>
    {result&&result.state!=='ready'&&<p className={failed?'subject-inline-warning':'subject-muted'}>{subjectResultMessage(result)}</p>}
    {!result&&<p className="subject-muted">查询后可查看{label}。</p>}
    {failed&&items.length>0&&<p className="subject-inline-warning">本次查询未成功，以下保留此前已获取的记录。</p>}
    {key!=='shareholders'&&result?.state==='ready'&&<p className="subject-extra-result">{extraSummary(key,result)}</p>}
    {key==='shareholders'&&items.length>0&&<><p className="subject-record-count">已加载 {items.length} / {result!.data.total} 位股东</p>{items.map((item,i)=><div className="subject-shareholder" key={i}><div className="subject-shareholder-title"><span className="subject-case-number">{String(i+1).padStart(2,'0')}</span><strong>{item.name}</strong></div><dl className="subject-record-fields"><div><dt>认缴出资</dt><dd>{contributions(item.capital)}</dd></div><div><dt>实缴出资</dt><dd>{contributions(item.capitalActl)}</dd></div></dl></div>)}{items.length<result!.data.total&&<Button className="subject-load-more" variant="outline" disabled={busy||!matched} onClick={()=>onQuery(key,Math.max(...Object.keys(pages).map(Number))+1,false)}>加载更多股东</Button>}</>}
   </div>
  </details>
 })}</div></section>
}
