import {toast} from 'sonner'
import { ServerReview } from './server-review'
import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowDownToLine, ArrowLeft, Save, FileText, LoaderCircle } from 'lucide-react'
import { Button } from './components/ui/button'
import { Badge } from './components/reui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from './components/ui/tabs'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from './components/ui/resizable'
import { Toaster } from './components/ui/sonner'
import {useOnlyoffice} from './editors/use-onlyoffice'
import './contract-editor.css'
import { LegalWorkspace } from './legal-workspace'
import { ReviewHome } from './review-home'
import { ReviewRecordsPage } from './review-records-page'
import { ReviewRecordDetail } from './review-record-detail'
import type { WorkbenchContract } from './workbench-data'
import { RulesCenter } from './rules-center'
import {remoteContract,serverId} from './backend-api'
import {SubjectReview} from './subject-review'
import {ExportDialog} from './export-dialog'
import {readAppRoute,contractRoute,createAppNavigation} from './app-route'
import { cn } from './lib/utils'
function useCompact() {
  const [compact,setCompact]=useState(()=>window.matchMedia('(max-width: 760px)').matches)
  useEffect(()=>{const q=window.matchMedia('(max-width: 760px)');const sync=()=>setCompact(q.matches);q.addEventListener('change',sync);return()=>q.removeEventListener('change',sync)},[])
  return compact
}

export default function App() {
  const [route,setRoute]=useState(()=>readAppRoute(location.hash))
  const [active,setActive]=useState<WorkbenchContract|null>(null)
  const [routeError,setRouteError]=useState(''),[attempt,setAttempt]=useState(0)
  const guard=useRef<()=>Promise<boolean>>(async()=>true)
  const navigation=useRef<ReturnType<typeof createAppNavigation>|null>(null)
  const registerGuard=useCallback((next:()=>Promise<boolean>)=>{guard.current=next;return()=>{if(guard.current===next)guard.current=async()=>true}},[])
  useEffect(()=>{const nav=createAppNavigation(window,setRoute,()=>guard.current());navigation.current=nav;return()=>{nav.dispose();navigation.current=null}},[])
  const navigate=(hash:string)=>{void navigation.current?.navigate(hash)}
  useEffect(()=>{
    let disposed=false
    setActive(null);setRouteError('')
    if(route.kind==='review')void remoteContract(route.id).then(item=>{
      if(disposed)return
      if(!item.hasDocument){setRouteError('该合同尚未上传正文。');return}
      setActive(item)
    }).catch(error=>{if(!disposed)setRouteError(error instanceof Error?error.message:'合同暂时无法读取')})
    return()=>{disposed=true}
  },[route,attempt])
  const current=route.kind==='review'&&active?.id===route.id?active:null
  useEffect(()=>{document.title=current?`${current.title} · 国能日新 · 智能合同审查`:route.kind==='rules'?'审查规则中心 · 国能日新 · 智能合同审查':route.kind==='records'||route.kind==='record'?'审查记录 · 国能日新 · 智能合同审查':'开始审查 · 国能日新 · 智能合同审查'},[current,route.kind])
  const workbench=()=>{navigate('#/')}
  const rulesCenter=()=>{navigate('#/rules')}
  const open=(item:WorkbenchContract)=>{
    try{localStorage.setItem('rixin:workbench:last-document',item.id)}catch{ /* Optional recent entry. */ }
    navigate(contractRoute(item.id))
  }
  if(route.kind==='review'&&current)return <ReviewRoom key={current.id} item={current} onBack={()=>navigate('#/records')} onRules={rulesCenter} registerNavigationGuard={registerGuard}/>
  if(route.kind==='review'||route.kind==='invalid')return <main className="route-state"><div role={routeError||route.kind==='invalid'?'alert':'status'}><h1>{route.kind==='invalid'?'页面地址无效':routeError?'暂时无法打开合同':'正在打开合同…'}</h1>{routeError&&<p>{routeError}</p>}<div>{routeError&&<Button variant="outline" onClick={()=>setAttempt(n=>n+1)}>重试</Button>}<Button variant="outline" onClick={workbench}>返回工作台</Button></div></div></main>
  return <LegalWorkspace active={route.kind==='rules'?'rules':route.kind==='records'||route.kind==='record'?'records':'home'} onNavigate={navigate}>{route.kind==='rules'?<RulesCenter onStart={()=>navigate('#/')}/>:route.kind==='records'?<ReviewRecordsPage onNavigate={navigate} onOpen={open}/>:route.kind==='record'?<ReviewRecordDetail key={route.id} id={route.id} onNavigate={navigate} onOpen={open}/>:<ReviewHome onOpen={open} registerNavigationGuard={registerGuard}/>}</LegalWorkspace>
}

export function ReviewRoom({item,onBack,onRules,registerNavigationGuard}: {item:WorkbenchContract;onBack:()=>void;onRules:()=>void;registerNavigationGuard?:(guard:()=>Promise<boolean>)=>()=>void}) {
  const editor=useOnlyoffice(item.id,true)
  const [exportOpen,setExportOpen]=useState(false)
  const [exportRunId,setExportRunId]=useState<string|undefined>(undefined)
  const [remoteSummary,setRemoteSummary]=useState({total:0,pending:0,hasResult:false,active:!!item.reviewActive})
  const [leaving,setLeaving]=useState(false)
  const leavePromise=useRef<Promise<boolean>|null>(null)
  const prepareLeave=async()=>{
    if(leavePromise.current)return leavePromise.current
    if(editor.busy)return false
    setLeaving(true)
    const work=async()=>{try{return await editor.close()}catch(error){toast.error(error instanceof Error?error.message:'退出文档失败，请重试');return false}finally{setLeaving(false);leavePromise.current=null}}
    leavePromise.current=work();return leavePromise.current
  }
  const leaveRef=useRef(prepareLeave);leaveRef.current=prepareLeave
  useEffect(()=>registerNavigationGuard?.(()=>leaveRef.current()),[registerNavigationGuard])
  const leave=(destination=onBack)=>{if(registerNavigationGuard)destination();else void prepareLeave().then(ok=>{if(ok)destination()})}
  const [panelTab,setPanelTab]=useState('risks')
  const [reviewActionsHost,setReviewActionsHost]=useState<HTMLDivElement|null>(null)
  const [mobileView,setMobileView]=useState(item.reviewActive?'risks':'document')
  const compact=useCompact()
  const documentPane=<section className="document-pane live-document" aria-label="合同正文">
    <div className="document-toolbar"><div className="toolbar-left"><span className="toolbar-document-title"><FileText/>{editor.file.name}</span></div>{!editor.ready&&<span className={cn("editor-load-status",editor.error&&"failed")} role="status" title={editor.error||editor.loadStage}>{!editor.error&&<LoaderCircle aria-hidden="true"/>}{editor.error?'加载未完成':editor.slow?'打开时间较长，请稍候…':editor.loadStage}</span>}</div>
    <div className="onlyoffice-editor-host" ref={editor.host} inert={!editor.ready&&!editor.needsInput} aria-label="文档编辑器"/>
    {editor.error&&<div className="editor-load-error" role="alert"><strong>{editor.documentVisible?'正文已打开，审阅功能暂不可用':'正文未能打开'}</strong><p>{editor.error}</p><div className="editor-load-error-actions"><Button size="sm" variant="outline" onClick={()=>void editor.reload()}>重新加载</Button><Button size="sm" variant="outline" onClick={()=>void editor.checkRecovery()}>检查未结束会话</Button>{editor.recovery&&<div><p>{editor.recovery.session_id?(editor.recovery.can_recover?'旧会话已离线。重新打开将使用最后确认保存的版本；未确认的副本请先下载核对。':'原窗口仍在线，请先在那里保存并关闭。'):'没有占用中的编辑会话。'}</p>{editor.recovery.candidates.map(c=><a key={c.id} href={c.download_url}>下载未确认副本 · {new Date(c.created_at).toLocaleString()}</a>)}{editor.recovery.can_recover&&<Button size="sm" variant="outline" onClick={()=>void editor.recoverSession()}>结束过期会话并重新打开</Button>}</div>}</div></div>}
    <div className="document-bottom"><span><span className={cn('editor-status-dot',editor.ready&&'ready')}/>{editor.ready?'正文已加载':editor.documentVisible?'正文已显示':'DOCX 文档'}</span></div>
  </section>

  const reviewPane=<section className="review-pane" aria-label="审查面板">
    <Tabs value={panelTab==='subjects'?'subjects':'risks'} onValueChange={setPanelTab} className="review-tabs">
      <div className="review-tab-bar">
        <TabsList variant="line" aria-label="审查面板"><TabsTrigger value="risks">审查结果</TabsTrigger><TabsTrigger value="subjects">主体审查</TabsTrigger></TabsList>
        <div ref={setReviewActionsHost} className="review-tab-actions"/>
      </div>
      <TabsContent value="risks" forceMount hidden={panelTab==='subjects'} className="risk-tab-content"><ServerReview id={item.id} editor={editor} actionsHost={reviewActionsHost} onRunChange={setExportRunId} onSummary={setRemoteSummary} onShowDocument={()=>setMobileView('document')} onRules={()=>void leave(onRules)}/></TabsContent>
      <TabsContent value="subjects" className="risk-tab-content"><SubjectReview id={item.id}/></TabsContent>
    </Tabs>
  </section>
  return <><div className="app-shell esign-review-room" inert={leaving}>
    <div className="workspace">
      <header className="esign-room-header"><div className="esign-room-brand"><Button variant="ghost" size="icon-sm" aria-label="返回审查记录" disabled={editor.busy} onClick={()=>void leave()}><ArrowLeft/></Button><img src="/favicon.png" alt="国能日新"/><strong>国能日新</strong><span className="esign-brand-divider"/><span>合同智能审查</span><Badge variant="outline">AI</Badge></div><div className="contract-actions"><Button size="sm" variant="outline" disabled={!editor.ready||editor.busy||editor.readOnly||editor.saveStatus==='saved'} onClick={editor.retrySave}><Save/>{editor.readOnly?'只读':!editor.ready?'加载中…':editor.busy?'正在保存…':editor.saveStatus==='saved'?'已保存':editor.saveStatus==='error'?'重试保存':'保存'}</Button><Button size="sm" disabled={!editor.ready||editor.busy} onClick={()=>setExportOpen(true)}><ArrowDownToLine/>导出</Button></div></header>
      {editor.readOnlyReason==='occupied'&&<div className="completed-document-note" role="status">打开时已有其他编辑会话，当前为只读查看，展示打开时已保存的正文，不实时同步后续修改。编辑者退出后，可返回工作台重新进入编辑。</div>}
      {editor.saveStatus==='error'&&<div className="storage-error" role="alert">草稿保存失败，请重试或导出 DOCX 保留修改。<Button size="sm" variant="outline" onClick={editor.retrySave}>重试保存</Button><Button size="sm" variant="outline" onClick={()=>void editor.exportBackup()}>导出 DOCX 备份</Button></div>}
      {compact&&<div className="mobile-view-tabs"><Tabs value={mobileView} onValueChange={setMobileView}><TabsList aria-label="工作区域"><TabsTrigger value="document">合同正文</TabsTrigger><TabsTrigger value="risks">{remoteSummary.active?'审查进度':`待处理 ${remoteSummary.pending}`}</TabsTrigger></TabsList></Tabs></div>}
      <main className="main-content">
        <ResizablePanelGroup orientation="horizontal" className={cn('pane-group',compact&&'compact-panes',compact&&`show-${mobileView}`)} id="review-workspace"><ResizablePanel id="document" defaultSize="68%" minSize={compact?'0px':'340px'} className="document-panel">{documentPane}</ResizablePanel><ResizableHandle withHandle aria-label="调整正文与审查面板宽度"/><ResizablePanel id="review" defaultSize="32%" minSize={compact?'0px':'360px'} className="risk-panel">{reviewPane}</ResizablePanel></ResizablePanelGroup>
      </main>
      <footer className="workspace-footer"><span><span className="save-indicator" data-status={editor.error?'error':editor.saveStatus} aria-hidden="true"/>{editor.error?'文档连接未就绪':editor.saveStatus==='saved'?'正文已保存至服务端':editor.saveStatus==='error'?'保存失败':editor.saveStatus==='saving'?'正在保存草稿…':'正在加载文档…'}</span><span>服务端合同</span><span className="footer-progress">{remoteSummary.active?'AI 审查进行中':`待处理 ${remoteSummary.pending} 项`}</span></footer>
    </div>
    <Toaster theme="light" position="bottom-center" closeButton richColors/>
  </div><ExportDialog open={exportOpen} onOpenChange={setExportOpen} cid={serverId(item.id)} runId={exportRunId} capture={editor.captureExportSnapshot} release={editor.releaseSnapshot}/>{leaving&&<div className="workbench-save-overlay" role="status">正在保存正文…</div>}</>
}
