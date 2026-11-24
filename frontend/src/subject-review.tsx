import {useEffect,useRef,useState} from 'react'
import {AlertCircle,ArrowRight,Building2,Check,ChevronRight,ClipboardCheck,Copy,Database,LoaderCircle,RefreshCw,Search,ShieldCheck} from 'lucide-react'
import {api,post,serverId} from './backend-api'
import {Button} from './components/ui/button'
import {SubjectRiskCard,SubjectRiskTile,subjectDate,subjectRiskCounts,subjectResultMessage,subjectResultVisible,type SubjectResult} from './subject-risk-card'
import {SubjectCompanyDetails,extraNames} from './subject-company-details'
import './subject-review.css'
type Check={id:string;name:string;version_id:string;matched:boolean;binding:string;queried_at:string;basic:SubjectResult;modules:Record<string,SubjectResult>;decision?:{action:string;note:string;at:string}}
type Info={version_id:string;parties:{our_name?:string;counterparties?:string[];needs_reconfirmation?:boolean};checks:Check[]}
const riskNames:Record<string,string>={dishonesty:'失信信息',execution:'被执行人',illegal:'严重违法',abnormal:'经营异常',tax:'税务非正常户',bankruptcy:'破产重整'}
const modules={...riskNames,...extraNames}
const decisionNames:Record<string,string>={confirmed:'已确认主体',needs_material:'待补材料',reviewed:'已核实'}
export function SubjectReview({id}:{id:string}){
 const [info,setInfo]=useState<Info|null>(null),[name,setName]=useState(''),[check,setCheck]=useState<Check|null>(null),[busy,setBusy]=useState(false),[progress,setProgress]=useState(''),[error,setError]=useState(''),[note,setNote]=useState(''),[selectedRisk,setSelectedRisk]=useState<string|null>(null),[decisionAction,setDecisionAction]=useState('needs_material'),[savedNote,setSavedNote]=useState(''),[queryStep,setQueryStep]=useState<number|null>(null)
 const cid=serverId(id),generation=useRef(0),detailHost=useRef<HTMLDivElement>(null),root=useRef<HTMLElement>(null)
 useEffect(()=>{if(selectedRisk)detailHost.current?.scrollIntoView({block:'nearest'})},[selectedRisk])
 const closeDetail=()=>{root.current?.querySelector<HTMLButtonElement>('.subject-risk-tile[aria-pressed=true]')?.focus();setSelectedRisk(null)}
 useEffect(()=>{const token=++generation.current;setInfo(null);setCheck(null);setError('');void api<Info>(`/contracts/${cid}/subjects`).then(x=>{if(token!==generation.current)return;setInfo(x);const n=x.parties.counterparties?.[0]??'';setName(n);setCheck(x.checks.find(c=>c.name===n)??null)}).catch(e=>{if(token===generation.current)setError(String(e.message))});return()=>{generation.current++}},[cid])
 const select=(n:string)=>{setName(n);setCheck(info?.checks.find(c=>c.name===n)??null);setNote('');setError('');setSelectedRisk(null);setSavedNote('')}
 const save=(c:Check)=>{setCheck(c);setInfo(i=>i?{...i,checks:[c,...i.checks.filter(x=>x.name!==c.name)]}:i)}
 const run=async(fn:(save:(c:Check)=>void,active:()=>boolean)=>Promise<void>)=>{const token=generation.current;const active=()=>token===generation.current;setBusy(true);setError('');setSavedNote('');setQueryStep(null);try{await fn(c=>{if(active())save(c)},active)}catch(e){if(active())setError(e instanceof Error?e.message:'查询失败')}finally{if(active()){setBusy(false);setProgress('');setQueryStep(null)}}}
 const query=(refresh=false)=>info&&run(async(save,active)=>{
  setQueryStep(0);setProgress('正在核对企业身份…')
  let c=await post<Check>(`/contracts/${cid}/subjects`,{name:name.trim(),document_version_id:info.version_id,refresh});save(c)
  if(c.basic.state!=='ready'||!c.matched)return
  const entries=Object.entries(modules)
  for(let i=0;i<entries.length&&active();i++){
   const [key]=entries[i];setQueryStep(i+1);setProgress('正在查询企业风险与资料…')
   c=await post<Check>(`/subject-checks/${c.id}/modules/${key}`,{});save(c)
  }
 })
 const queryModule=(m:string,page=1,refresh=false)=>check&&run(async save=>{setProgress(`正在查询${modules[m]}…`);save(await post<Check>(`/subject-checks/${check.id}/modules/${m}?page=${page}&refresh=${refresh}`,{}))})
 const queryDetail=(caseId:string)=>check&&run(async save=>{setProgress('正在查询破产案件详情…');save(await post<Check>(`/subject-checks/${check.id}/bankruptcy/${encodeURIComponent(caseId)}`,{}))})
 const decision=(action:string)=>check&&run(async save=>{setProgress('正在保存核查记录…');save(await post<Check>(`/subject-checks/${check.id}/decision`,{action,note}));setSavedNote('核查记录已保存')})
 const data=check?.basic.data
 const risks=Object.keys(riskNames).map(key=>[key,check?.modules[key]??{label:riskNames[key],state:'not_queried',message:'尚未查询',data:null}] as const).filter(([,result])=>subjectResultVisible(result))
 const counts=subjectRiskCounts(risks.map(([,r])=>r))
 const unknown=risks.filter(([,r])=>!['ready','empty'].includes(r.state))
 const selected=selectedRisk?risks.find(([key])=>key===selectedRisk):undefined
 const pending=Object.keys(modules).some(key=>subjectResultVisible(check?.modules[key])&&!['ready','empty'].includes(check?.modules[key]?.state??''))
 const latest=check?[check.queried_at,...Object.values(check.modules).map(r=>r.last_attempt_at||r.queried_at||'')].sort().at(-1):undefined
 const ready=check?.basic.state==='ready'
 const [copied,setCopied]=useState(false)
 const copyCode=async()=>{try{await navigator.clipboard.writeText(String(data.creditCode));setCopied(true)}catch{setError('复制失败，请选择信用代码后手动复制。')}}
 useEffect(()=>{setCopied(false)},[check?.id])
 return <section ref={root} className="subject-review" aria-label="主体审查" aria-busy={busy}>
  <header className="subject-panel-heading"><div><h2>主体审查</h2><p>企业身份与公开风险核查</p></div><span className="subject-source"><Database aria-hidden="true"/>天眼查</span></header>
  <div className="subject-scroll">
   <section className="subject-identity" aria-label="合同相对方">
    <div className="subject-identity-heading"><span className="subject-company-icon"><Building2 aria-hidden="true"/></span><div className="subject-company-name"><span className="subject-eyebrow">合同相对方</span>
     {info?.parties.counterparties?.length===1?<h3>{name}</h3>:<label><span className="sr-only">选择合同相对方</span>{info?.parties.counterparties?.length?<select disabled={busy} value={name} onChange={e=>select(e.target.value)}>{info.parties.counterparties.map(n=><option key={n}>{n}</option>)}</select>:<input disabled={busy||!info} value={name} onChange={e=>select(e.target.value)} placeholder={info?'填写签约企业全称':'正在读取合同主体…'}/>}</label>}
    </div></div>
    {ready&&<><div className="subject-identity-badges"><span className="subject-badge">{String(data.regStatus||'经营状态未提供')}</span><span className={`subject-badge ${check.matched?'is-matched':'is-warning'}`}>{check.matched?<Check aria-hidden="true"/>:<AlertCircle aria-hidden="true"/>}{check.matched?(check.binding==='manual_confirmed'?'已确认主体':'名称一致'):'待核对主体'}</span></div>
     <div className="subject-credit-code"><span>信用代码</span><code>{data.creditCode||'未提供'}</code>{data.creditCode&&<Button variant="ghost" size="icon-sm" aria-label={copied?'信用代码已复制':'复制统一社会信用代码'} title={copied?'已复制':'复制信用代码'} onClick={()=>void copyCode()}>{copied?<Check/>:<Copy/>}</Button>}</div>
     <dl className="subject-key-facts"><div><dt>法定代表人</dt><dd>{data.legalPersonName||'未提供'}</dd></div><div><dt>注册资本</dt><dd>{data.regCapital||'未提供'}</dd></div></dl>
     <details className="subject-registration"><summary>工商登记详情<ChevronRight aria-hidden="true"/></summary><dl className="subject-record-fields">{Object.entries({name:'登记名称',companyOrgType:'企业类型',actualCapital:'实缴资本',regLocation:'注册地址',businessScope:'经营范围'}).map(([key,label])=><div key={key}><dt>{label}</dt><dd>{String(data[key]??'未提供')}</dd></div>)}<div><dt>成立日期</dt><dd>{data.estiblishTime?new Date(data.estiblishTime).toLocaleDateString('zh-CN'):'未提供'}</dd></div></dl><p className="subject-meta">企业信息查询于 {subjectDate(check.queried_at)}</p></details>
    </>}
    <div className="subject-query-toolbar"><span className="subject-meta">{check?`最近查询 ${subjectDate(latest)}`:'查询企业身份、风险与股东信息'}</span><div><Button size="sm" disabled={busy||!info||name.trim().length<2} onClick={()=>void query(!!check&&!pending)}>{busy?<LoaderCircle className="subject-spin" aria-hidden="true"/>:<Search aria-hidden="true"/>}{busy?'查询中':check?(pending?'继续查询':'更新查询'):'查询主体'}</Button>{check&&pending&&<Button variant="ghost" size="icon-sm" aria-label="更新全部信息" title="重新查询全部企业信息" disabled={busy} onClick={()=>void query(true)}><RefreshCw/></Button>}</div></div>
   </section>
   {error&&<div role="alert" className="subject-notice is-error"><AlertCircle aria-hidden="true"/><p>{error}</p></div>}
   {busy&&<div className="subject-query-progress" role="status"><span><LoaderCircle className="subject-spin" aria-hidden="true"/>{progress}</span>{queryStep!==null&&<div role="progressbar" aria-label="主体查询进度" aria-valuenow={queryStep} aria-valuemin={0} aria-valuemax={10}><i style={{transform:`scaleX(${queryStep/10})`}}/></div>}</div>}
   {info?.parties.needs_reconfirmation&&<div className="subject-notice"><AlertCircle aria-hidden="true"/><p>正文主体已变化，请核对企业名称后查询。</p></div>}
   {check&&!ready&&<div className="subject-empty"><FileEmpty/><h3>{check.basic.state==='empty'?'暂未找到该企业':'企业信息未能获取'}</h3><p>{subjectResultMessage(check.basic)}</p><p>请核对合同主体名称后重新查询。</p></div>}
   {!check&&info&&!busy&&<div className="subject-empty"><ShieldCheck aria-hidden="true"/><h3>了解交易对方，再做签约判断</h3><p>查询后将在这里汇总公开风险信息，<br/>并提供企业登记与股东信息。</p></div>}
   {ready&&check&&<>
    {!check.matched&&<div className="subject-notice"><AlertCircle aria-hidden="true"/><div><strong>请先确认企业身份</strong><p>登记名称：{data.name}</p><p>曾用名：{data.historyNames||'未提供'}。请核对信用代码，确认与签约主体一致后再查询。</p><Button size="sm" variant="outline" disabled={busy} onClick={()=>void decision('confirmed')}>确认是该签约主体</Button></div></div>}
    <section className="subject-section" aria-label="风险概览"><div className="subject-section-heading"><h3>风险概览</h3><span className="subject-meta">已获取 {risks.length-counts.unknown} / {risks.length} 项</span></div>
     <div className="subject-risk-summary"><div className={counts.found?'has-records':''}><strong>{counts.found}<small>项</small></strong><span>有相关记录</span></div><div><strong>{counts.clear}<small>项</small></strong><span>未发现记录</span></div><div className={counts.unknown?'has-unknown':''}><strong>{counts.unknown}<small>项</small></strong><span>尚未获取</span></div></div>
     {unknown.length>0&&<div className="subject-coverage-note"><AlertCircle aria-hidden="true"/><p>{unknown.map(([key])=>riskNames[key]).join('、')}尚未获取，不能据此判断风险。</p></div>}
     <div className="subject-risk-grid">{risks.map(([key,result])=><SubjectRiskTile key={key} result={result} selected={selectedRisk===key} onClick={()=>setSelectedRisk(selectedRisk===key?null:key)}/>)}</div>
     {selected&&<div ref={detailHost}><SubjectRiskCard module={selected[0]} result={selected[1]} busy={busy} matched={check.matched} onQuery={(page,refresh)=>void queryModule(selected[0],page,refresh)} onDetail={id=>void queryDetail(id)} onClose={closeDetail}/></div>}
     <p className="subject-risk-footnote">点击项目查看明细与查询时间；同一案件可能出现在不同类别中。</p>
    </section>
    <SubjectCompanyDetails modules={check.modules} busy={busy} matched={check.matched} onQuery={(key,page,refresh)=>void queryModule(key,page,refresh)}/>
    <section className="subject-section subject-decision-section" aria-label="人工核查"><details className="subject-decision"><summary><ClipboardCheck aria-hidden="true"/><h3>人工核查</h3><span className="subject-meta">{check.decision?decisionNames[check.decision.action]:'未记录'}</span><ChevronRight aria-hidden="true"/></summary><div className="subject-decision-body">
     {check.decision&&<div className="subject-saved-decision"><span className="subject-badge">{decisionNames[check.decision.action]}</span><time>{subjectDate(check.decision.at)}</time>{check.decision.note&&<p>{check.decision.note}</p>}</div>}
     <label>核查说明<textarea disabled={busy} value={note} onChange={e=>setNote(e.target.value)} maxLength={2000} rows={3} placeholder="记录核验依据、需补充的材料或后续处理意见"/></label><div className="subject-decision-actions"><label><span className="sr-only">核查结论</span><select disabled={busy} value={decisionAction} onChange={e=>setDecisionAction(e.target.value)}><option value="needs_material">待补材料</option><option value="reviewed" disabled={!check.matched}>已核实</option></select></label><Button size="sm" disabled={busy||(decisionAction==='reviewed'&&!check.matched)} onClick={()=>void decision(decisionAction)}>保存核查记录<ArrowRight aria-hidden="true"/></Button></div>
    </div></details>{savedNote&&<p role="status" className="subject-save-message"><Check aria-hidden="true"/>{savedNote}</p>}</section>
    <footer className="subject-panel-footer"><Database aria-hidden="true"/><p>数据来源：天眼查。核查结果与人工记录将随完整审查意见书导出。</p></footer>
   </>}
  </div>
 </section>
}
function FileEmpty(){return <Search aria-hidden="true"/>}
