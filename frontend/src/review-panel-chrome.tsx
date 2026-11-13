import { CircleAlert, FileText, MoreHorizontal, Plus } from 'lucide-react'
import { DropdownMenu } from 'radix-ui'
import { Button } from './components/ui/button'
import type { ReactNode } from 'react'

export function ReviewPanelHeading({position,children}:{position?:string;children:ReactNode}){
  return <header className="result-panel-heading"><div><h2>审查结果</h2><p>我方：{position??'以合同信息为准'}</p></div>
    <DropdownMenu.Root><DropdownMenu.Trigger asChild><Button variant="ghost" size="icon-sm" aria-label="审查结果更多操作"><MoreHorizontal/></Button></DropdownMenu.Trigger><DropdownMenu.Portal><DropdownMenu.Content className="result-options-menu" align="end" sideOffset={6}>{children}</DropdownMenu.Content></DropdownMenu.Portal></DropdownMenu.Root>
  </header>
}
export function ReviewPanelFooter({disabled,onSupplement,onHistory}:{disabled:boolean;onSupplement:()=>void;onHistory:()=>void}){
  return <footer className="result-panel-actions"><Button variant="ghost" disabled={disabled} onClick={onSupplement}><Plus/>补充审查意见</Button><Button variant="ghost" onClick={onHistory}><FileText/>审查记录</Button></footer>
}
export function ReviewVersionNotice({children,disabled,onReview,submitting=false}:{children:ReactNode;disabled:boolean;onReview?:()=>void;submitting?:boolean}){
  return <div className="result-stale-notice" role="status"><CircleAlert/><span>{children}</span>{onReview&&<button disabled={disabled} onClick={onReview}>{submitting?'正在提交…':'保存并重审'}</button>}</div>
}
