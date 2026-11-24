import type { Finding, Evidence, RevisionProposal } from './backend-api'
export type ReviewDraft={issue:Finding;revision:number;state:'generating'|'validating'|'failed';fields:Record<string,string>;first_seq:number;message?:string}
export type ReviewPhase={id:string;title:string;state:'queued'|'running'|'completed'|'failed';message?:string;updated_at?:string}
export type AnalysisArtifact={id:string;title:string;revision:number;state:'generating'|'validating'|'completed'|'failed';fields:Record<string,string>;sections:{title:string;text:string;evidence:Evidence[];check_id?:string;check_status?:'checked'|'insufficient_evidence'}[];message?:string;first_seq?:number}
export type ExecutionTask={id:string;rule_scope?:Record<string,string>;rule_observations?:Record<string,string>;event_id?:string;rule_id?:string;title?:string;first_seq?:number;state:'queued'|'running'|'completed'|'failed';anchor?:Evidence;message?:string;sections?:AnalysisArtifact['sections']}
export type ReviewUnit={id:string;title:string;number?:string;source_order:number;block_ids:string[];anchor:Evidence;task_ids:string[];screening:string}
export type ReviewCoverage={batch:number;block_ids:string[];state?:string;message?:string;topics?:{topic:string;status:'checked'|'not_applicable'|'insufficient_evidence';reason:string}[]}
export type ExecutionState={coverage?:ReviewCoverage[];phases?:Record<string,ReviewPhase>;artifacts?:Record<string,AnalysisArtifact>;plan?:{revision:number;units:ReviewUnit[];scope:string};schema_version:number;run_id:string;document_version_id:string;material_bundle_id?:string;attempt_id:string|null;seq:number;status:string;stale?:boolean;tasks:Record<string,ExecutionTask>;issues:Record<string,Finding>;drafts?:Record<string,ReviewDraft>;proposals?:Record<string,RevisionProposal>}
export type ExecutionEvent=Pick<ExecutionState,'run_id'|'document_version_id'|'attempt_id'|'seq'> & {type:string;payload:Record<string,any>}
// null means a missing/out-of-order event requires an authoritative snapshot.
export function reduceExecution(state:ExecutionState,event:ExecutionEvent):ExecutionState|null{
 if(event.run_id!==state.run_id||event.document_version_id!==state.document_version_id)return state
 if(event.seq<=state.seq)return state
 if(event.seq!==state.seq+1)return null
 if(event.type==='attempt_started')return {...state,seq:event.seq,attempt_id:event.attempt_id,status:'running',plan:undefined,tasks:{},issues:{},drafts:{},proposals:{},phases:{},artifacts:{},coverage:[]}
 if(event.attempt_id!==state.attempt_id)return null
 const next={...state,seq:event.seq}
 // Analysis deltas must not invalidate every risk card and its revision diff.
 if(event.type.startsWith('task_'))next.tasks={...state.tasks}
 if(event.type.startsWith('draft_')||event.type.startsWith('issue_'))next.drafts={...state.drafts}
 if(event.type.startsWith('issue_')){next.issues={...state.issues};next.proposals={...state.proposals}}

 const data=event.payload
 if(event.type==='coverage_updated')next.coverage=data.coverage
 if(event.type==='phase_updated')next.phases={...state.phases,[data.phase.id]:data.phase}
 if(event.type.startsWith('analysis_')){
  next.artifacts={...state.artifacts}
  const old=next.artifacts[data.artifact_id]
  if(event.type==='analysis_started')next.artifacts[data.artifact_id]=data.artifact
  else {
   if(!old){if(event.type!=='analysis_failed')return null;next.artifacts[data.artifact_id]={id:data.artifact_id,title:data.title,revision:data.revision,state:'failed',message:data.message,fields:{},sections:[]}}
   else {
    if(old.revision!==data.revision)return null
    const artifact={...old,fields:{...old.fields}}
    if(event.type==='analysis_delta')for(const change of data.changes){
     const text=artifact.fields[change.field]??''
     if(Array.from(text).length!==change.offset)return null
     artifact.fields[change.field]=text+change.text
    }
    if(event.type==='analysis_section')artifact.sections=[...old.sections,data.section]
    if(event.type==='analysis_validating'){artifact.state='validating';artifact.message=data.message}
    if(event.type==='analysis_completed'){artifact.state='completed';artifact.sections=data.sections;artifact.fields={};delete artifact.message}
    if(event.type==='analysis_failed'){artifact.state='failed';artifact.message=data.message;artifact.fields={}}
    next.artifacts[data.artifact_id]=artifact
   }
  }
 }
 if(event.type==='plan_ready')next.plan=data.plan
 if(event.type.startsWith('task_'))next.tasks[data.task_id]={first_seq:event.seq,...next.tasks[data.task_id],...data,id:data.task_id,state:({task_discovered:'queued',task_started:'running',task_completed:'completed',task_failed:'failed'} as const)[event.type as 'task_started']}
 if(event.type==='draft_started')next.drafts![data.issue_id]=data.draft
 if(['draft_delta','draft_validating','draft_failed'].includes(event.type)){
  const old=next.drafts![data.issue_id]
  if(!old||old.revision!==data.revision)return null
  const draft={...old,fields:{...old.fields}}
  if(event.type==='draft_delta')for(const change of data.changes){
   const value=draft.fields[change.field]??''
   // Server offsets count Unicode code points, not JavaScript UTF-16 units.
   if(Array.from(value).length!==change.offset)return null
   draft.fields[change.field]=value+change.text
  }
  if(event.type==='draft_validating')draft.state='validating'
  if(event.type==='draft_failed'){draft.state='failed';draft.message=data.message}
  next.drafts![data.issue_id]=draft
 }
 if(event.type==='issue_upserted'){
  next.issues[data.issue.id]=data.issue;delete next.drafts![data.issue.id]
  for(const p of data.proposals??[])next.proposals![p.proposal_id??p.id]=p
 }
 if(event.type==='issue_retracted'){delete next.issues[data.issue_id];delete next.drafts![data.issue_id]}
 // Final result reconciliation is server-owned; do not infer it from counters.
 if(event.type.startsWith('run_'))return null
 return next
}
