import {api} from './backend-api'
export interface ReviewRecord {id:string;contract_id:string;title:string;counterpart:string;round_number:number;is_latest:boolean;created_at:string;status:string;record_status?:string;incomplete:boolean;pending:number;handled:number;document_version_id:string;result_id:string|null;completed_at:string|null}
export interface ReviewRecords {items:ReviewRecord[];total:number;counts:Record<string,number>;page:number;page_size:number}
export const recordStatus=(r:Pick<ReviewRecord,'status'|'record_status'|'incomplete'>)=>{
 const status=r.record_status??r.status
 return status==='queued'?'排队中':status==='running'?'审查中':status==='failed'?'审查失败':status==='needs_input'?'待补充信息':status==='completed'?(r.incomplete?'部分完成':'已生成结果'):'状态待确认'
}
export const recordAction=(r:ReviewRecord)=>['queued','running'].includes(r.status)?'查看进度':r.status==='failed'?'查看原因':!r.is_latest||r.completed_at?'查看记录':'继续审阅'
export const recordRoute=(id:string)=>`#/records/${encodeURIComponent(id)}`
export const loadReviewRecords=(params:URLSearchParams)=>api<ReviewRecords>(`/review-records?${params}`)
export async function validateContractFile(file:File){
 const legacy=/\.doc$/i.test(file.name)
 if(!/\.docx?$/i.test(file.name))throw new Error('请选择 DOC 或 DOCX 格式的合同正文。')
 if(file.size>20*1024*1024)throw new Error('文件超过 20 MB，请选择较小的 Word 文件。')
 const bytes=new Uint8Array(await file.slice(0,8).arrayBuffer())
 if(legacy){
  if(![0xd0,0xcf,0x11,0xe0,0xa1,0xb1,0x1a,0xe1].every((b,i)=>bytes[i]===b))throw new Error('文件不是有效的 DOC，请另存为 DOCX 后上传。')
 }else if(bytes[0]!==80||bytes[1]!==75)throw new Error('文件内容不是有效的 DOCX，请重新选择。')
}
