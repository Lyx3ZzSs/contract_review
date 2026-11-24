import type {ReviewTarget} from './contract-editor'
export type SourceBlock={id:string;text:string}
export type NativeParagraph={text:string;paraId?:string}
export type NativeMatch={blockId:string;paragraphIndex:number;start:number;length:number;scope?:{kind?:string}|unknown}
// Deliberately exact: fields, text boxes and revision projections must not silently shift ordinals.
export function bindEigenpalAnchors(version:string,blocks:SourceBlock[],paragraphs:readonly NativeParagraph[],find:(text:string)=>readonly NativeMatch[]){
 const nonempty=paragraphs.map((p,index)=>({...p,index})).filter(p=>p.text.trim())
 if(nonempty.length!==blocks.length)throw Error('正文段落数量与审查快照不一致')
 const map=new Map<string,{blockId:string;text:string}>(),used=new Set<string>()
 for(let i=0;i<blocks.length;i++){
  const b=blocks[i],p=nonempty[i],ordinal=Number(b.id.slice((version+':p').length))-1
  if(!b.id.startsWith(version+':p')||ordinal!==p.index||b.text!==p.text||map.has(b.id))throw Error('正文段落顺序或文字与审查快照不一致')
  // Native find rejects long queries. The entire paragraph was verified above;
  // a bounded prefix only obtains its native node identity, never establishes text identity.
  const prefix=Array.from(b.text).slice(0,64).join('')
  const matches=find(prefix).filter(m=>m.paragraphIndex===ordinal&&m.start===0&&m.length===prefix.length&&(!m.scope||(m.scope as {kind?:string}).kind==='body'))
  if(matches.length!==1||used.has(matches[0].blockId))throw Error('编辑器节点无法唯一绑定：段落 '+(ordinal+1)+'，候选 '+matches.length)
  map.set(b.id,{blockId:matches[0].blockId,text:b.text});used.add(matches[0].blockId)
 }
 return {resolve(target:ReviewTarget){
  const p=map.get(target.blockId),chars=p?Array.from(p.text):[]
  if(target.documentVersionId!==version||!p||p.text!==target.paragraph||!Number.isInteger(target.start)||!Number.isInteger(target.end)||target.start<0||target.end<=target.start||target.end>chars.length||chars.slice(target.start,target.end).join('')!==target.quote)throw Error('证据与当前只读快照不一致')
  return {blockId:p.blockId,start:chars.slice(0,target.start).join('').length,length:target.quote.length,expectedText:target.quote}
 },size:map.size}
}
