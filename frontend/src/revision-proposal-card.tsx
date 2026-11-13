import { RevisionDiff } from './revision-diff'
import { useState } from 'react'
import type { RevisionProposal, ServerRun, Version } from './backend-api'
import { Button } from './components/ui/button'
import { reviewItems } from './review-issues'
import { LegalFeedbackForm } from './legal-feedback-form'
const states={draft:'待核对',context_required:'缺少适用条件或政策依据',conflict:'修改范围冲突',invalid:'建议校验未通过'}
export function RevisionProposalCard({proposal:p,run,version,locked}:{proposal:RevisionProposal;run:ServerRun;version:Version|null;locked:boolean}){
  const [notice,setNotice]=useState('')
  const stale=!!run.stale||!!version&&version.id!==p.document_version_id||p.document_version_id!==run.document_version_id
  const related=reviewItems(run).filter(f=>f.event_id&&p.event_ids.includes(f.event_id))
  const finding=related[0]
  const labels=[...new Set(related.map(f=>[f.clause_number?`第 ${f.clause_number} 条`:'',f.event_anchor?.quote??f.title??''].filter(Boolean).join(' · ')).filter(Boolean))]
  return <article className="revision-proposal"><h4>{{delete:'删除',replace:'替换',insert:'插入'}[p.operation]}建议 · {stale?'正文已更新，建议已过期':states[p.state]}</h4>
    {labels.map(label=><p key={label}>关联事件：{label}</p>)}
    {p.state==='draft' && !stale && (p.operation==='delete' || p.after_text) ? <RevisionDiff before={p.operation==='insert'?'':p.before_text} after={p.operation==='delete'?'':p.after_text}/> : <><strong>参考原文</strong><blockquote>{p.before_text||'（插入位置）'}</blockquote><strong>候选文本 · 待核对</strong><blockquote>{p.after_text||'（尚无确定文本）'}</blockquote></>}
    <p>{p.rationale}</p>{p.message&&<p>{p.message}</p>}<small>依据：{p.basis_refs.length?p.basis_refs.join('、'):'尚未提供依据'}</small>
    <p>{p.state==='draft'?'建议尚未写入正文，请核对后手工修订。':'当前建议仅供核对；补齐条件或解决校验问题后再形成确定修改。'}</p>
    <Button size="sm" variant="outline" disabled={stale||locked||p.state!=='draft'||!version} onClick={async()=>{try{await navigator.clipboard.writeText(p.operation==='delete'?`删除：${p.before_text}`:p.after_text);setNotice('已复制')}catch{setNotice('复制失败，请手动选择文本复制')}}}>复制建议</Button>{notice&&<span role="status">{notice}</span>}
    {finding&&<LegalFeedbackForm run={run} finding={finding} proposal={p} version={version} disabled={locked||stale}/>}
  </article>
}
