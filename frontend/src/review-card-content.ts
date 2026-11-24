import type {Finding, RevisionProposal} from './backend-api'
import type {ReviewDraft} from './review-execution'
import {evidenceKey} from './review-issue-presentation'
import {reviewClauseAt, reviewClauseLabel} from './clause-tree'
import type {Evidence, Version} from './backend-api'

export function evidenceLabel(version:Version|null,e?:Evidence){
 if(!e)return '相关条款'
 const index=version?.blocks.findIndex(b=>b.id===e.block_id)??-1
 const block=version?.blocks[index], location=block?.table_location
 const field=block?.text.match(/^\s*([^：:\r\n]{1,24})[：:]/)?.[1].trim()
 if(version&&location&&field){
  const cell=version.blocks.slice(0,index).filter(b=>b.table_location?.table===location.table&&
   b.table_location.row===location.row&&b.table_location.cell===location.cell)
  const party=cell.map(b=>b.text.match(/^\s*(甲方|乙方|丙方|丁方)\s*[：:]/)?.[1]).reverse().find(Boolean)
  if(party&&cell.some(b=>/^[\s（(]*(?:盖章|签字|签章)(?:[\s）)]|$)/.test(b.text)))
   return `签署表 · ${/^(甲方|乙方|丙方|丁方)/.test(field)?field:party+field}`
  if(/^(?:(?:甲方|乙方|丙方|丁方)\s*)?(?:签署|签订|签字)?日期$/.test(field))return `表格 ${location.table} · ${field}`
 }
 const clause=reviewClauseAt(version,e)
 const number=block?.text.trim().match(/^(\d+(?:\.\d+)+)(?=[^\d.]|$)/)?.[1]
 const label=reviewClauseLabel(version,clause,number)
 if(version&&location&&(!clause||/^表格\s*\d+$/.test(label.title))){
  const rowLabel=location.cell>1?version.blocks.find(b=>b.table_location?.table===location.table&&
   b.table_location.row===location.row&&b.table_location.cell===1)?.text.trim():undefined
  const position=`表格 ${location.table} · 第 ${location.row} 行`
  return rowLabel&&rowLabel.length<=18?`${position} · ${rowLabel}`:`${position}第 ${location.cell} 列`
 }
 if(clause||number)return label.title
 const quote=(e.quote||block?.text||'').trim().replace(/\s+/g,' ')
 return quote?`“${Array.from(quote).slice(0,18).join('')}${Array.from(quote).length>18?'…':''}”`:'相关原文'
}

export function cardContent(finding:Finding,proposals:RevisionProposal[]){
 const content=finding.card_content
 const allowed=new Set([...finding.evidence,...(finding.event_anchor?[finding.event_anchor]:[])].map(evidenceKey))
 // A legacy or adjusted opinion must never inherit another version's citations.
 const valid=content?.version==='review-card-v1'&&finding.review_state!=='adjusted'&&content.risk_paragraphs.length>0&&content.risk_paragraphs.every(p=>p.text.trim()&&p.evidence.length>0&&p.evidence.every(e=>allowed.has(evidenceKey(e))))
 const unified=Array.from(new Set(proposals.filter(p=>p.state!=='invalid'&&p.state!=='conflict'&&p.coordination).map(p=>p.coordination!.summary))).join('\n')
 return {
  paragraphs:valid?content.risk_paragraphs:[],
  plan:valid?content.modification_plan:unified||(proposals.length?finding.revision_plan?.message:'')||(finding.review_state==='adjusted'?'':Array.from(new Set(proposals.map(p=>p.rationale.trim()).filter(Boolean))).join('\n')),
 }
}

export function draftRiskText(draft?:ReviewDraft){
 if(!draft)return ''
 const paragraphs=Array.from({length:6},(_,i)=>draft.fields[`risk:${i}:text`]).filter(Boolean)
 return paragraphs.length?paragraphs.join('\n\n'):draft.fields.explanation??''
}
