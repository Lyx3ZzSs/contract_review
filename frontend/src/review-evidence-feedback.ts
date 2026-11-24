import type {ReviewPresentationResult} from './editors/contract-editor'
export function evidenceFeedback(result:ReviewPresentationResult,reveal:'never'|'if-needed'|'center'){
 if(!result.ok){
  if(result.status==='interrupted')return '定位已暂停，可重新点击原文引用。'
  if(result.status==='stale')return '正文已变化，请保存后重新定位。'
  if(['ambiguous','mapping_mismatch','mapping_missing'].includes(result.status??''))return '原文位置尚未唯一确认，请核对上下文后重新定位。'
  if(result.status==='unsupported')return '当前正文无法安全展示证据范围，请手动核对。'
  if(result.status==='not_found')return '未找到与本轮证据一致的原文，请核对文档版本。'
  return '原文定位未完成，请确认正文已加载并保存后重试。'
 }
 if(reveal!=='never'&&!result.visible)return '已生成证据标记，但目标尚未进入可视区域，请重新定位。'
 if(result.geometry==='start-only')return '仅标出原文起点，完整范围未展开，请手动核对。'
 return reveal==='never'?'证据标记已更新，阅读位置保持不变。':''
}
