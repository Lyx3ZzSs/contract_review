import type { RefObject } from 'react'
import type { ReviewState } from '../review-state'
export type ProposalMode='ALL'|'COMMENT'|'MODIFY'
export interface ProposalOperation {created_at?:string;reverted_at?:string;id:string;run_id?:string;proposal_id:string;mode:ProposalMode;requested_mode?:ProposalMode;verification_error?:string;phase?:'prepared'|'saved_unverified'|'verified'|'cancelled';state:'prepared'|'applied'|'reverted'|'cancelled';before_version_id:string;after_version_id?:string;can_undo?:boolean}
export interface Snapshot { documentVersionId:string;sha256:string;saveRequestId:string }
export type ReviewTarget={navigationNotice?:string;documentVersionId:string;blockId:string;start:number;end:number;paragraph:string;quote:string;blocks:{id:string;text:string}[]}
export type ReviewEvidenceContext={title:string;phase:'queued'|'checking'|'settling'|'attention'|'incomplete'|'finished'|'context'}
export type ReviewPresentation={context?:ReviewEvidenceContext;current:ReviewTarget;related?:ReviewTarget[];reveal:'never'|'if-needed'|'center'}
export type ReviewPresentationResult={ok:boolean;visible:boolean;moved:boolean;status?:string;reason?:string;geometry?:'line-ranges'|'start-only'}
export interface ReviewEditor {
  readOnly?:boolean;
  ready:boolean;busy:boolean;saveStatus:'loading'|'saving'|'saved'|'error';review:ReviewState;
  capabilities:{locateEvidence:boolean;applyTrackedSuggestion:boolean;nativeReferenceSelection?:boolean};
  applyProposal?:(runId:string,proposalId:string,mode:ProposalMode,manualReplacement?:string)=>Promise<ProposalOperation>;
  confirmProposal?:(operationId:string)=>Promise<ProposalOperation>;
  undoProposal?:(operation:ProposalOperation)=>Promise<void>;
  flushSave:()=>Promise<boolean>;
  setReviewReadonly?:(locked:boolean)=>Promise<void>;
  canAutomaticallyLocate?:()=>boolean;
  subscribeDocumentInteraction?:(listener:()=>void)=>()=>void;
  cancelReviewNavigation?:()=>void;
  locateReviewTarget?:(target:ReviewTarget)=>Promise<boolean>;
  presentReviewEvidence?:(presentation:ReviewPresentation)=>Promise<ReviewPresentationResult>;
  clearReviewEvidence?:()=>void;
  updateReviewEvidenceContext?:(blockId:string,context:ReviewEvidenceContext)=>void;
  locateEvidence:(paragraph:string,quote:string,replacement?:string)=>Promise<boolean>;
  setReviewCompleted?:(completed:boolean)=>void;
  prepareSnapshot?:()=>Promise<boolean>;
  snapshotSessionId?:()=>string|undefined;
  releaseSnapshot?:()=>Promise<void>;
}
export interface EditorMount {host:RefObject<HTMLDivElement|null>;toolbar:RefObject<HTMLDivElement|null>}
