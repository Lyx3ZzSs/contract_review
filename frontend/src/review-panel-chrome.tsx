import { CircleAlert, MoreHorizontal } from 'lucide-react'
import { DropdownMenu } from 'radix-ui'
import { Button } from './components/ui/button'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

export function ReviewPanelActions({host,children}:{host:HTMLElement|null;children:ReactNode}){
  if(!host)return null
  return createPortal(<DropdownMenu.Root>
    <DropdownMenu.Trigger asChild><Button variant="ghost" size="icon-sm" aria-label="审查结果更多操作"><MoreHorizontal/></Button></DropdownMenu.Trigger>
    <DropdownMenu.Portal><DropdownMenu.Content className="result-options-menu" align="end" sideOffset={6}>{children}</DropdownMenu.Content></DropdownMenu.Portal>
  </DropdownMenu.Root>,host)
}
export function ReviewVersionNotice({children}:{children:ReactNode}){
  return <div className="result-stale-notice" role="status"><CircleAlert/><span>{children}</span></div>
}
