import type { ServerRun } from './backend-api'
import { coverageGroups, hasIncompleteReview } from './review-issues'
import { aiLabels } from './review-status'

export function ReviewRuleCoverage({run}:{run:ServerRun}) {
  const groups=coverageGroups(run)
  return <details className="review-coverage-section"><summary>查看全部规则结论 <span>{hasIncompleteReview(run)?'本轮部分完成':`${groups.flatMap(g=>g.rules).filter(r=>r.state==='completed').length} 项已完成`}</span></summary>
    <div className="review-rule-coverage" aria-label="规则检查记录">{groups.map(group=><section key={group.title}><h4>{group.title}</h4>{group.rules.map(({id,result:rule,state})=><details key={id}>
      <summary><strong>{run.rule_snapshot?.rules.find(r=>r.id===id)?.title??id}</strong><span>{state==='completed'?'已完成':state==='uncovered'?'未覆盖':state==='not_run'?'未执行':'未完成'}{rule&&state==='completed'?` · ${id.startsWith('CR-')&&rule.status==='insufficient_evidence'?'需法务复核':aiLabels[rule.status]??rule.status}`:''}</span></summary>
      {rule?<><p>{rule.explanation}</p>{rule.evidence.map((e,i)=><blockquote key={i}>{e.quote}</blockquote>)}</>:<p>{state==='uncovered'?'本轮未包含此项检查。':'此项尚未完成，需重新审查。'}</p>}
    </details>)}</section>)}</div>
    {!groups[1].rules.some(r=>r.state!=='uncovered')&&<p>本轮未包含责任与费用保护检查；可使用当前规则重新审查。</p>}
    {run.module_errors?.map((error,i)=><p role="alert" key={i}>{error.module} 未完成：{error.message}。请重新审查。</p>)}
  </details>
}
