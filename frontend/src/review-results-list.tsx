import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { FileCheck2, Filter } from 'lucide-react'
import { Tabs, TabsList, TabsTrigger, TabsContent } from './components/ui/tabs'
import { Button } from './components/ui/button'
import { ReviewFindingCard } from './review-finding-card'
import { RevisionProposalCard } from './revision-proposal-card'
import { buildReviewResultView, resultCategory, type ResultCategory } from './review-result-view'
import { summarizeReview } from './review-status'
import type { Finding, ServerRun, Version } from './backend-api'
import type { SupplementMode } from './review-issue-presentation'

type Props = {
  run: ServerRun; version: Version | null; cid: string; locked: boolean; ready: boolean; canApply?: boolean; locateLocked?:boolean; active?:boolean
  notice?: ReactNode
  onLocate: (finding: Finding, index: number, replace?: boolean) => void
  onDecision: (finding: Finding, action: string) => void
  onSupplement: (finding: Finding, mode: SupplementMode) => void
}

export function ReviewResultsList({ run, version, cid, locked, ready, canApply = true, locateLocked = locked, active = false, notice, onLocate, onDecision, onSupplement }: Props) {
  const view = buildReviewResultView(run)
  const { decisions } = summarizeReview(run)
  const [filter, setFilter] = useState<'pending' | 'handled'>(view.defaultFilter)
  const [category, setCategory] = useState<ResultCategory | 'all'>('all')
  const [judgment, setJudgment] = useState('all')
  const [filtersOpen, setFiltersOpen] = useState(false)
  // undefined selects the first visible item; null is an intentional collapse.
  const [expanded, setExpanded] = useState<string | null | undefined>(undefined)
  const filterId = useId()
  const candidates = filter === 'pending' ? view.pending : view.handled
  const visible = candidates.filter(f => (category === 'all' || resultCategory(f) === category) && (judgment === 'all' || f.status === judgment))
  useEffect(()=>{if(expanded===undefined&&visible[0])setExpanded(visible[0].id)},[expanded,visible[0]?.id])
  const activeId = expanded === null ? null : visible.some(f => f.id === expanded) ? expanded : visible[0]?.id
  const filtered = category !== 'all' || judgment !== 'all'
  const structured = run.result_schema_version === 'interactive-review-v3'
  const allItems = [...view.pending, ...view.handled]
  const [seenIds, setSeenIds] = useState(() => new Set(allItems.map(f => f.id)))
  const [jumpTo, setJumpTo] = useState<string | null>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const newItems = allItems.filter(f => !seenIds.has(f.id))
  useEffect(() => {
    if (!jumpTo) return
    listRef.current?.querySelector(`[data-finding-id="${CSS.escape(jumpTo)}"]`)?.scrollIntoView({ block: 'nearest' })
    setJumpTo(null)
  }, [jumpTo])
  // Never silently drop proposals whose event is absent from the actionable list.
  const unlinked = structured ? (run.revision_proposals ?? []).filter(p => !allItems.some(f => f.event_id && p.event_ids.includes(f.event_id))) : []

  return <Tabs ref={listRef} className="result-browser" value={filter} onValueChange={value => { setFilter(value as typeof filter); setExpanded(undefined) }}>
    <div className="result-status-bar">
      <TabsList variant="line" className="result-status-tabs" aria-label="意见处理状态">
        <TabsTrigger value="pending">待处理 <span>{view.pending.length}</span></TabsTrigger>
        <TabsTrigger value="handled">已处理 <span>{view.handled.length}</span></TabsTrigger>
      </TabsList>
      <Button variant="ghost" className={`result-filter-toggle ${filtered ? 'is-filtered' : ''}`} aria-expanded={filtersOpen} aria-controls={filterId} onClick={() => setFiltersOpen(!filtersOpen)}><Filter />筛选{filtered && <span className="filter-active-dot" aria-label="已应用筛选" />}</Button>
    </div>
    {filtersOpen && <div className="result-filter-bar" id={filterId}>
      <label>审查类别<select aria-label="审查类别" value={category} onChange={e => { setCategory(e.target.value as typeof category); setExpanded(undefined) }}><option value="all">全部类别</option>{view.categories.map(c => <option value={c.id} key={c.id}>{c.label} ({c.pending + c.handled})</option>)}</select></label>
      <label>AI 判断<select aria-label="AI 判断" value={judgment} onChange={e => { setJudgment(e.target.value); setExpanded(undefined) }}><option value="all">全部判断</option><option value="flag">发现问题</option><option value="insufficient_evidence">待核验或法务复核</option></select></label>
      {filtered && <Button variant="ghost" size="sm" onClick={() => { setCategory('all'); setJudgment('all'); setExpanded(undefined) }}>清除</Button>}
    </div>}
    <div className="result-list-notices">{notice}
      {view.contextWarnings.length > 0 && <aside className="review-context-warning" role="status"><strong>审查范围与待核对事项</strong>{view.contextWarnings.map(w => <p key={w}>{w}</p>)}</aside>}
    </div>
    {active && newItems.length > 0 && <Button size="sm" variant="outline" onClick={() => {
      const target = newItems[0].id
      setFilter('pending'); setCategory('all'); setJudgment('all'); setExpanded(target)
      setSeenIds(new Set(allItems.map(f => f.id))); setJumpTo(target)
    }}>新增 {newItems.length} 条意见 · 查看</Button>}
    <span className="sr-only" aria-live="polite">当前显示 {visible.length} 项{structured ? `；问题事件 ${view.riskEventCount}；修改建议 ${view.proposalCount}` : ''}</span>
    {(['pending', 'handled'] as const).map(state => <TabsContent value={state} key={state} className="result-list-content"><div className="review-findings">
      {visible.map((f, index) => <ReviewFindingCard key={f.id} number={index + 1} finding={f} run={run} decision={decisions.get(f.id)} version={version} cid={cid} locked={locked} locateLocked={locateLocked} ready={ready} canApply={canApply && !structured} collapsed={activeId !== f.id} onExpandedChange={open => setExpanded(open ? f.id : null)} onLocate={(i, replace) => onLocate(f, i, replace)} onDecision={action => onDecision(f, action)} onSupplement={mode => onSupplement(f, mode)} />)}
      {!visible.length && <div className="result-empty" role="status"><FileCheck2 /><strong>{filtered ? '没有符合筛选条件的意见' : filter === 'handled' ? '暂无已处理意见' : view.handled.length ? '本轮待处理意见已处理' : active ? '本轮意见正在生成' : '本轮未发现需要处理的事项'}</strong><p>{filtered ? '调整筛选条件，查看其他审查意见。' : filter === 'handled' ? '记录处理结论后，可在这里查看。' : active ? '已校验的意见会陆续出现在这里。' : '审查范围与执行情况可在审查记录中查看。'}</p>{filtered && <Button variant="outline" size="sm" onClick={() => { setCategory('all'); setJudgment('all'); setExpanded(undefined) }}>清除筛选</Button>}</div>}
    </div></TabsContent>)}
    {unlinked.length > 0 && <details className="revision-proposals"><summary>其他修改建议（{unlinked.length}）</summary>{unlinked.map(p => <RevisionProposalCard key={p.proposal_id ?? p.id} proposal={p} run={run} version={version} locked={locked} />)}</details>}
  </Tabs>
}
