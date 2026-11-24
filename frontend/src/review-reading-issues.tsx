import {useEffect,useRef} from 'react'
import type {Evidence,Finding,ServerRun,Version} from './backend-api'
import {issuePresentation,evidenceKey} from './review-issue-presentation'
import {stableIssueOrder} from './review-reference'
import {decisionLabels,isResolved,summarizeReview} from './review-status'
import {MaterialEvidencePreview} from './material-evidence-preview'
import {RevisionProposalCard} from './revision-proposal-card'
export function ReviewReadingIssues({issues,run,version,cid,blockIds,disabled,locked,onEvidence,onDecision,onInteract,matter=false}:{issues:Finding[];run:ServerRun;version:Version|null;cid:string;blockIds:string[];disabled:boolean;locked:boolean;onEvidence:(e:Evidence,title:string)=>void;onDecision:(f:Finding,action:string)=>void;onInteract:()=>void;matter?:boolean}){
 const order=useRef<string[]>([]),stable=stableIssueOrder(order.current,issues)
 useEffect(()=>{order.current=stable.map(i=>i.id)},[issues])
 const {decisions}=summarizeReview(run)
 const sharedProposals=(run.revision_proposals??[]).filter(p=>stable.some(f=>f.event_id&&p.event_ids.includes(f.event_id))).filter((p,i,all)=>all.findIndex(other=>(other.proposal_id??other.id)===(p.proposal_id??p.id))===i)
 return <section className="reading-issues" aria-label={matter?'当前事项意见':'当前条款意见'}><h3>{matter?'事项意见':'当前条款意见'} <span>{stable.length}</span></h3>
 {!stable.length&&<p className="reading-empty">{matter?'本事项尚无可展示的意见，核查状态见上方。':'当前条款暂无已生成的待处理意见。核查范围与进度见上方。'}</p>}
 {stable.map(f=>{
  const p=issuePresentation(f,run.rule_snapshot?.rules.find(r=>r.id===f.rule_id)?.title??f.rule_id),decision=decisions.get(f.id)
  const evidence=[...(f.event_anchor?[f.event_anchor]:[]),...p.evidence].filter((e,i,all)=>all.findIndex(other=>evidenceKey(other)===evidenceKey(e))===i)
  const proposals=(run.revision_proposals??[]).filter(p=>!!f.event_id&&p.event_ids.includes(f.event_id))
  return <article key={f.id} data-reading-issue={f.id} className="reading-issue" onPointerDown={onInteract} onFocusCapture={onInteract}>
   <header><strong>{p.title}</strong><span className={isResolved(decision)?'is-handled':''}>{decision?decisionLabels[decision.action]??decision.action:'待处理'}</span></header>
   <p className="reading-issue-summary">{p.summary}</p>
   <details className="reading-evidence"><summary>原文与关联依据 · {evidence.length} 处</summary>
    {evidence.map((e,i)=>{const body=!!version?.blocks.some(b=>b.id===e.block_id),related=!blockIds.includes(e.block_id);return <div key={evidenceKey(e)} className="reading-source"><div><strong>{body?(related?'关联条款':'本条原文'):'附件依据'} {i+1}</strong>{body&&<button disabled={disabled} onClick={()=>onEvidence(e,`${p.title} · ${related?'关联条款':'本条原文'}`)}>{related?'查看关联原文':'查看本条原文'}</button>}</div><blockquote>{e.quote}</blockquote>{!body&&<MaterialEvidencePreview cid={cid} bundleId={run.material_bundle_id} evidence={e}/>}</div>})}
    {!evidence.length&&<p>没有可定位的原文证据，请补充依据后核对。</p>}
    <small>核查依据：{run.rule_snapshot?.rules.find(r=>r.id===f.rule_id)?.title??f.rule_id}{f.execution_mode==='case_advisory'?' · 个案意见，需法务复核':''}</small>
   </details>
   {proposals.length?null:<div className="reading-guidance"><strong>{f.suggested_text?'修改建议 · 待核对':'下一步核对'}</strong><p>{f.suggested_text||p.nextStep}</p></div>}
   {decision&&<p className="reading-decision">{decision.note}</p>}
   {!isResolved(decision)&&<div className="reading-actions"><button disabled={locked} onClick={()=>onDecision(f,'acknowledged')}>记录处理</button><button disabled={locked} onClick={()=>onDecision(f,'needs_business_confirmation')}>待业务确认</button></div>}
  </article>
 })}{sharedProposals.length>0&&<section aria-label="当前条款修改方案"><h4>条款修改方案</h4>{sharedProposals.filter(p=>p.state!=='invalid'&&p.state!=='conflict').map(p=><RevisionProposalCard key={p.proposal_id??p.id} proposal={p} run={run} version={version} locked={locked}/>)}{sharedProposals.some(p=>p.state==='invalid'||p.state==='conflict')&&<p role="status">部分候选稿存在冲突或已失效，请在审查结果中核对统一方案。</p>}</section>}</section>
}
