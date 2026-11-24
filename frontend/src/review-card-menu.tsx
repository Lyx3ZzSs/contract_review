import {useEffect, useRef, type ReactNode} from 'react'
import {MoreHorizontal} from 'lucide-react'

/** Native disclosure keeps all secondary actions keyboard-accessible. */
export function ReviewCardMenu({label,children}:{label:string;children:ReactNode}){
 const ref=useRef<HTMLDetailsElement>(null)
 useEffect(()=>{
  const close=(event:PointerEvent)=>{if(ref.current&&!ref.current.contains(event.target as Node))ref.current.open=false}
  document.addEventListener('pointerdown',close)
  return()=>document.removeEventListener('pointerdown',close)
 },[])
 return <details ref={ref} className="review-card-menu" onKeyDown={e=>{if(e.key==='Escape'&&ref.current){ref.current.open=false;ref.current.querySelector('summary')?.focus()}}}>
  <summary aria-label={label} title={label}><MoreHorizontal aria-hidden="true"/></summary>
  <div className="review-card-menu-items" onClick={e=>{if((e.target as HTMLElement).closest('button:not(:disabled)')&&ref.current)ref.current.open=false}}>{children}</div>
 </details>
}
