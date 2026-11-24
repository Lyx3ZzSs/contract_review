import {authFetch} from './auth-http'
export type ExportKind='contract'|'changes'|'opinions'
export interface ExportOptions {modifications:number;other_changes:number;comments:number;removed_comments:number;issues:number;changes_available:boolean;changes_reason:string;opinions_available:boolean;opinions_reason:string;base_revision:number;current_revision:number;round_number:number|null;document_version_id:string;base_version_id:string}
export interface ExportRecord {id:string;kind:ExportKind;state:'pending'|'ready'|'failed';filename:string;error:string|null;download_url:string|null;document_version_id:string;base_version_id:string}
export const exportChoices=[
 {kind:'contract' as const,title:'当前合同',description:'导出当前文档，保留已有修订和批注',action:'导出 Word'},
 {kind:'changes' as const,title:'本次修改说明',description:'汇总实际正文修改、批注及关联审查意见',action:'生成并导出'},
 {kind:'opinions' as const,title:'完整审查意见书',description:'汇总本轮最终意见、修改建议和待确认事项',action:'导出意见书'},
]
export function unavailable(kind:ExportKind,options:ExportOptions|null){return kind==='contract'?'':!options?'正在核对导出范围':kind==='changes'?options.changes_available?'':options.changes_reason:options.opinions_available?'':options.opinions_reason}
/** A failed generate/download retries the same snapshot, without capturing newer edits. */
export async function finishExport(record:ExportRecord,generate:(id:string)=>Promise<ExportRecord>,download:(record:ExportRecord)=>Promise<void>){
 const ready=record.state==='ready'?record:await generate(record.id)
 if(ready.state!=='ready'||!ready.download_url)throw Error(ready.error||'文件尚未生成，请重试')
 await download(ready);return ready
}
export async function downloadExport(record:ExportRecord){
 if(!record.download_url)throw Error('文件尚未生成')
 const response=await authFetch(record.download_url)
 if(!response.ok)throw Error('文件下载失败，请重试')
 const blob=await response.blob(),url=URL.createObjectURL(blob),a=document.createElement('a')
 a.href=url;a.download=record.filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
