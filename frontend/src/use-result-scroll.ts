import {useLayoutEffect,useRef,useState} from 'react'

type Anchor={key:string;attribute:string;top:number;scrollTop:number}
export function useResultScroll(runKey:string,active:boolean,sequence:number,followSelector?:string){
 const ref=useRef<HTMLDivElement>(null),following=useRef(true),programmatic=useRef(false)
 const anchor=useRef<Anchor|null>(null),last=useRef({runKey,sequence}),frame=useRef(0)
 const [unseen,setUnseen]=useState(false)
 function remember(){
  const el=ref.current;if(!el||el.hidden)return
  const top=el.getBoundingClientRect().top
  const nodes=el.querySelectorAll<HTMLElement>('[data-reading-anchor],[data-finding-id]')
  let node:HTMLElement|undefined
  for(const candidate of nodes){
   const box=candidate.getBoundingClientRect()
   if(!box.height||box.bottom<=top+8)continue
   if(node&&!node.contains(candidate))break
   node=candidate
   if(box.top>top+8)break
  }
  const attribute=node?.hasAttribute('data-reading-anchor')?'data-reading-anchor':'data-finding-id'
  anchor.current=node?{key:node.getAttribute(attribute)!,attribute,top:node.getBoundingClientRect().top-top,scrollTop:el.scrollTop}:null
 }
 function move(top:number){
  const el=ref.current;if(!el)return
  top=Math.max(0,Math.min(top,el.scrollHeight-el.clientHeight))
  // Reassigning even the same value interrupts native wheel/touch momentum.
  if(Math.abs(el.scrollTop-top)<.5)return
  programmatic.current=true;el.scrollTop=top
  cancelAnimationFrame(frame.current)
  frame.current=requestAnimationFrame(()=>{programmatic.current=false;remember()})
 }
 function latest(){const el=ref.current;if(!el)return;const target=followSelector?el.querySelector<HTMLElement>(followSelector):null;move(Math.max(el.scrollTop,target?el.scrollTop+target.getBoundingClientRect().bottom-el.getBoundingClientRect().bottom+16:el.scrollHeight))}
 function resume(){following.current=true;setUnseen(false);latest()}
 useLayoutEffect(()=>{
  const el=ref.current;if(!el)return
  const scroll=()=>{if(programmatic.current)return;if(el.scrollHeight-el.clientHeight-el.scrollTop>=48)following.current=false;remember()}
  const pause=()=>{following.current=false;programmatic.current=false;cancelAnimationFrame(frame.current);remember()}
  const wheel=(e:WheelEvent)=>{if(e.deltaY!==0)pause()}
  const key=(e:KeyboardEvent)=>{if(['ArrowUp','ArrowDown','PageUp','PageDown','Home','End',' '].includes(e.key))pause()}
  const selection=()=>{const selected=window.getSelection();if(selected&&!selected.isCollapsed&&el.contains(selected.anchorNode))pause()}
  el.addEventListener('scroll',scroll,{passive:true});el.addEventListener('wheel',wheel,{passive:true});el.addEventListener('keydown',key);el.addEventListener('pointerdown',pause);el.addEventListener('touchstart',pause,{passive:true});document.addEventListener('selectionchange',selection)
  remember()
  return()=>{el.removeEventListener('scroll',scroll);el.removeEventListener('wheel',wheel);el.removeEventListener('keydown',key);el.removeEventListener('pointerdown',pause);el.removeEventListener('touchstart',pause);document.removeEventListener('selectionchange',selection);cancelAnimationFrame(frame.current);programmatic.current=false}
 },[runKey])
 useLayoutEffect(()=>{
  const el=ref.current;if(!el)return
  const changed=last.current.sequence!==sequence
  if(last.current.runKey!==runKey){following.current=true;anchor.current=null;setUnseen(false)}
  last.current={runKey,sequence}
  if(el.hidden)return
  if(changed&&following.current&&active)latest()
  // Progress notices can shrink when the run finishes without a new event seq.
  // Stabilize those layouts too, not only streamed text renders.
  if(!following.current){
    const saved=anchor.current
    // Native scrolling updates scrollTop before dispatching its scroll event.
    // A render in that interval must not restore the previous reading position.
    if(saved&&Math.abs(el.scrollTop-saved.scrollTop)<.5){const node=el.querySelector<HTMLElement>(`[${saved.attribute}="${CSS.escape(saved.key)}"]`);if(node)move(el.scrollTop+node.getBoundingClientRect().top-el.getBoundingClientRect().top-saved.top)}
    if(changed&&active)setUnseen(true)
  }
  remember()
 })
 return {ref,unseen,resume,following}
}
