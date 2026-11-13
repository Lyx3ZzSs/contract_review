import type { RefObject } from 'react'
import type { ReviewState } from '../review-state'
export interface Snapshot { documentVersionId:string;sha256:string;saveRequestId:string }
export interface ReviewEditor {
  readOnly?:boolean;
  ready:boolean;busy:boolean;saveStatus:'loading'|'saving'|'saved'|'error';review:ReviewState;
  capabilities:{locateEvidence:boolean;applyTrackedSuggestion:boolean};
  flushSave:()=>Promise<boolean>;
  locateReviewTarget?:(target:{documentVersionId:string;paragraph:string;quote:string})=>Promise<boolean>;
  locateEvidence:(paragraph:string,quote:string,replacement?:string)=>Promise<boolean>;
  freeze:()=>void;reopen:()=>Promise<boolean>;
  prepareFinalize?:()=>Promise<boolean>;
  finalizeSessionId?:()=>string|undefined;
  cancelFinalize?:()=>Promise<void>;
}
export interface EditorMount {host:RefObject<HTMLDivElement|null>;toolbar:RefObject<HTMLDivElement|null>}
