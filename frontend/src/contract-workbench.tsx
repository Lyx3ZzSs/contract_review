import { createReviewPoller } from './review-polling'
import { createRemote } from './backend-api'
import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowUpDown, ArrowRight, ArrowUp, ArrowUpRight, CalendarDays, CheckCheck, ChevronLeft, ChevronRight, CircleHelp, Clock3, FileCheck2, FileText, LayoutDashboard, Plus, Search, ShieldCheck, SlidersHorizontal, Scale, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from './components/ui/button'
import { Badge } from './components/reui/badge'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from './components/ui/dialog'
import { Toaster } from './components/ui/sonner'
import { ContractQueueCard } from './components/reui/contract-queue-card'
import { contractTypes, owners, loadContracts, type ContractStatus, type WorkbenchContract } from './workbench-data'
import { cn } from './lib/utils'
import './workbench.css'
import { NewReviewDialog, type ReviewSubmission } from './new-review-dialog'

const statuses: ContractStatus[] = ['待审阅','审阅中','待业务确认','已完成']
function StatusBadge({status}: {status:ContractStatus}) {
  return <span className={cn('queue-status',`status-${statuses.indexOf(status)}`)}><i/>{status}</span>
}
function RiskSummary({item}: {item:WorkbenchContract}) {
  if(item.status==='已完成')return <span className="queue-complete"><CheckCheck/>已完成审阅</span>
  return <span className="queue-muted">{item.total?`待处理 ${item.total-item.processed} 项`:item.note}</span>
}

export function ContractWorkbench({onOpen,onRules,startWithRuleSet}: {onOpen:(item:WorkbenchContract)=>void;onRules:()=>void;startWithRuleSet?:string}) {
  const [contracts,setContracts] = useState<WorkbenchContract[]>([])
  const [loading,setLoading] = useState(true)
  const [loadError,setLoadError] = useState(false)
  const [query,setQuery] = useState('')
  const [scope,setScope] = useState('全部合同')
  const [status,setStatus] = useState('全部状态')
  const [type,setType] = useState('全部类型')
  const [owner,setOwner] = useState('全部负责人')
  const [pendingOnly,setPendingOnly] = useState(false)
  const [filtersOpen,setFiltersOpen] = useState(false)
  const [ascending,setAscending] = useState<boolean | null>(null)
  const [page,setPage] = useState(0)
  const [selected,setSelected] = useState<string|null>(null)
  const [formItem,setFormItem] = useState<WorkbenchContract|null|undefined>(startWithRuleSet?null:undefined)
  const [help,setHelp] = useState(false)
  const detailTrigger = useRef<HTMLElement | null>(null)
  const formTrigger = useRef<HTMLElement | null>(null)
  const openDetails = (id: string, trigger: HTMLElement) => {detailTrigger.current=trigger;setSelected(id)}
  const selectedItem = contracts.find(c=>c.id===selected)
  const refresh = async () => {
    setLoading(true);setLoadError(false)
    try { setContracts(await loadContracts()) }
    catch { setLoadError(true) }
    finally { setLoading(false) }
  }
  useEffect(()=>{
    let disposed=false
    const poller=createReviewPoller(async()=>{
      const rows=await loadContracts()
      if(disposed)return false
      setContracts(rows);setLoading(false);setLoadError(false)
      return rows.some(c=>c.reviewActive)
    },()=>{if(!disposed){setLoadError(true);setLoading(false)}},4000)
    void poller.refresh()
    const resume=()=>{if(document.visibilityState==='visible')void poller.refresh()}
    window.addEventListener('focus',resume);document.addEventListener('visibilitychange',resume)
    return()=>{disposed=true;poller.stop();window.removeEventListener('focus',resume);document.removeEventListener('visibilitychange',resume)}
  },[])
  useEffect(()=>{setPage(0)},[query,scope,status,type,owner,pendingOnly,ascending])
  const reset = () => {setQuery('');setScope('全部合同');setStatus('全部状态');setType('全部类型');setOwner('全部负责人');setPendingOnly(false)}
  const activeFilters = query!==''||scope!=='全部合同'||status!=='全部状态'||type!=='全部类型'||owner!=='全部负责人'||pendingOnly
  const filtered = useMemo(()=>contracts.filter(c=>(scope!=='我的待办'||c.owner==='我'&&c.status!=='已完成')&&(scope!=='已完成'||c.status==='已完成')&&(status==='全部状态'||c.status===status)&&(type==='全部类型'||c.type===type)&&(owner==='全部负责人'||c.owner===owner)&&(!pendingOnly||c.total>c.processed)&&[c.title,c.number,c.counterpart,c.project].join(' ').toLowerCase().includes(query.trim().toLowerCase())).sort((a,b)=>ascending===null?0:ascending?a.deadline.localeCompare(b.deadline):b.deadline.localeCompare(a.deadline)),[contracts,query,scope,status,type,owner,pendingOnly,ascending])
  const pages = Math.max(1,Math.ceil(filtered.length/8))
  const currentPage = Math.min(page,pages-1)
  const visible = filtered.slice(currentPage*8,currentPage*8+8)
  let lastDocument: string | null = null
  try { lastDocument = localStorage.getItem('rixin:workbench:last-document') } catch { /* Optional preference. */ }
  const current = contracts.find(c=>c.id===lastDocument&&c.hasDocument) ?? contracts.find(c=>c.hasDocument&&c.status!=='已完成')
  const myTasks = contracts.filter(c=>c.owner==='我'&&c.status!=='已完成').length
  const openForm = (item:WorkbenchContract|null=null, trigger?: HTMLElement) => {
    const active = trigger ?? document.activeElement as HTMLElement
    formTrigger.current = active.closest('.contract-detail-drawer') ? detailTrigger.current : active
    setFormItem(item)
  }
  const openContract = (item:WorkbenchContract) => {if(item.hasDocument)onOpen(item);else {setSelected(null);openForm(item)}}
  const saveContract = async (submission:ReviewSubmission) => {
    const {title,counterpart,type,owner,deadline,file,configuration}=submission
    const id = formItem?.id ?? submission.requestId
    const date = new Date(configuration.createdAt).toLocaleDateString('sv-SE')
    const item:WorkbenchContract = {
      id,title,counterpart,number:formItem?.number??`RX-${date.replaceAll('-','')}-${id.slice(0,4).toUpperCase()}`,
      type,owner,deadline,department:formItem?.department??'待确认',updated:date,status:'待审阅',amount:formItem?.amount??'待确认',
      project:formItem?.project??'待确认',position:configuration.position,high:0,medium:0,low:0,total:0,processed:0,
      hasDocument:true,example:false,note:'已保存合同正文与审阅配置，可进行手动编辑、修订与批注。尚未生成 AI 审查结果。',reviewConfig:configuration,
    }
    const saved=await createRemote(item,file,submission.partySelection,submission.requestId)
    const next=[saved,...contracts.filter(c=>c.id!==id)]
    setContracts(next);setFormItem(undefined);toast.success('合同已保存，审查已启动');onOpen(saved)
  }

  return <div className="app-shell workbench-shell">
    <aside className="app-rail" aria-label="应用导航"><button type="button" className="brand-mark" aria-label="国能日新 · 合同工作台" onClick={reset}><img src="/favicon.png" alt="国能日新" width={36} height={36}/></button><div className="rail-items"><button className="rail-button current" aria-label="合同工作台" aria-current="page" title="合同工作台" onClick={reset}><LayoutDashboard/></button><button className="rail-button" aria-label="审查规则中心" title="审查规则中心" onClick={onRules}><Scale/></button></div><div className="rail-bottom"><button className="rail-button" aria-label="工作台使用说明" onClick={()=>setHelp(true)}><CircleHelp/></button><span className="user-avatar" title="法务审阅员">法</span></div></aside>
    <div className="workspace workbench-workspace">
      <header className="workspace-header"><div className="breadcrumb"><span className="brand-name">国能日新</span><span className="breadcrumb-slash">/</span><span>合同工作台</span></div><div className="header-right"><span><ShieldCheck/>企业法务工作空间</span><span className="header-separator"/><span>国能日新</span></div></header>
      <main className="workbench-main">
        <div className="workbench-title"><div><div className="workbench-eyebrow">LEGAL WORKSPACE</div><h1>合同工作台</h1><p>聚焦待办，推进每一份合同。</p></div><div className="workbench-title-actions"><Button variant="outline" aria-label="打开审查规则中心" onClick={onRules}><Scale/><span>审查规则</span></Button><Button disabled={loading||loadError} onClick={event=>openForm(null,event.currentTarget)}><Plus/>新建审阅</Button></div></div>
        <div className="workbench-stats" aria-label="合同队列概览">
          {[{label:'待我处理',value:myTasks,detail:'需要你推进的合同',icon:FileCheck2,action:()=>{reset();setScope('我的待办')}},{label:'审阅进行中',value:contracts.filter(c=>c.status==='审阅中').length,detail:'正在进行条款审阅',icon:Clock3,action:()=>{reset();setStatus('审阅中')}},{label:'有待处理审查项',value:contracts.filter(c=>c.total>c.processed&&c.status!=='已完成').length,detail:'风险与待补充材料',icon:ShieldCheck,action:()=>{reset();setPendingOnly(true)}},{label:'已完成审阅',value:contracts.filter(c=>c.status==='已完成').length,detail:'已完成法务审阅',icon:CheckCheck,action:()=>{reset();setScope('已完成')}}].map((stat,index)=><button className={cn('workbench-stat',index===0&&'stat-primary')} key={stat.label} onClick={stat.action}><div><span>{stat.label}</span><stat.icon/></div><strong>{loading||loadError?'—':stat.value}<small>份</small></strong><p>{stat.detail}<ArrowUpRight/></p></button>)}
        </div>
        {current&&<section className="continue-contract" aria-label="继续审阅"><div className="continue-icon"><FileText/></div><div className="continue-copy"><span>{current.status==='已完成'?'查看上次的审阅结果':'继续上次的审阅'} <i/> {current.number}</span><h2>{current.title}</h2></div><div className="continue-progress">{current.total>0?<><span>已处理 {current.processed} / {current.total} 项审查事项</span><div><i style={{width:`${current.processed/current.total*100}%`}}/></div></>:<span>{current.note}</span>}</div><Button variant="outline" onClick={()=>onOpen(current)}>{current.status==='已完成'?'查看结果':'继续审阅'}<ArrowRight/></Button></section>}
        <ContractQueueCard title="合同队列" description="按状态与优先级找到下一份需要处理的合同。" action={<span className="queue-source-note"><i/>服务端业务合同</span>} footer={<><span>共 {filtered.length} 份合同{activeFilters?' · 已筛选':''}</span><div className="queue-pagination"><span>每页 8 份</span><Button size="icon-sm" variant="outline" disabled={currentPage===0} aria-label="上一页" onClick={()=>setPage(currentPage-1)}><ChevronLeft/></Button><span>{currentPage+1} / {pages}</span><Button size="icon-sm" variant="outline" disabled={currentPage+1>=pages} aria-label="下一页" onClick={()=>setPage(currentPage+1)}><ChevronRight/></Button></div></>}>
          <div className="queue-tabs" aria-label="合同范围">{['全部合同','我的待办','已完成'].map(s=><button key={s} aria-pressed={scope===s} className={cn(scope===s&&'active')} onClick={()=>setScope(s)}>{s}<span>{s==='全部合同'?contracts.length:s==='我的待办'?myTasks:contracts.filter(c=>c.status==='已完成').length}</span></button>)}</div>
          <div className="queue-toolbar"><div className="queue-search"><Search/><input aria-label="搜索合同" value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜索合同名称、编号或相对方…"/>{query&&<button aria-label="清除搜索" onClick={()=>setQuery('')}><X/></button>}</div><div className="queue-filters"><select aria-label="审阅状态" value={status} onChange={e=>setStatus(e.target.value)}><option>全部状态</option>{statuses.map(s=><option key={s}>{s}</option>)}</select><Button variant="outline" size="sm" aria-expanded={filtersOpen} onClick={()=>setFiltersOpen(!filtersOpen)}><SlidersHorizontal/>筛选{(type!=='全部类型'||owner!=='全部负责人'||pendingOnly)&&<span className="filter-dot"/>}</Button>{activeFilters&&<button className="queue-reset" onClick={reset}>重置</button>}</div></div>
          {filtersOpen&&<div className="queue-advanced"><label>合同类型<select value={type} onChange={e=>setType(e.target.value)}><option>全部类型</option>{contractTypes.map(t=><option key={t}>{t}</option>)}</select></label><label>负责人<select value={owner} onChange={e=>setOwner(e.target.value)}><option>全部负责人</option>{owners.map(o=><option key={o}>{o}</option>)}</select></label><label className="queue-checkbox"><input type="checkbox" checked={pendingOnly} onChange={e=>setPendingOnly(e.target.checked)}/>仅看有待处理审查项</label></div>}
          {loading?<div className="queue-empty" role="status">正在读取合同队列…</div>:loadError?<div className="queue-empty" role="alert"><h3>合同队列暂时无法读取</h3><p>请重试，已保存的合同不会被覆盖。</p><Button variant="outline" onClick={()=>void refresh()}>重新加载</Button></div>:visible.length===0?<div className="queue-empty"><Search/><h3>{contracts.length?'没有找到匹配的合同':'暂无业务合同'}</h3><p>{contracts.length?'试试其他关键词，或清除筛选条件。':'上传第一份合同，开始审阅。'}</p>{contracts.length?<Button variant="outline" onClick={reset}>清除筛选</Button>:<Button onClick={event=>openForm(null,event.currentTarget)}><Plus/>新建审阅</Button>}</div>:<div className="queue-table-scroll" tabIndex={0} role="region" aria-label="合同队列表格，可左右滚动"><table className="contract-queue-table"><thead><tr><th>合同 / 相对方</th><th>审阅状态</th><th>审查待办</th><th>负责人</th><th aria-sort={ascending===null?'none':ascending?'ascending':'descending'}><button onClick={()=>setAscending(!ascending)}>期望完成 {ascending===null?<ArrowUpDown/>:ascending?<ArrowUp/>:<ArrowDown/>}</button></th><th><span className="sr-only">操作</span></th></tr></thead><tbody>{visible.map(item=><tr key={item.id} data-contract-id={item.id}><td><div className="queue-contract-cell"><span className="queue-file-icon"><FileText/></span><div><button className="queue-contract-title" onClick={event=>openDetails(item.id,event.currentTarget)}>{item.title}</button><div className="queue-contract-meta"><span>{item.number}</span><i/>{item.counterpart}</div></div></div></td><td><StatusBadge status={item.status}/></td><td><RiskSummary item={item}/></td><td><span className="queue-owner"><span className={cn('owner-avatar',item.owner==='我'&&'is-me')}>{item.owner==='待分配'?'—':item.owner.slice(-1)}</span>{item.owner}</span></td><td><span className="queue-deadline"><CalendarDays/>{item.deadline.slice(5).replace('-',' / ')}</span></td><td><button className="queue-row-action" aria-label={`查看${item.title}详情`} onClick={event=>openDetails(item.id,event.currentTarget)}>详情<ChevronRight/></button></td></tr>)}</tbody></table></div>}
        </ContractQueueCard>
        <div className="workbench-footnote"><ShieldCheck/>业务列表与统计来自服务端合同；测试数据不计入。</div>
      </main>
    </div>
    <Dialog open={!!selectedItem} onOpenChange={open=>{if(!open)setSelected(null)}}><DialogContent className="contract-detail-drawer" onCloseAutoFocus={event=>{event.preventDefault();if(formItem===undefined&&detailTrigger.current?.isConnected)detailTrigger.current.focus()}}>{selectedItem&&<><DialogHeader><span className="detail-eyebrow">合同详情 <span>服务端保存</span></span><DialogTitle>{selectedItem.title}</DialogTitle><DialogDescription>{selectedItem.number}</DialogDescription></DialogHeader><div className="detail-scroll"><div className="detail-status-row"><StatusBadge status={selectedItem.status}/><span>{selectedItem.type}</span></div><dl className="contract-detail-fields">{selectedItem.partyDetails&&<div><dt>我方主体</dt><dd>{selectedItem.partyDetails.our_name}</dd></div>}<div><dt>合同相对方</dt><dd>{selectedItem.counterpart}{selectedItem.partyDetails?.needs_reconfirmation&&<small>（正文已变更，主体信息需重新核对）</small>}</dd></div><div><dt>所属业务</dt><dd>{selectedItem.department}</dd></div><div><dt>关联项目</dt><dd>{selectedItem.project}</dd></div><div><dt>合同金额</dt><dd>{selectedItem.amount}</dd></div><div><dt>我方立场</dt><dd>{selectedItem.position}</dd></div><div><dt>负责人</dt><dd>{selectedItem.owner==='我'?'我 · 法务审阅员':selectedItem.owner}</dd></div><div><dt>期望完成</dt><dd>{selectedItem.deadline}</dd></div></dl><section className="detail-risk-box"><h3><ShieldCheck/>审阅摘要</h3><RiskSummary item={selectedItem}/><p>{selectedItem.note}</p>{selectedItem.total>0&&<div className="detail-progress"><span>已处理事项</span><strong>{selectedItem.processed} / {selectedItem.total}</strong></div>}</section>{selectedItem.resultSummary&&<section className="detail-result-note"><h3>结果 R{selectedItem.resultSummary.revision} · {selectedItem.resultSummary.conclusion}</h3><p>{selectedItem.resultSummary.opinion}</p><small>{selectedItem.status==='已完成'?'已完成审阅':'历史结果 · 当前已重新开启审阅'}</small></section>}{selectedItem.reviewConfig&&<section className="detail-review-config"><h3>审阅配置</h3><p>{selectedItem.reviewConfig.position}</p><p>合同审查规则 · 实际版本见审查批次</p></section>}<section className="detail-document"><h3>合同正文</h3><div><FileText/><span>{selectedItem.hasDocument?'DOCX 正文已就绪':'尚未上传对应正文'}<small>{selectedItem.hasDocument?'支持编辑、修订、批注及导出':'上传 DOCX 后即可开始审阅'}</small></span><Badge variant="outline">DOCX</Badge></div></section></div><div className="detail-footer"><Button variant="outline" onClick={()=>setSelected(null)}>返回队列</Button><Button onClick={()=>openContract(selectedItem)}>{selectedItem.hasDocument?(selectedItem.status==='已完成'&&selectedItem.resultSummary?'查看审阅结果':'进入审阅室'):'上传正文并审阅'}<ArrowRight/></Button></div></>}</DialogContent></Dialog>
    {formItem!==undefined&&<NewReviewDialog item={formItem} preset={startWithRuleSet} onSubmit={saveContract} onClose={()=>{setFormItem(undefined);requestAnimationFrame(()=>{if(formTrigger.current?.isConnected)formTrigger.current.focus()})}}/>}
    <Dialog open={help} onOpenChange={setHelp}><DialogContent><DialogHeader><DialogTitle>工作台使用说明</DialogTitle><DialogDescription>集中管理合同，跟进审阅进度。</DialogDescription></DialogHeader><p>点击合同名称可查看详情，选择「进入审阅室」处理正文。可按状态、类型、负责人和待处理事项筛选队列。</p><p>「新建审阅」支持上传 DOCX，每份合同独立保存。新上传合同保存至服务器，可发起合同审查。账号权限尚未接入。</p></DialogContent></Dialog><Toaster position="bottom-right"/>
  </div>
}
