type NavigationReceipt={status?:string;reason?:string;sourceIndex?:number;blockId?:string;sourceStart?:number;sourceEnd?:number}

// Preserve bridge diagnostics for callers; user messages never include contract text.
export class NavigationError extends Error {
 constructor(public readonly phase:'bind'|'locate',public readonly receipt:NavigationReceipt={}) {
  const {status,reason,sourceIndex}=receipt
  let message='编辑器未确认定位结果，请重新点击原文引用。'
  if(status==='stale')message='正文已变化或保存尚未确认，请保存后重新定位。'
  else if(status==='unsupported')message='当前编辑器不支持所需定位能力，请更新编辑器资源后重新加载。'
  else if(status==='mapping_mismatch')message=`正文第 ${Number.isInteger(sourceIndex)?sourceIndex!+1:'未知'} 段与编辑器内容未能对齐，请重新加载正文后核对。`
  else if(status==='mapping_missing')message='正文定位映射已失效，请重新点击原文引用。'
  else if(status==='ambiguous')message='该段原文存在重复，无法唯一确定位置，请在正文中核对上下文。'
  else if(status==='interrupted')message='定位已被中断，请重新点击原文引用。'
  else if(reason==='paragraph_missing')message='该段原文未能与编辑器内容匹配，请在正文中核对。'
  else if(reason==='invalid_offsets'||reason==='invalid_anchor'||status==='invalid_request')message='引用内容或字符位置校验失败，请重新审查后定位。'
  else if(reason==='range_text_mismatch')message='无法在对应段落中确认引用的文字范围，请在正文中核对。'
  else if(reason==='selected_text_mismatch')message='编辑器未能保留这处引用的选区，请重新点击定位。'
  else if(status==='not_found')message='编辑器中未找到对应原文，请在正文中查找并核对。'
  super(message);this.name='NavigationError'
 }
}

export function requireNavigationReceipt(receipt:NavigationReceipt|undefined,phase:'bind'|'locate') {
 if(receipt?.status===(phase==='bind'?'bound':'located'))return
 if(receipt?.reason==='range_text_mismatch'||receipt?.reason==='selected_text_mismatch'){
  const {reason,blockId,sourceStart,sourceEnd}=receipt
  console.warn('OnlyOffice navigation', {reason,blockId,sourceStart,sourceEnd})
 }
 throw new NavigationError(phase,receipt)
}
