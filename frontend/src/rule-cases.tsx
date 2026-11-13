import { useEffect, useState } from 'react'
import { Button } from './components/ui/button'
import { loadRuleCases, type RuleCases, type RuleCase, type RulePack } from './rule-data'

const categoryNames = {historical: '真实法务案例', engineering: '规则工程验证', attachment: '附件专项验证'}
function resultLabel(item: RuleCase) {
  if (!item.trials.length) return '未运行 · 预期待确认'
  if (item.trials.some(t => t.status === 'failed')) return '含执行失败'
  if (item.trials.some(t => t.passed === false)) return '存在差异'
  if (item.trials.every(t => t.passed === true)) return '符合工程预期'
  return '尚未比较'
}

export function RuleCasesPanel({ruleId, pack}: {ruleId: string; pack: RulePack}) {
  const [data, setData] = useState<RuleCases | null>(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [filter, setFilter] = useState('all')
  useEffect(() => {
    let cancelled = false
    setData(null); setError('')
    loadRuleCases(ruleId).then(value => {if (!cancelled) setData(value)})
      .catch(e => {if (!cancelled) setError(e instanceof Error ? e.message : '案例读取失败')})
    return () => {cancelled = true}
  }, [ruleId, retry])
  if (error) return <div className="rule-case-empty" role="alert"><p>{error}</p><Button variant="outline" onClick={() => setRetry(v => v + 1)}>重试案例加载</Button></div>
  if (!data) return <p role="status">正在读取案例与已保存的验证结果…</p>
  const visible = data.cases.filter(c => filter === 'all' || filter === c.category)
  return <div className="rule-cases">
    <p className="rule-scope-note">已有记录只读展示，不会重新调用模型。历史案例的预期仍待法务裁定，工程结果不等于法律准确率。</p>
    <div className="case-statistics" aria-label="案例记录汇总">
      <span>真实案例 <b>{data.summary.historical_cases}</b></span><span>工程样例 <b>{data.summary.engineering_cases}</b></span>
      <span>结果差异 <b>{data.summary.differences}</b></span><span>执行失败 <b>{data.summary.failed_requests}</b></span>
    </div>
    <label className="case-filter">案例类型<select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部案例</option>{Object.entries(categoryNames).map(([id, title]) => <option value={id} key={id}>{title}</option>)}</select></label>
    {!visible.length && <p className="rule-case-empty">暂无此类案例，待补充验证材料。</p>}
    {visible.map(item => <details className="rule-case-card" key={item.id}>
      <summary><span className="case-heading"><small>{item.id} · {categoryNames[item.category]}</small><strong>{item.title}</strong><span className={item.trials.some(t => t.passed === false || t.status === 'failed') ? 'case-status attention' : 'case-status'}>{resultLabel(item)}</span></span></summary>
      <div className="case-body">
        <p className="case-limitation">{item.limitation}</p>
        <details className="case-excerpts"><summary>查看原文与定位（{item.excerpts.length} 段）</summary>{item.excerpts.map((e, i) => <blockquote key={i}><small>{e.source_id && `${pack.presentation.sources.find(s => s.id === e.source_id)?.filename ?? e.source_id} · `}{e.location}</small><p>{e.text || '该位置未提取到原文'}</p></blockquote>)}</details>
        {item.reviewer_comment && <section><h5>原法务批注</h5><p>{item.reviewer_comment}</p></section>}
        <section><h5>{item.category === 'historical' ? '待法务裁定的预期结论' : '工程预期'}</h5><p>{item.expected}</p></section>
        <section><h5>已保存的实际结果</h5>{!item.trials.length ? <p>未运行：暂无与本案例关联的结果。</p> : item.trials.map(t => <div className="case-trial" key={t.repeat}>
          <div className="case-trial-title"><strong>第 {t.repeat} 次</strong><span className={t.status === 'failed' || t.passed === false ? 'case-status attention' : 'case-status'}>{t.status === 'failed' ? '执行失败' : t.passed === true ? '符合工程预期' : t.passed === false ? '与预期有差异' : '未比较'}</span></div>
          <p>{t.actual}</p>{t.explanation && <p>{t.explanation}</p>}
          {t.error_code && <p>错误：{t.error_code}。原记录未保留 HTTP 状态码。</p>}
          {t.rejected_attempts > 0 && <p>保留失败尝试：{t.rejected_attempts} 次</p>}
          {!!t.evidence.length && <details><summary>查看结果引用（{t.evidence.length} 处）</summary>{t.evidence.map((e, i) => <blockquote key={i}><small>{e.block_id}</small><p>{e.quote}</p></blockquote>)}</details>}
          <p className="case-run-meta">{t.policy_version} · {t.model}<br/>{new Date(t.created_at).toLocaleString('zh-CN')}</p>
          {(t.policy_version !== pack.execution_policy.version || t.prompt_sha256 !== pack.execution_policy.prompt_sha256) && <p className="case-version-warning">此记录的执行口径与当前版本不同，不能作为当前版本的验证结果。</p>}
        </div>)}</section>
        <small className="case-source">记录来源：{item.source_file}</small>
      </div>
    </details>)}
  </div>
}
