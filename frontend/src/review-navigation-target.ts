import type {Evidence,Version} from './backend-api'
import type {ReviewTarget} from './editors/contract-editor'

type Blocks=Pick<Version,'blocks'>['blocks']
const MAX_CELLS=1_000_000
const ambiguous=()=>new Error('原文存在多个可能位置，无法唯一确认，请在正文中核对上下文。')

// An anchor is usable only if EVERY optimal alignment retains it at the same
// position. Picking one diff (or the first search hit) can select a different
// occurrence after a duplicate is inserted or deleted.
function alignment(a:string[],b:string[]){
 const n=a.length,m=b.length,width=m+1
 if((n+1)*width>MAX_CELLS)throw Error('正文变化范围较大，暂时无法自动确认位置，请在正文中核对。')
 const pre=new Uint32Array((n+1)*width),post=new Uint32Array((n+1)*width)
 for(let i=0;i<n;i++)for(let j=0;j<m;j++)pre[(i+1)*width+j+1]=a[i]===b[j]?pre[i*width+j]+1:Math.max(pre[i*width+j+1],pre[(i+1)*width+j])
 for(let i=n-1;i>=0;i--)for(let j=m-1;j>=0;j--)post[i*width+j]=a[i]===b[j]?post[(i+1)*width+j+1]+1:Math.max(post[(i+1)*width+j],post[i*width+j+1])
 const optimum=pre[n*width+m]
 return (i:number)=>{
  let match=-1
  for(let j=0;j<=m;j++){
   if(pre[i*width+j]+post[(i+1)*width+j]===optimum)return -1
   if(j<m&&a[i]===b[j]&&pre[i*width+j]+1+post[(i+1)*width+j+1]===optimum){if(match!==-1)return -1;match=j}
  }
  return match
 }
}
function flatten(blocks:Blocks){
 const chars:string[]=[],positions:{block:number;offset:number}[]=[]
 blocks.forEach((b,block)=>{
  if(block){chars.push('\n');positions.push({block:-1,offset:-1})}
  Array.from(b.text).forEach((char,offset)=>{chars.push(char);positions.push({block,offset})})
 })
 return {chars,positions}
}

// This resolver is for navigation only. It does not establish whether a review
// finding or a proposed write is still applicable to the edited contract.
export function reviewNavigationTarget(e:Evidence,source:Pick<Version,'id'|'blocks'>,current:Pick<Version,'id'|'blocks'>):ReviewTarget {
 const index=source.blocks.findIndex(b=>b.id===e.block_id),block=source.blocks[index]
 if(!block)throw Error('本项缺少可定位原文，请补充材料。')
 const chars=Array.from(block.text)
 if(!Number.isInteger(e.start)||!Number.isInteger(e.end)||e.start<0||e.end<=e.start||e.end>chars.length||chars.slice(e.start,e.end).join('')!==e.quote)throw Error('证据校验失败')
 const make=(target:Blocks[number],start=e.start,end=e.end,navigationNotice?:string):ReviewTarget=>({documentVersionId:current.id,blockId:target.id,start,end,paragraph:target.text,quote:Array.from(target.text).slice(start,end).join(''),blocks:current.blocks,...(navigationNotice?{navigationNotice}:{})})
 if(current.id===source.id){
  const target=current.blocks.find(b=>b.id===block.id)
  if(!target||target.text!==block.text)throw Error('正文快照与审查版本不一致，请重新加载正文。')
  return make(target)
 }
 const old=source.blocks.map(b=>b.text),now=current.blocks.map(b=>b.text)
 if(old.length===now.length&&old.every((t,i)=>t===now[i]))return make(current.blocks[index])
 const candidates=now.flatMap((t,i)=>t===block.text?[i]:[])
 if(candidates.length===1&&old.filter(t=>t===block.text).length===1)return make(current.blocks[candidates[0]])
 const paragraphMatch=alignment(old,now)
 if(candidates.length){
  const mapped=paragraphMatch(index)
  if(mapped<0)throw ambiguous()
  return make(current.blocks[mapped])
 }
 // Bound the changed region by verified unchanged paragraphs. This supports
 // paragraph splits/merges without assuming that paragraph ordinals persist.
 let before=-1,after=old.length,left=-1,right=now.length
 for(let i=index-1;i>=0;i--){const j=paragraphMatch(i);if(j>=0){before=i;left=j;break}}
 for(let i=index+1;i<old.length;i++){const j=paragraphMatch(i);if(j>=0){after=i;right=j;break}}
 const oldRegion=source.blocks.slice(before+1,after),newRegion=current.blocks.slice(left+1,right)
 if(!newRegion.length)throw Error('原文所在段落已删除，请在正文中核对相邻条款。')
 const a=flatten(oldRegion),b=flatten(newRegion),match=alignment(a.chars,b.chars)
 const sourceIndex=index-before-1,start=a.positions.findIndex(p=>p.block===sourceIndex&&p.offset===e.start)
 const mapped=chars.slice(e.start,e.end).map((_,i)=>match(start+i))
 if(mapped.every((j,i)=>j>=0&&(!i||j===mapped[0]+i))){
  const first=b.positions[mapped[0]],last=b.positions[mapped[mapped.length-1]]
  if(first.block>=0&&first.block===last.block)return make(newRegion[first.block],first.offset,last.offset+1,'正文已修改，已定位当前仍保留的引用；审查意见仍基于旧版本。')
 }
 // A retained quote may now cross paragraph boundaries. The single-range
 // editor contract can show its first fragment, but must not claim the whole
 // historical range is selected.
 if(mapped.every((j,i)=>j>=0&&(!i||(j>mapped[i-1]&&b.positions.slice(mapped[i-1]+1,j).every(p=>p.block===-1))))){
  const first=b.positions[mapped[0]],last=b.positions[mapped[mapped.length-1]]
  if(first.block>=0&&last.block>first.block){
   const target=newRegion[first.block]
   return make(target,first.offset,Array.from(target.text).length,'原引用现跨多个段落，已定位起始片段，请继续核对后续段落；审查意见仍基于旧版本。')
  }
 }
 // If the quote was edited, offer the corresponding CURRENT paragraph rather
 // than presenting different words as the old evidence. Require substantial,
 // unavoidable surviving text, all belonging to one current paragraph.
 const surviving=a.positions.flatMap((p,i)=>{
  if(p.block!==sourceIndex)return []
  const j=match(i),pos=j>=0?b.positions[j]:undefined
  return pos&&pos.block>=0?[pos]:[]
 })
 const destinations=new Set(surviving.map(p=>p.block))
 if(destinations.size===1&&surviving.length>=Math.max(6,Math.ceil(chars.length*.5))){
  const target=newRegion[surviving[0].block]
  return make(target,0,Array.from(target.text).length)
 }
 throw Error('原引用已修改或删除，尚无法唯一确认对应段落，请在正文中核对。')
}
