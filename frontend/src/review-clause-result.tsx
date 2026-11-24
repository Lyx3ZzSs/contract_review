import type {ReactNode} from 'react'
import type {ClauseResult} from './review-result-view'
import type {Finding,ServerRun,Version,Evidence} from './backend-api'
import {RevisionProposalCard} from './revision-proposal-card'

export function ReviewClauseResult({group,run,version,locked,locateLocked,onLocate,renderIssue,onNavigateClause,onNavigateFinding}:{group:ClauseResult;run:ServerRun;version:Version|null;locked:boolean;locateLocked:boolean;onLocate:(finding:Finding,evidence:Evidence)=>void;renderIssue:(f:Finding,index:number)=>ReactNode;onNavigateClause?:(id:string)=>void;onNavigateFinding?:(f:Finding)=>void}){
 const blocked=group.proposals.filter(p=>p.state==='conflict'||p.state==='invalid')
 const current=group.proposals.filter(p=>p.state!=='conflict'&&p.state!=='invalid')
 const plans=[...new Set(group.issues.map(f=>f.revision_plan?.message).filter(Boolean))]
 return <section className="review-clause-result" data-clause-result={group.id} aria-label={`${group.title}审查结果`}>
  <header className="clause-result-heading"><h3 title={group.sourceTitle}>{group.title}</h3><span>{group.issues.length} 个风险点 · {current.length} 条修订</span></header>
  <div className="clause-risk-list">{group.issues.map(renderIssue)}</div>
  <section className="clause-revision-plan" aria-label={`${group.title}统一修改方案`}>
   <h4>条款修改方案</h4>
   {current.length>0?current.map((p,i)=><RevisionProposalCard key={p.proposal_id??p.id} initialCollapsed={i>0} onNavigateFinding={onNavigateFinding} proposal={p} run={run} version={version} locked={locked} locateLocked={locateLocked} onLocate={()=>onLocate(group.issues.find(f=>f.event_id&&p.event_ids.includes(f.event_id))??group.issues[0],p.anchor)}/>):plans.length?plans.map(p=><p key={p}>{p}</p>):!blocked.length&&!group.relatedProposalCount&&<p>本项暂未提供独立修改稿，可结合风险说明核对。</p>}
   {group.relatedProposals.length>0&&<nav className="clause-related-links" aria-label="配套修改"><span>配套修改</span>{group.relatedProposals.map(p=><button type="button" key={p.proposalId} onClick={()=>onNavigateClause?.(p.groupId)}>{p.title}</button>)}</nav>}
   {blocked.length>0&&<><p className="revision-blocker" role="status">{blocked.some(p=>p.state==='conflict')?'关联修改存在冲突，尚未形成可共同采用的统一稿。请重新审查生成方案。':'部分旧建议已失效，不能用于修改正文。'}</p><details className="clause-revision-history"><summary>查看未采用的候选稿（{blocked.length}）</summary>{blocked.map(p=><RevisionProposalCard key={p.proposal_id??p.id} proposal={p} run={run} version={version} locked={true}/>)}</details></>}
  </section>
 </section>
}
