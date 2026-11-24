import { ServerReview } from './server-review'
import { useEffect, useState } from 'react'
import { ArrowDownToLine, ArrowLeft, CheckCheck, Save, FileText, PencilLine, ShieldCheck } from 'lucide-react'
import { Button } from './components/ui/button'
import { Badge } from './components/reui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from './components/ui/tabs'
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from './components/ui/resizable'
import { Toaster } from './components/ui/sonner'
import {useOnlyoffice} from './editors/use-onlyoffice'
import './contract-editor.css'
import { ContractWorkbench } from './contract-workbench'
import type { WorkbenchContract } from './workbench-data'
import { RulesCenter } from './rules-center'
import { cn } from './lib/utils'
function useCompact() {
  const [compact,setCompact]=useState(()=>window.matchMedia('(max-width: 760px)').matches)
  useEffect(()=>{const q=window.matchMedia('(max-width: 760px)');const sync=()=>setCompact(q.matches);q.addEventListener('change',sync);return()=>q.removeEventListener('change',sync)},[])
  return compact
}

export default function App() {
  const [active, setActive] = useState<WorkbenchContract | null>(null)
  const [view,setView] = useState<'workbench'|'rules'>('workbench')
  const [preset,setPreset] = useState<string|undefined>()
  useEffect(() => { const siteTitle = '国能日新 · 智能合同审查'; document.title = active ? `${active.title} · ${siteTitle}` : view==='rules'?`审查规则中心 · ${siteTitle}`:siteTitle }, [active,view])
  const workbench = () => {setActive(null);setPreset(undefined);setView('workbench')}
  const rulesCenter = () => {setActive(null);setPreset(undefined);setView('rules')}
  const open = (item: WorkbenchContract) => {
    try { localStorage.setItem('rixin:workbench:last-document', item.id) } catch { /* Recent entry is optional. */ }
    setPreset(undefined);setActive(item)
  }
  return active
    ? <ReviewRoom key={active.id} item={active} onBack={workbench} onRules={rulesCenter}/>
    : view==='rules'?<RulesCenter onBack={workbench} onStart={id=>{setPreset(id);setView('workbench')}}/>
    : <ContractWorkbench onOpen={open} onRules={rulesCenter} startWithRuleSet={preset}/>
}

export function ReviewRoom({item,onBack,onRules}: {item:WorkbenchContract;onBack:()=>void;onRules:()=>void}) {
  const editor=useOnlyoffice(item.id,true)
  const {review}=editor
  const [remoteFinishRequest,setRemoteFinishRequest]=useState(0)
  const [remoteSummary,setRemoteSummary]=useState({total:0,pending:0,hasResult:false,active:!!item.reviewActive})
  const [leaving,setLeaving]=useState(false)
  const leave=async(destination=onBack)=>{
    if(leaving||editor.busy)return
    setLeaving(true)
    if(await editor.close())destination()
    else setLeaving(false)
  }
  const [panelTab,setPanelTab]=useState('risks')
  const [mobileView,setMobileView]=useState(item.reviewActive?'risks':'document')
  const compact=useCompact()
  const documentPane=<section className="document-pane live-document" aria-label="合同正文">
    <div className="document-toolbar"><div className="toolbar-left"><span className="toolbar-document-title"><FileText/>{editor.file.name}</span></div></div>
    <div className="onlyoffice-editor-host" ref={editor.host}/>
    {!editor.ready&&<div className="editor-loading" role="status">{editor.error||editor.loadStage}{editor.error&&<><Button size="sm" variant="outline" onClick={()=>window.location.reload()}>重新加载</Button><><Button size="sm" variant="outline" onClick={()=>void editor.checkRecovery()}>检查未结束会话</Button>{editor.recovery&&<div><p>{editor.recovery.session_id?(editor.recovery.can_recover?'旧会话已离线。重新打开将使用最后确认保存的版本；未确认的副本请先下载核对。':'原窗口仍在线，请先在那里保存并关闭。'):'没有占用中的编辑会话。'}</p>{editor.recovery.candidates.map(c=><a key={c.id} href={c.download_url}>下载未确认副本 · {new Date(c.created_at).toLocaleString()}</a>)}{editor.recovery.can_recover&&<Button size="sm" variant="outline" onClick={()=>void editor.recoverSession()}>结束过期会话并重新打开</Button>}</div>}</></>}</div>}
    <div className="document-bottom"><span><span className={cn('editor-status-dot',editor.ready&&'ready')}/>{editor.ready?'正文已加载':'文档加载中'}</span><button className="editor-text-action" onClick={()=>{setPanelTab('revisions');setMobileView('risks')}}>修订与批注</button></div>
  </section>

  const reviewPane=<section className="review-pane" aria-label="审查面板">
    <Tabs value={panelTab} onValueChange={setPanelTab} className="review-tabs">
      <div className="review-tab-bar"><TabsList variant="line" aria-label="审查面板"><TabsTrigger value="risks">审查结果</TabsTrigger><TabsTrigger value="revisions"><PencilLine/>修订与批注</TabsTrigger></TabsList></div>
      <TabsContent value="risks" className="risk-tab-content"><ServerReview id={item.id} editor={editor} position={item.position} finishRequest={remoteFinishRequest} onFinishConsumed={()=>setRemoteFinishRequest(0)} onSummary={setRemoteSummary} onShowDocument={()=>setMobileView('document')} onRules={()=>void leave(onRules)} onRevisions={()=>setPanelTab('revisions')}/></TabsContent>
      <TabsContent value="revisions" className="revision-content">
        <div className="revision-intro"><h2>修订与批注</h2><p>在正文编辑器中查看和处理修订、添加批注。</p><Button variant="outline" onClick={()=>void editor.openNativeReview()}>打开审阅工具</Button><Button variant="outline" onClick={()=>void editor.openNativeComments()}>打开批注</Button></div>
      </TabsContent>
    </Tabs><div className="review-panel-footer"><ShieldCheck/><span>建议供审阅参考，最终判断由法务确认</span></div>
  </section>
  return <><div className="app-shell esign-review-room" inert={leaving}>
    <div className="workspace">
      <header className="esign-room-header"><div className="esign-room-brand"><Button variant="ghost" size="icon-sm" aria-label="返回工作台" disabled={editor.busy} onClick={()=>void leave()}><ArrowLeft/></Button><img src="/favicon.png" alt="国能日新"/><strong>国能日新</strong><span className="esign-brand-divider"/><span>合同智能审查</span><Badge variant="outline">AI</Badge></div><div className="contract-actions"><Button size="sm" variant="outline" disabled={!editor.ready||editor.busy||editor.readOnly||editor.saveStatus==='saved'} onClick={editor.retrySave}><Save/>{editor.readOnly?'只读':!editor.ready?'加载中…':editor.busy?'正在保存…':editor.saveStatus==='saved'?'已保存':editor.saveStatus==='error'?'重试保存':'保存'}</Button><Button size="sm" disabled={!editor.ready||editor.busy} onClick={()=>void editor.exportDocx()}><ArrowDownToLine/>导出 DOCX</Button><Button size="sm" data-complete-review disabled={!editor.ready||editor.busy||(editor.readOnly&&!review.completed)} onClick={()=>{setPanelTab('risks');setMobileView('risks');if(!review.completed)setRemoteFinishRequest(x=>x+1)}}><CheckCheck/>{review.completed?'查看定稿':'完成审阅'}</Button></div></header>
      {editor.readOnlyReason==='occupied'&&<div className="completed-document-note" role="status">打开时已有其他编辑会话，当前为只读查看，展示打开时已保存的正文，不实时同步后续修改。编辑者退出后，可返回工作台重新进入编辑。</div>}
      {review.completed&&<div className="completed-document-note">本次审阅已完成，当前正文只读。可在定稿记录中重新开启审阅，历史结果保持不变。</div>}
      {editor.saveStatus==='error'&&<div className="storage-error" role="alert">草稿保存失败，请重试或导出 DOCX 保留修改。<Button size="sm" variant="outline" onClick={editor.retrySave}>重试保存</Button><Button size="sm" variant="outline" onClick={()=>void editor.exportBackup()}>导出 DOCX 备份</Button></div>}
      {compact&&<div className="mobile-view-tabs"><Tabs value={mobileView} onValueChange={setMobileView}><TabsList aria-label="工作区域"><TabsTrigger value="document">合同正文</TabsTrigger><TabsTrigger value="risks">{remoteSummary.active?'审查进度':`待处理 ${remoteSummary.pending}`}</TabsTrigger></TabsList></Tabs></div>}
      <main className="main-content">
        <ResizablePanelGroup orientation="horizontal" className={cn('pane-group',compact&&'compact-panes',compact&&`show-${mobileView}`)} id="review-workspace"><ResizablePanel id="document" defaultSize="68%" minSize={compact?'0px':'340px'} className="document-panel">{documentPane}</ResizablePanel><ResizableHandle withHandle aria-label="调整正文与审查面板宽度"/><ResizablePanel id="review" defaultSize="32%" minSize={compact?'0px':'360px'} className="risk-panel">{reviewPane}</ResizablePanel></ResizablePanelGroup>
      </main>
      <footer className="workspace-footer"><span><span className="save-indicator" data-status={editor.error?'error':editor.saveStatus} aria-hidden="true"/>{editor.saveStatus==='saved'?'正文已保存至服务端':editor.saveStatus==='error'?'保存失败':editor.saveStatus==='saving'?'正在保存草稿…':'正在加载文档…'}</span><span>服务端合同</span><span className="footer-progress">{review.completed?'审阅已完成':remoteSummary.active?'AI 审查进行中':`待处理 ${remoteSummary.pending} 项`}</span></footer>
    </div>
    <Toaster theme="light" position="bottom-center" closeButton richColors/>
  </div>{leaving&&<div className="workbench-save-overlay" role="status">正在保存正文…</div>}</>
}
