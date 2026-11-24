import {AccountMenu} from './auth-gate'
import {useState,type ReactNode} from 'react'
import {CircleHelp,FileClock,SlidersHorizontal,UploadCloud} from 'lucide-react'
import {Button} from './components/ui/button'
import {Dialog,DialogContent,DialogHeader,DialogTitle,DialogDescription} from './components/ui/dialog'
import {Toaster} from './components/ui/sonner'
import './legal-workspace.css'
export function LegalWorkspace({active,onNavigate,children}:{active:'home'|'records'|'rules';onNavigate:(hash:string)=>void;children:ReactNode}){
 const [help,setHelp]=useState(false)
 return <div className="legal-workspace"><header className="legal-header"><button className="legal-brand" onClick={()=>onNavigate('#/')}><img src="/favicon.png" alt=""/><strong>国能日新</strong><span>合同智能审查</span></button><div className="legal-header-actions"><Button variant="outline" onClick={()=>setHelp(true)}><CircleHelp/>使用帮助</Button><AccountMenu/></div></header><div className="legal-layout"><aside className="legal-sidebar"><nav aria-label="主导航">{[{id:'home',href:'#/',label:'开始审查',Icon:UploadCloud},{id:'records',href:'#/records',label:'审查记录',Icon:FileClock},{id:'rules',href:'#/rules',label:'审查规则',Icon:SlidersHorizontal}].map(({id,href,label,Icon})=><a key={id} href={href} aria-current={active===id?'page':undefined} onClick={e=>{if(!e.metaKey&&!e.ctrlKey&&!e.shiftKey&&!e.altKey){e.preventDefault();onNavigate(href)}}}><Icon/>{label}</a>)}</nav><small>国能日新 · 法务工作空间</small></aside><main className="legal-main">{children}</main></div><Dialog open={help} onOpenChange={setHelp}><DialogContent><DialogHeader><DialogTitle>合同审查使用帮助</DialogTitle><DialogDescription>上传 DOC 或 DOCX，核对签约主体与立场，确认后开始审查。</DialogDescription></DialogHeader><p>审查记录按轮次保存。最新一轮可进入审阅室继续处理；历史轮次只读展示对应版本与意见。</p><p>AI 生成结果与人工审阅完成分别记录。标记完成不代表所有意见均已处理。</p></DialogContent></Dialog><Toaster position="bottom-right"/></div>
}
