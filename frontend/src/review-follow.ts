import type { Evidence, Finding } from './backend-api'
import type { ExecutionState } from './review-execution'
import {unitGuidance,type ReviewGuidance} from './review-guidance'
export type FollowTarget = {key:string;anchor:Evidence;title:string;unitId?:string;ready?:boolean;guidance?:ReviewGuidance}
export function anchorKey(e:Evidence){return `${e.block_id}:${e.start}:${e.end}`}
export function followTargets(state:ExecutionState|null):FollowTarget[]{
 if(!state)return []
 if(state.plan)return [...state.plan.units].sort((a,b)=>a.source_order-b.source_order).map(u=>({key:anchorKey(u.anchor),anchor:u.anchor,title:u.title?.slice(0,70)||'未编号段落',unitId:u.id,ready:(u.task_ids??[]).every(id=>['completed','failed'].includes(state.tasks[id]?.state)),guidance:unitGuidance(state,u)}))
 const issues=Object.values(state.issues).sort((a,b)=>((b as Finding&{first_seq?:number}).first_seq??0)-((a as Finding&{first_seq?:number}).first_seq??0))
 const targets:FollowTarget[]=[]
 for(const issue of issues){const anchor=issue.event_anchor??issue.evidence?.[0];if(anchor)targets.push({key:anchorKey(anchor),anchor,title:issue.title??'审查意见',guidance:unitGuidance(state,{id:'',title:'',source_order:0,block_ids:[anchor.block_id],anchor,task_ids:[],screening:''})})}
 for(const task of Object.values(state.tasks).sort((a,b)=>(a.first_seq??0)-(b.first_seq??0))){if(task.anchor&&task.state==='running')targets.push({key:anchorKey(task.anchor),anchor:task.anchor,title:task.title??'正在核查',guidance:{phase:'checking',eligible:true,reason:task.title??'正在核查相关条款',detail:'等待实际核查结果。',signature:task.id,related:0}})}
 return targets.filter((t,i)=>targets.findIndex(other=>other.key===t.key)===i)
}
// Manual navigation only. Execution snapshots never schedule editor actions.
export type FollowStatus={mode:'paused';message:string;target?:FollowTarget;pendingTarget?:FollowTarget}
export function createReviewFollower(locate:(target:FollowTarget,valid:()=>boolean)=>Promise<boolean>,changed:(status:FollowStatus)=>void,_interval=0,canNavigate:()=>boolean=()=>true,cancelNavigation:()=>void=()=>{}){
 let targets:FollowTarget[]=[],active=true,blocked:string|undefined,disposed=false,generation=0
 let status:FollowStatus={mode:'paused',message:'点击目录或原文引用查看正文'}
 const publish=()=>{if(!disposed)changed({...status})}
 function pause(message='定位已暂停'){generation++;cancelNavigation();status={...status,pendingTarget:undefined,message};publish()}
 async function select(target:FollowTarget){
  if(disposed||!active||blocked||!canNavigate())return false
  const n=++generation;cancelNavigation();const valid=()=>!disposed&&generation===n
  status={...status,pendingTarget:target,message:'正在定位原文'};publish()
  try{const ok=await locate(target,valid);if(!valid())return false;status={mode:'paused',target:ok?target:status.target,message:ok?'已定位所选原文':'定位未完成，请重试'};publish();return ok}
  catch{if(valid()){status={...status,pendingTarget:undefined,message:'定位未完成，请重试'};publish()}return false}
 }
 return {update(next:FollowTarget[],enabled=true,reason?:string,_terminal=false){targets=next;active=enabled;blocked=reason;if(!enabled||reason)pause(reason);else if(status.target){status={...status,target:next.find(t=>t.key===status.target?.key)??status.target};publish()}},select,
 advance(){const i=targets.findIndex(t=>t.key===status.target?.key);if(targets[i+1])return select(targets[i+1])},pause,
 toggle(){pause()},setPace(_pace:string){},checkpoint:()=>({targetKey:status.target?.key}),
 dispose(){disposed=true;generation++;cancelNavigation()}}
}
