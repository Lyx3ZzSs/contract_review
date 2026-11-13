export interface PartySelection {
  preview_id:string|null;our_index:number|null;counterparty_indices:number[]
  manual_our_name:string|null;manual_counterparties:string[]|null
}
export interface PartyPreview {
  id:string;file_sha256:string;status:'ready'|'partial'|'conflict'|'not_found'|'failed'
  parties:{name:string;role:string;source:'explicit'|'llm';evidence:{block_id:string;quote:string}[]}[]
  error:{code:string;message:string}|null;tracked_changes_present:boolean
}
export interface PartyDetails {
  our_name:string;our_role:string|null;counterparties:string[];source:'manual'|'extracted'
  confirmed_at:string;needs_reconfirmation:boolean;document_version_id:string
}
