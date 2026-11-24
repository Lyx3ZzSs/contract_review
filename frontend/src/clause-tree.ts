import type {ClauseNode,Evidence,Version} from './backend-api'

// Numbered items are local to their parent. Keep that path visible instead of
// presenting every “（5）” as a document-wide “第 5 项”.
export function reviewClauseLabel(version:Version|null,clause:ClauseNode|undefined,fallbackNumber?:string){
 const number=(clause?.number??fallbackNumber??'').trim()
 const text=(clause?.title??'').trim().replace(/[：:]$/,'')
 const item=/^[（(].+[）)]$/.test(number)
 let label=number
 if(item){
  label=number.replace(/\(/g,'（').replace(/\)/g,'）')
  const seen=new Set(clause?[clause.id]:[])
  let parent=version?.clauses?.find(c=>c.id===clause?.parent_id)
  while(parent&&!seen.has(parent.id)){
   seen.add(parent.id)
   const n=parent.number?.trim()
   if(n){
    label=n.replace(/\(/g,'（').replace(/\)/g,'）')+label
    if(!/^[（(]/.test(n))break
   }
   parent=version?.clauses?.find(c=>c.id===parent!.parent_id)
  }
 }else if(/^[一二三四五六七八九十百零〇]+$/.test(number))label=number+'、'
 else if(number&&!/^第/.test(number))label=`第 ${number} 条`
 const shortHeading=text&&[...text].length<=24&&!/[，。；！？,;!?]/.test(text)
 // Long parser titles are paragraph bodies, not headings. Quote an excerpt for
 // otherwise anonymous local items; never manufacture a semantic title.
 const chars=[...text]
 const excerpt=shortHeading?text:item&&text?chars.slice(0,18).join('')+(chars.length>18?'…':''):''
 return {title:excerpt?`${label}${!label||label.endsWith('、')?'':' · '}${excerpt}`:label||'相关条款',sourceTitle:text?`${label} ${text}`.trim():label}
}

export function clauseAt(version:Version|null,evidence?:Pick<Evidence,'block_id'|'start'|'end'>){
 if(!evidence)return undefined
 return version?.clauses?.find(c=>c.source_spans?.length
  ?c.source_spans.some(s=>s.block_id===evidence.block_id&&s.start<evidence.end&&s.end>evidence.start)
  :c.block_ids.includes(evidence.block_id))
}
export function reviewClauseAt(version:Version|null,evidence?:Pick<Evidence,'block_id'|'start'|'end'>){
 let c=clauseAt(version,evidence)
 const seen=new Set<string>()
 while(c&&['table','table_cell'].includes(c.kind??'')&&c.parent_id&&!seen.has(c.id)){
  seen.add(c.id);const parent=version?.clauses?.find(n=>n.id===c!.parent_id)
  if(!parent)break
  c=parent
 }
 return c
}
