import {authFetch} from './auth-http'
import type { PartySelection, PartyDetails } from './party-types'
import type { EditorDraft } from './editor-storage'
import type { WorkbenchContract } from './workbench-data'
import {needsReview, summarizeReview, isResolved, reviewProgressText } from './review-status'
import { reviewItems, isCurrentReviewCompletion } from './review-issues'
import { initialState } from './review-state'
import type { WordLoadTrace } from './word-load-metrics'
export const isRemote=(id:string)=>id.startsWith('server:')
export const serverId=(id:string)=>id.replace(/^server:/,'')
const pendingReads = new Map<string, Promise<unknown>>()
export async function api<T>(path:string,init?:RequestInit):Promise<T>{
  // Share only simultaneous default GETs. Mutable business state is never retained.
  const share = init === undefined
  const mutation = !['GET','HEAD'].includes(init?.method?.toUpperCase() ?? 'GET')
  if (mutation) pendingReads.clear()
  let request = share ? pendingReads.get(path) : undefined
  if (!request) {
    request = (async () => {
      try {
        const response=await authFetch('/api/v1'+path,init)
        if(!response.ok){let message=`服务请求失败 (${response.status})`;try{const body=await response.json();message=typeof body.detail==='string'?body.detail:message}catch{}throw new Error(message)}
        return await response.json()
      } finally { if (mutation) pendingReads.clear() }
    })()
    if (share) {
      pendingReads.set(path, request)
      const clean = () => { if (pendingReads.get(path) === request) pendingReads.delete(path) }
      void request.then(clean, clean)
    }
  }
  return structuredClone(await request) as T
}
export const post=<T,>(path:string,body:unknown)=>api<T>(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})
export interface Evidence {block_id:string;start:number;end:number;quote:string}
export interface IssuePresentation {version:'issue-presentation-v1';title:string;summary:string;next_step:string;observations:{name:string;status:string;evidence:Evidence[];requirement_evidence:Evidence[]}[]}
export interface ReviewCardContent {version:'review-card-v1';risk_paragraphs:{text:string;evidence:Evidence[]}[];modification_plan:string}
export type ReviewCategory = 'transaction' | 'procedure' | 'wording' | 'legality' | 'other'
export interface Finding {review_category?:ReviewCategory|null;category?:string|null;revision_plan?:{state:'generating'|'ready'|'needs_confirmation'|'failed'|'no_change';message:string;group_id?:string}|null;card_content?:ReviewCardContent|null;review_state?:'preliminary'|'drafting'|'pending_reconciliation'|'reviewed'|'adjusted'|'merged'|'retracted'|'incomplete';review_state_reason?:string;provenance?:{origin?:string;rule_id?:string;module?:string;candidate_hint_refs?:string[];guidance_ids?:string[]};reconciliation?:{action:string;reason:string;target_issue_id?:string;previous_title?:string;previous_explanation?:string};reconciliation_note?:string;related_issue_key?:string;event_id?:string;event_anchor?:Evidence;clause_number?:string;display_group?:'legal_issue'|'context';mechanisms?:string[];applicability_state?:string;execution_state?:'completed'|'failed'|'not_run';execution_mode?:'confirmed_rule'|'case_advisory'|'model_discovery'|'liability_limit'|'liability_clause';review_reason?:string|null;title?:string|null;id:string;rule_id:string;status:string;explanation:string;evidence:Evidence[];suggested_text:string|null;subject_key?:string;material_bundle_id?:string;attachment_name?:string;reference_name?:string;match_state?:string;supersedes_issue_id?:string;presentation?:IssuePresentation|null}
export interface ReviewDecision {finding_id:string;action:string;note:string;created_at?:string;actor?:string;actor_sub?:string|null}
export interface ServerRun {execution_phases?:Record<string,{id:string;title:string;state:string;message?:string}>;recovery_count?:number;diagnostics?:{context_warnings?:string[];[key:string]:unknown}|unknown[]|null;revision_proposals?:RevisionProposal[];context_snapshot?:Record<string,unknown>;module_errors?:{module:string;code:string;message:string}[];result_schema_version?:string;rule_results?:RuleResult[];issues?:ReviewIssue[];material_bundle_id?:string;parent_run_id?:string;rule_snapshot?:{version:string;rules:{id:string;title:string}[]};review_prompt_version?:string;id:string;document_version_id:string;status:string;progress?:string;stage?:string;stage_history?:{stage:string;started_at:string}[];created_at?:string;started_at?:string;finished_at?:string;stale?:boolean;context_stale?:boolean;findings:Finding[];error?:{message:string;code?:string};decisions?:ReviewDecision[]}
export type RuleResult = Finding & {computed_calculations?:unknown[]|null;attachment_references?:unknown[]|null;field_checks?:unknown[]|null;numeric_grounding?:{confirmed?:boolean;internal_limit_yuan?:string;pending_reason?:string}|unknown[]|null}
export type ReviewIssue = Finding
export interface MaterialVersion {id:string;filename:string;parse_status:string;blocks?:{id:string;text:string}[];sha256?:string}
export interface AttachmentLink {reference_name:string;target_material_version_id?:string|null;target_block_ids:string[];origin?:string}
export interface MaterialBundle {materials?:MaterialVersion[];id:string;document_version_id:string;material_version_ids:string[];assertions:{statement?:string;text?:string;actor?:string;actor_sub?:string|null}[];links:AttachmentLink[]}
export interface IssueHistory {items:{run_id:string;issue:ReviewIssue;decisions:ReviewDecision[];created_at?:string}[];assertions:{statement?:string;text?:string;actor?:string;actor_sub?:string|null}[]}
export interface ClauseNode {id:string;parent_id?:string|null;number:string|null;block_ids:string[];title:string;kind?:string;source_order?:number;source_spans?:{block_id:string;start:number;end:number}[];resolution_status?:string;parse_gaps?:string[]}
export interface Version {id:string;filename:string;blocks:{id:string;text:string;table_location?:{table:number;row:number;cell:number}}[];clauses?:ClauseNode[];structure_version?:string;structure_summary?:{node_count:number;clause_count:number;unresolved_count:number;covered_blocks:number}}
export interface SupplementReceipt {review_id:string;bundle_id:string;parent_run_id:string}
export interface ServerResult {reviewer?:string;reviewer_sub?:string|null;scope?:string;run_id?:string;material_bundle_id?:string;id:string;document_version_id:string;created_at:string;opinion:string;reservations:string;review_snapshot?:ServerRun}
interface ServerContract {party_details?:PartyDetails;data_purpose?:'business'|'test';id:string;title:string;contract_type:string;our_party:string;created_at:string;client_metadata:Partial<WorkbenchContract>;current_document_version_id?:string}
const versions=new Map<string,string>()
export const setKnownVersion=(id:string,version:string)=>versions.set(id,version)
export const knownVersion=(id:string)=>versions.get(id)
const documentFiles = new Map<string, {version:Version;blob:Blob}>()
const pendingFiles = new Map<string, Promise<{version:Version;blob:Blob}>>()
const maxCachedBytes = 32 * 1024 * 1024
async function versionFile(id:string, trace?:WordLoadTrace) {
  const cached = documentFiles.get(id)
  if (cached) {
    documentFiles.delete(id); documentFiles.set(id,cached)
    trace?.mark('document.cache','memory hit')
    return cached
  }
  const pending = pendingFiles.get(id)
  if (pending) { trace?.mark('document.cache','shared request'); return pending }
  trace?.mark('document.cache','download')
  const measure = <T,>(stage:string, work:()=>Promise<T>) => trace ? trace.measure(stage,work) : work()
  const request = Promise.all([
    measure('document.version',()=>api<Version>(`/versions/${id}`)),
    measure('document.download',async()=>{
      const response=await authFetch(`/api/v1/versions/${id}/file`)
      if(!response.ok)throw new Error('正文下载失败')
      return response.blob()
    }),
  ]).then(([version,blob])=>{
    const entry={version,blob}
    if (blob.size <= maxCachedBytes) {
      documentFiles.set(id,entry)
      while (documentFiles.size > 3 || [...documentFiles.values()].reduce((n,x)=>n+x.blob.size,0) > maxCachedBytes) {
        documentFiles.delete(documentFiles.keys().next().value!)
      }
    }
    return entry
  })
  pendingFiles.set(id,request)
  try { return await request } finally { if (pendingFiles.get(id)===request) pendingFiles.delete(id) }
}
export async function remoteDraft(id:string, trace?:WordLoadTrace):Promise<EditorDraft>{
  const measure = <T,>(stage:string, work:()=>Promise<T>) => trace ? trace.measure(stage,work) : work()
  const cid=serverId(id), versionAtStart=versions.get(id)
  const snapshot=await measure('contract.snapshot',()=>api<{document_version_id:string|null;draft_state:Omit<EditorDraft,'blob'>|null;results:ServerResult[]}>(`/contracts/${cid}/editor-state`))
  if(!snapshot.document_version_id)throw new Error('合同尚未上传正文')
  const [document,latest]=await Promise.all([
    measure('document.file',()=>versionFile(snapshot.document_version_id!,trace)),
    snapshot.results[0]?api<ServerRun[]>(`/contracts/${cid}/reviews`).then(rows=>rows[0]?api<ServerRun>(`/runs/${rows[0].id}`):null):Promise.resolve(null),
  ])
  const {draft_state:state,results}=snapshot
  const {version:v,blob}=document
  if (versions.get(id)!==versionAtStart && versions.get(id)!==v.id) throw new Error('正文版本在加载期间发生变化，请重新打开合同')
  const review=state?.review??initialState()
  review.completed=isCurrentReviewCompletion(results[0],latest,v.id,review.reopenedAt)
  versions.set(id,v.id)
  return {version:1,name:v.filename,edited:false,...state,isDemo:false,review:{...review,decisions:{},activity:[]},blob}
}
export async function remoteSave(id:string,draft:EditorDraft){
  const expected=versions.get(id);if(!expected)throw new Error('文档版本未加载，请重新打开合同')
  const form=new FormData();form.append('file',draft.blob,draft.name);form.append('expected_version_id',expected)
  const {blob:_,...state}=draft;form.append('draft_state',JSON.stringify(state))
  const v=await api<Version>(`/contracts/${serverId(id)}/versions`,{method:'POST',body:form});versions.set(id,v.id)
}
export async function createRemote(item:WorkbenchContract,file:File,partySelection?:PartySelection,requestId?:string){
  if(partySelection){
    const form=new FormData();form.append('file',file,file.name)
    form.append('metadata',JSON.stringify({title:item.title,contract_type:item.type,our_party:item.position,stage:'pre_sign',client_metadata:item,party_selection:partySelection,...(requestId?{start_review:true,idempotency_key:requestId}:{})}))
    const result=await api<{contract:ServerContract;version:Version}>('/contracts/import',{method:'POST',body:form})
    const id='server:'+result.contract.id;versions.set(id,result.version.id)
    return {...item,id,...(requestId?{status:'审阅中' as const,note:'审查已提交，等待后台处理',reviewActive:true}:{}),counterpart:result.contract.party_details!.counterparties.join('、'),partyDetails:result.contract.party_details}
  }
  const c=await post<ServerContract>('/contracts',{title:item.title,contract_type:item.type,our_party:item.position,stage:'pre_sign',client_metadata:item})
  const form=new FormData();form.append('file',file,file.name)
  const v=await api<Version>(`/contracts/${c.id}/versions`,{method:'POST',body:form})
  const id='server:'+c.id;versions.set(id,v.id);return {...item,id}
}
export async function remoteContracts():Promise<WorkbenchContract[]>{
  const rows=(await api<ServerContract[]>('/contracts?data_purpose=business')).filter(c=>c.data_purpose!=='test')
  return Promise.all(rows.map(c=>remoteContract('server:'+c.id,c)))
}
export async function remoteContract(id:string,summary?:ServerContract):Promise<WorkbenchContract>{
    const c=summary??await api<ServerContract>(`/contracts/${encodeURIComponent(serverId(id))}`)
    const [info,history,results,state]=await Promise.all([
      summary?api<ServerContract>(`/contracts/${c.id}`):Promise.resolve(c),api<ServerRun[]>(`/contracts/${c.id}/reviews`),
      api<ServerResult[]>(`/contracts/${c.id}/results`),api<Omit<EditorDraft,'blob'>|null>(`/contracts/${c.id}/draft-state`),
    ])
    const latest=history[0]?await api<ServerRun>(`/runs/${history[0].id}`):null
    const required=latest?reviewItems(latest).filter(needsReview):[]
    const {decisions}=summarizeReview(latest)
    const businessPending=required.some(f=>decisions.get(f.id)?.action==='needs_business_confirmation')
    const completed=isCurrentReviewCompletion(results[0],latest,info.current_document_version_id,state?.review.reopenedAt)
    const status=completed?'已完成':businessPending?'待业务确认':latest||state?.review.reopenedAt?'审阅中':'待审阅'
    const note=latest?.context_stale?'审查资料或主体已修改，需重新审查':latest?.status==='failed'?'审查失败，请重试':(latest?reviewProgressText(latest):undefined)??'正文已保存，可发起合同审查'
    return {number:c.id.slice(0,8),owner:'我',department:'待确认',deadline:'',updated:c.created_at.slice(0,10),amount:'待确认',project:'待确认',...c.client_metadata,
      partyDetails:c.party_details,counterpart:c.party_details?.counterparties.join('、')??c.client_metadata.counterpart??'待确认',
      id:'server:'+c.id,title:c.title,type:c.contract_type,position:c.our_party,example:false,hasDocument:!!info.current_document_version_id,
      status,note,reviewActive:latest?.status==='queued'||latest?.status==='running',high:0,medium:0,low:0,total:required.length,processed:required.filter(f=>isResolved(decisions.get(f.id))).length,
      resultSummary:results[0]?{revision:results.length,conclusion:'人工审阅记录',opinion:results[0].opinion,completedAt:results[0].created_at,ignored:0}:undefined,
    } as WorkbenchContract
}

export type RevisionProposal = ({id?:string;proposal_id:string}|{id:string;proposal_id?:string}) & {confirmation_items?:{id:string;text:string;source:'requirement'|'draft'|'coverage'|'legacy';requirement_ids?:string[];parameter_sources?:{value:string;origin:string}[]}[];coordination?:{group_id:string;event_ids:string[];requirement_ids:string[];summary:string;structurally_valid?:boolean};conflicting_proposal_ids?:string[];event_ids:string[];document_version_id:string;operation:'delete'|'replace'|'insert';anchor:Evidence;before_text:string;after_text:string;rationale:string;basis_refs:string[];state:'draft'|'context_required'|'conflict'|'invalid';message?:string}
export type LegalVerdict = 'agree'|'modify_suggestion'|'false_positive'|'not_applicable'|'business_acceptance'|'missed_issue'
export interface LegalFeedbackInput {idempotency_key:string;issue_id?:string;proposal_id?:string;event_anchor?:Evidence;verdict:LegalVerdict;reason:string;corrected_text?:string;basis_refs:string[];actor:string;document_version_id:string}
export interface LegalFeedback extends LegalFeedbackInput {id:string;run_id:string;created_at:string}
