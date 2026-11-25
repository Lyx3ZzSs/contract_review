import {needsReview} from './review-status'
import {isChangedTargetNotice,ProposalActionButton,useProposalOperation,useProposalEligible,useProposalCompletion,useProposalLocation} from './proposal-actions'
import {RevisionDiff} from './revision-diff'
import {createContext,useContext,useId,useState} from 'react'
import {ChevronDown,ListChecks,Target} from 'lucide-react'
import type {Finding,RevisionProposal,ServerRun,Version} from './backend-api'
import {Button} from './components/ui/button'
import {reviewItems} from './review-issues'
import {ReviewCardMenu} from './review-card-menu'
import {evidenceLabel} from './review-card-content'
export const RevisionDisclosureContext=createContext<{choices:Record<string,boolean>;setChoice:(id:string,collapsed:boolean)=>void}|null>(null)
const states={draft:'待核对',context_required:'待核对事项',conflict:'关联修改待整合',invalid:'建议校验未通过'}
export function RevisionProposalCard({proposal:p,run,version,locked,locateLocked=locked,onLocate,initialCollapsed=false,onNavigateFinding}:{proposal:RevisionProposal;run:ServerRun;version:Version|null;locked:boolean;locateLocked?:boolean;onLocate?:()=>void;initialCollapsed?:boolean;onNavigateFinding?:(finding:Finding)=>void}){
  const [notice,setNotice]=useState(''),[localCollapsed,setLocalCollapsed]=useState(initialCollapsed)
  const disclosure=useContext(RevisionDisclosureContext)
  const detailId=useId(),pid=p.proposal_id??p.id!
  const collapsed=disclosure?.choices[pid]??localCollapsed
  const toggle=()=>{setLocalCollapsed(!collapsed);disclosure?.setChoice(pid,!collapsed)}
  const relocation=useProposalLocation(pid),operation=useProposalOperation(pid),completed=useProposalCompletion(pid)
  const stale=!!run.stale||!!version&&version.id!==p.document_version_id||p.document_version_id!==run.document_version_id
  const related=reviewItems(run).filter(f=>needsReview(f)&&f.event_id&&p.event_ids.includes(f.event_id))
  const block=version?.blocks.find(b=>b.id===p.anchor?.block_id)
  const title=p.anchor?evidenceLabel(version,p.anchor):'条款修改'
  const eligible=useProposalEligible(pid),current=['draft','context_required'].includes(p.state)&&(!stale||eligible)
  const status=operation?.state==='prepared'?'保存结果待确认':completed.comment&&completed.revision?'修订与批注均已保存':completed.revision?'修订已保存':completed.comment?'批注已保存 · 正文未修改':current?'未应用':'仅供核对'
  async function copy(){
    try{await navigator.clipboard.writeText(p.operation==='delete'?`删除：${p.before_text}`:p.after_text);setNotice('已复制建议')}
    catch{setNotice('复制失败，请手动选择文本复制')}
  }
  return <article className="revision-proposal" data-proposal-id={pid} aria-label={`${title}的修改建议`}>
    <header className="revision-proposal-toolbar">
      <button type="button" className="revision-proposal-title" aria-expanded={!collapsed} aria-controls={detailId} onClick={toggle}><ListChecks aria-hidden="true"/><span>{title}</span><small>{relocation.appended?.length?'段后新增':{delete:'删除',replace:'替换',insert:'新增'}[p.operation]}</small><ChevronDown className={collapsed?'is-collapsed':''}/></button>
      <div className="revision-proposal-actions">
        {(onLocate||relocation.location?.target)&&<button type="button" className="revision-locate" aria-label={`定位修改位置：${title}`} title="定位修改位置" disabled={relocation.location?!relocation.canLocate:locateLocked||stale||!block} onClick={relocation.location?()=>void relocation.locate():onLocate}><Target aria-hidden="true"/></button>}
        <ProposalActionButton proposal={p}/>
        <ReviewCardMenu label={`更多修订操作：${title}`}><Button size="sm" variant="ghost" disabled={stale&&!eligible||!['draft','context_required'].includes(p.state)||!version} onClick={()=>void copy()}>复制建议</Button></ReviewCardMenu>
      </div>
    </header>
    <div className="revision-proposal-status"><span>{status}</span>{notice&&<span role="status">{notice}</span>}</div>
    {related.length>1&&<details className="revision-shared-plan"><summary>关联 {related.length} 个风险 · 同步应用状态</summary><nav aria-label="关联风险">{related.map(f=>onNavigateFinding?<button type="button" key={f.id} onClick={()=>onNavigateFinding(f)}>{f.title??f.clause_number??'相关风险'}</button>:<p key={f.id}>{f.title??f.clause_number??'相关风险'}</p>)}</nav></details>}
    {collapsed&&<p className="revision-summary">{p.rationale||'展开查看具体修订'}</p>}
    <div id={detailId} hidden={collapsed}>
      {relocation.location?.status==='relocated'&&<p className="revision-location-note" role="status">{relocation.location.message}</p>}
      {relocation.recheck&&relocation.recheck.status!=='not_required'&&!isChangedTargetNotice(relocation.recheck.reason)&&<p className="revision-blocker" role="status">{relocation.recheck.reason}</p>}
      {!current&&!operation&&!isChangedTargetNotice(relocation.location?.message)&&<p className="revision-blocker" role="status">{relocation.location?.message||(stale&&!eligible?'正文已更新，建议已过期':states[p.state])}{p.message&&p.state!=='context_required'?` · ${p.message}`:''}</p>}
      {(current||completed.comment||completed.revision||operation?.state==='applied')&&(p.operation==='delete'||p.after_text)?<RevisionDiff before={relocation.appended?.length||p.operation==='insert'?'':p.before_text} after={relocation.appended?.length?relocation.appended.join('\n'):p.operation==='delete'?'':p.after_text}/>:<div className="revision-candidate"><strong>候选文本 · 待核对</strong><blockquote>{p.operation==='delete'?'（建议删除上述原文，不替换为其他文本）':p.after_text||'（尚无确定文本）'}</blockquote><details><summary>参考原文</summary><blockquote>{p.operation==='insert'?p.anchor?.quote:p.before_text}</blockquote></details></div>}
      {current&&p.operation==='insert'&&p.anchor?.quote&&<details><summary>插入位置原文</summary><blockquote>{p.anchor.quote}</blockquote></details>}
    </div>
  </article>
}
