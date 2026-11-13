import type { Finding, Evidence } from './backend-api'
export type ExecutionTask={id:string;title?:string;first_seq?:number;state:'queued'|'running'|'completed'|'failed';anchor?:Evidence;message?:string}
export type ExecutionState={schema_version:number;run_id:string;document_version_id:string;material_bundle_id?:string;attempt_id:string|null;seq:number;status:string;stale?:boolean;tasks:Record<string,ExecutionTask>;issues:Record<string,Finding>}
export type ExecutionEvent=Pick<ExecutionState,'run_id'|'document_version_id'|'attempt_id'|'seq'> & {type:string;payload:Record<string,any>}
// null means a missing/out-of-order event requires an authoritative snapshot.
export function reduceExecution(state:ExecutionState,event:ExecutionEvent):ExecutionState|null{
 if(event.run_id!==state.run_id||event.document_version_id!==state.document_version_id)return state
 if(event.seq<=state.seq)return state
 if(event.seq!==state.seq+1)return null
 if(event.type==='attempt_started')return {...state,seq:event.seq,attempt_id:event.attempt_id,status:'running',tasks:{},issues:{}}
 if(event.attempt_id!==state.attempt_id)return null
 const next={...state,seq:event.seq,tasks:{...state.tasks},issues:{...state.issues}}
 const data=event.payload
 if(event.type.startsWith('task_'))next.tasks[data.task_id]={first_seq:event.seq,...next.tasks[data.task_id],...data,id:data.task_id,state:({task_discovered:'queued',task_started:'running',task_completed:'completed',task_failed:'failed'} as const)[event.type as 'task_started']}
 if(event.type==='issue_upserted')next.issues[data.issue.id]=data.issue
 if(event.type==='issue_retracted')delete next.issues[data.issue_id]
 // Final result reconciliation is server-owned; do not infer it from counters.
 if(event.type.startsWith('run_'))return null
 return next
}
