import {useEffect,useRef,useState} from 'react'
import {createReferenceNavigator,type ReadingLocation,type ReferenceVisit} from './review-reference'
export function useReviewReference({scope,locations,locate,pause,cancel,subscribe,blocked}:{scope?:string;locations:ReadingLocation[];locate:(location:ReadingLocation,valid:()=>boolean)=>Promise<boolean>;pause:()=>void;cancel?:()=>void;subscribe?:(listener:()=>void)=>()=>void;blocked?:string}){
 const [visit,setVisit]=useState<ReferenceVisit|null>(null),controller=useRef<ReturnType<typeof createReferenceNavigator>|null>(null)
 const latest=useRef({locations,locate,pause,cancel});latest.current={locations,locate,pause,cancel}
 useEffect(()=>{
  const key=scope?`review-reference:1:${scope}`:undefined
  const value=createReferenceNavigator({locate:(target,valid)=>latest.current.locate(target,valid),pause:()=>latest.current.pause(),cancel:()=>latest.current.cancel?.(),changed:next=>{
   setVisit(next)
   if(key)try{const memory=value.checkpoint();if(memory)sessionStorage.setItem(key,JSON.stringify(memory));else sessionStorage.removeItem(key)}catch{/* Storage is optional. */}
  }})
  controller.current=value;setVisit(null)
  if(key)try{const memory=JSON.parse(sessionStorage.getItem(key)||'null');if(memory)value.restore(memory,latest.current.locations)}catch{/* Ignore obsolete or invalid progress. */}
  return()=>{value.dispose();controller.current=null}
 },[scope])
 useEffect(()=>subscribe?.(()=>controller.current?.interrupt()),[subscribe])
 useEffect(()=>{if(blocked)controller.current?.interrupt()},[blocked])
 return {visit,open:(origin:ReadingLocation,destination:ReadingLocation)=>controller.current?.open(origin,destination),back:()=>controller.current?.back(),retry:()=>controller.current?.retry(),clear:()=>controller.current?.clear()}
}
