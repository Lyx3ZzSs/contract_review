import type {Evidence,Finding} from './backend-api'
import {anchorKey} from './review-follow'
export type ReadingLocation={anchor:Evidence;title:string;related?:Evidence[]}
export type ReferenceVisit={origin:ReadingLocation;destination:ReadingLocation;phase:'locating'|'viewing'|'returning'|'paused'|'error';message?:string}
export function stableIssueOrder(previous:string[],issues:Finding[]){
 const present=new Map(issues.map(i=>[i.id,i]))
 const ids=[...previous,...issues.map(i=>i.id).filter(id=>!previous.includes(id))]
 return ids.flatMap(id=>present.has(id)?[present.get(id)!]:[])
}
export function createReferenceNavigator({locate,pause,cancel,changed}:{locate:(location:ReadingLocation,valid:()=>boolean)=>Promise<boolean>;pause:()=>void;cancel:()=>void;changed:(visit:ReferenceVisit|null)=>void}){
 let visit:ReferenceVisit|null=null,generation=0,disposed=false
 const publish=()=>{if(!disposed)changed(visit?{...visit}:null)}
 async function move(returning:boolean){
  if(!visit||disposed)return false
  const n=++generation,valid=()=>!disposed&&n===generation
  cancel();pause();visit={...visit,phase:returning?'returning':'locating',message:undefined};publish()
  const destination=returning?visit.origin:visit.destination
  try{
   const ok=await locate(destination,valid)
   if(!valid())return false
   if(ok){visit=returning||anchorKey(visit!.origin.anchor)===anchorKey(visit!.destination.anchor)?null:{...visit!,phase:'viewing'};publish();return true}
   visit={...visit!,phase:'error',message:'编辑器未确认定位完成，请重试。已保留返回原文的入口。'}
  }catch(e){if(!valid())return false;visit={...visit!,phase:'error',message:e instanceof Error?e.message:String(e)}}
  publish();return false
 }
 return {
  open(origin:ReadingLocation,destination:ReadingLocation){
   visit={origin:visit?.origin??origin,destination,phase:'locating'}
   return move(false)
  },
  back:()=>move(true),retry:()=>move(false),
  checkpoint:()=>visit?{origin:anchorKey(visit.origin.anchor),destination:anchorKey(visit.destination.anchor)}:null,
  restore(saved:{origin:string;destination:string},locations:ReadingLocation[]){
   const origin=locations.find(x=>anchorKey(x.anchor)===saved.origin),destination=locations.find(x=>anchorKey(x.anchor)===saved.destination)
   if(origin&&destination){generation++;pause();visit={origin,destination,phase:'paused',message:'已恢复核对记录，可重新定位证据或返回原条款。'};publish()}
  },
  interrupt(){if(visit){generation++;cancel();visit={...visit,phase:'paused',message:'已暂停定位，可重新定位或返回原文。'};publish()}},
  clear(){generation++;cancel();visit=null;publish()},
  dispose(){disposed=true;generation++;cancel()},
 }
}
