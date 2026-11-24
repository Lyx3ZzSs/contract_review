import { RevisionDiff } from './revision-diff'
import { useState } from 'react'
import { ChevronDown, ChevronRight, Target } from 'lucide-react'
import { Collapsible } from 'radix-ui'
import { toast } from 'sonner'
import { LegalFeedbackForm } from './legal-feedback-form'
import { RevisionProposalCard } from './revision-proposal-card'
import type { Finding, ReviewDecision, ServerRun, Version } from './backend-api'
import { Button } from './components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from './components/ui/dialog'
import { decisionLabels, isResolved } from './review-status'
import { isInteractive } from './review-issues'
import { MaterialEvidencePreview } from './material-evidence-preview'
import { AttachmentIssue } from './attachment-issue'
import { issuePresentation, evidenceKey, type SupplementMode } from './review-issue-presentation'

export function ReviewFindingCard({ finding: f, run, decision: d, version, cid, locked, ready, locateLocked = locked, canApply = true, number = 1, collapsed = true, onExpandedChange, onLocate, onDecision, onSupplement }: {
  finding: Finding; run: ServerRun; decision?: ReviewDecision; version: Version | null; cid: string; locked: boolean; ready: boolean; locateLocked?:boolean; canApply?: boolean; number?: number
  collapsed?: boolean; onExpandedChange?: (open: boolean) => void
  onLocate: (index: number, replace?: boolean) => void; onDecision: (action: string) => void; onSupplement: (mode: SupplementMode) => void
}) {
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const structured = run.result_schema_version === 'interactive-review-v3'
  const advisory = f.execution_mode === 'case_advisory' || f.rule_id.startsWith('CR-')
  const resolved = isResolved(d)
  const presentation = issuePresentation(f, run.rule_snapshot?.rules.find(r => r.id === f.rule_id)?.title ?? f.rule_id)
  const previous = (run.decisions ?? []).filter(item => item.finding_id === f.id).slice(0, -1)
  const firstEvidence = f.event_anchor ?? presentation.evidence[0]
  const primaryIndex = f.event_anchor ? -1 : f.evidence.findIndex(e => firstEvidence && evidenceKey(e) === evidenceKey(firstEvidence))
  const canLocate = (primaryIndex >= 0 || !!f.event_anchor) && !!version?.blocks.some(b => b.id === firstEvidence?.block_id)
  const canReplace = f.evidence.length === 1 && !!version?.blocks.some(b => b.id === f.evidence[0]?.block_id)
  const state = d ? decisionLabels[d.action] ?? d.action : '待处理'
  const clause = f.clause_number ?? presentation.title.match(/^(\d+(?:\.\d+)+)\s/)?.[1]
  const title = clause ? presentation.title.replace(new RegExp(`^${clause.replaceAll('.', '\\.')}\\s+`), '') : presentation.title
  const location = clause ? `第 ${clause} 条` : f.attachment_name ?? f.reference_name ?? '合同相关条款'
  const proposals = structured ? (run.revision_proposals ?? []).filter(p => f.event_id && p.event_ids.includes(f.event_id)) : []
  const evidence = f.event_anchor && !presentation.evidence.some(e => evidenceKey(e) === evidenceKey(f.event_anchor!)) ? [f.event_anchor, ...presentation.evidence] : presentation.evidence
  const needsCheck = !f.suggested_text && !advisory && (f.status === 'insufficient_evidence' || f.applicability_state === 'needs_context')
  const guidanceTitle = f.suggested_text ? '修改建议' : needsCheck ? '待核对事项' : '修改方向'
  const guidance = f.suggested_text || presentation.nextStep
  const original = canReplace ? version?.blocks.find(b=>b.id===f.evidence[0].block_id) : undefined
  const verifiedBefore = original && original.text.slice(f.evidence[0].start,f.evidence[0].end) === f.evidence[0].quote ? f.evidence[0].quote : null
  const showDiff = !!f.suggested_text && !!verifiedBefore && !run.stale && version?.id === run.document_version_id
  async function copyOpinion() {
    try { await navigator.clipboard.writeText(`${title}\n\n审查意见：${presentation.summary}${proposals.length ? '' : `\n\n${guidanceTitle}（待核对）：${guidance}`}`); toast.success('审查意见已复制，正文未修改') }
    catch { toast.error('复制失败，请选择意见文本手动复制') }
  }
  return <Collapsible.Root open={!collapsed} onOpenChange={open => {
    onExpandedChange?.(open)
    if (open && canLocate && ready && !locateLocked && window.matchMedia('(min-width: 761px)').matches) onLocate(primaryIndex)
  }} asChild>
    <article className={`review-finding finding-${f.status} ${resolved ? 'is-resolved' : ''}`} aria-label={presentation.title} data-finding-id={f.id}>
      <div className="result-row-header">
        <span className="result-number" aria-hidden="true">{String(number).padStart(2, '0')}</span>
        <div className="result-row-main">
          <Collapsible.Trigger asChild><button type="button" className="result-row" aria-label={presentation.title}><span className="result-row-title">{title}</span><ChevronRight className="result-chevron" /></button></Collapsible.Trigger>
          <div className="result-row-meta"><span>{location}</span>{!collapsed && canLocate && <button className="result-locate" disabled={locateLocked || !ready} onClick={() => onLocate(primaryIndex)}><Target />定位原文</button>}{d && <span className={`result-human-state ${resolved ? 'resolved' : ''}`}>{state}</span>}{collapsed && f.applicability_state === 'needs_context' && <span className="result-context-label">待确认</span>}</div>
          {collapsed && <p className="result-row-preview">{presentation.summary}</p>}
        </div>
      </div>
      <Collapsible.Content inert={collapsed} className="result-detail">
        <div className="result-detail-surface">
          {f.applicability_state === 'needs_context' && <p className="result-applicability">适用条件待确认：请补充业务范围或政策依据。</p>}
          {f.applicability_state === 'not_applicable' && <p className="result-applicability">当前适用性判断：本案不适用。</p>}
          <section className="result-explanation"><h4>审查意见</h4><p>{presentation.summary}</p></section>
          {proposals.length ? <section className="result-inline-proposals" aria-label="本条意见的修改建议">{proposals.map(p => <RevisionProposalCard key={p.proposal_id ?? p.id} proposal={p} run={run} version={version} locked={locked} />)}</section> : <section className={`result-guidance ${needsCheck ? 'is-verification' : 'is-direction'}`}><h4>{guidanceTitle}<span className="result-confirm-label">{advisory ? '待法务确认' : '待核对'}</span></h4><p>{guidance}</p>{showDiff && <RevisionDiff before={verifiedBefore!} after={f.suggested_text!}/>}</section>}
          <details className="result-evidence-section"><summary><ChevronDown /><span>原文与依据</span><small>{evidence.length} 处引用</small></summary>
            <div className="review-evidence">{evidence.length ? evidence.map((e, i) => <div className="result-source" key={evidenceKey(e)}><div className="result-source-heading"><span>{version?.blocks.some(b => b.id === e.block_id) ? '合同正文' : '附件材料'} · 证据 {i + 1}</span>{version?.blocks.some(b => b.id === e.block_id) && <Button size="sm" variant="ghost" disabled={locateLocked || !ready} onClick={() => onLocate(f.event_anchor && evidenceKey(e) === evidenceKey(f.event_anchor) ? -1 : f.evidence.findIndex(original => evidenceKey(original) === evidenceKey(e)))}>定位</Button>}</div><blockquote>{e.quote}</blockquote>{!version?.blocks.some(b => b.id === e.block_id) && <MaterialEvidencePreview cid={cid} bundleId={run.material_bundle_id} evidence={e} />}</div>) : <p className="result-no-evidence">没有可定位的原文证据，请结合本轮审查范围核验。</p>}</div>
            <div className="result-basis"><strong>{run.rule_snapshot?.rules.find(r => r.id === f.rule_id)?.title ?? f.rule_id}</strong><p>{advisory ? '个案审查意见 · 需法务复核' : '规则审查'} · {f.status === 'flag' ? '发现问题' : advisory ? '适用口径待确认' : '证据不足'}</p>{presentation.structured && <p>{f.explanation}</p>}{presentation.excluded.length > 0 && <p>本轮未按缺项处理：{presentation.excluded.map(o => o.name).join('、')}。</p>}</div>
            <div className="result-secondary-actions">
              {!resolved && <><Button size="sm" variant="ghost" disabled={locked} onClick={() => onDecision('needs_business_confirmation')}>待业务确认</Button><Button size="sm" variant="ghost" disabled={locked} onClick={() => onDecision('false_positive')}>标记误报</Button><Button size="sm" variant="ghost" disabled={locked} onClick={() => onDecision('exception_recorded')}>记录例外</Button></>}
              <Button size="sm" variant="ghost" onClick={() => setFeedbackOpen(true)}>法务反馈与历史</Button>
            </div>
            {isInteractive(run) && <AttachmentIssue issue={f} runId={run.id} disabled={locked} onSupplement={onSupplement} />}
            {previous.length > 0 && <details className="review-decision-history"><summary>此前 {previous.length} 条处理记录</summary>{previous.map((item, i) => <div className="review-decision-record" key={i}><strong>{decisionLabels[item.action] ?? item.action}</strong><p>{item.note}</p></div>)}</details>}
          </details>
          {d && <div className="review-decision-record"><strong>{state}</strong><p>{d.note}</p><small>人工处理记录，不代表正文已修改{d.created_at ? ` · ${new Date(d.created_at).toLocaleString('zh-CN')}` : ''}</small></div>}
          <div className="result-actions">
            {!resolved && <Button size="sm" disabled={locked} onClick={() => onDecision('acknowledged')}>记录处理</Button>}
            <Button size="sm" variant="outline" onClick={() => void copyOpinion()}>复制意见</Button>
            {!resolved && <Button size="sm" variant="ghost" disabled={locked} onClick={() => onDecision('ignored')}>忽略</Button>}
            {f.suggested_text && canApply && !structured && <Button size="sm" variant="outline" disabled={locked || !ready || !canReplace} onClick={() => onLocate(0, true)}>写入修订</Button>}
          </div>
        </div>
      </Collapsible.Content>
      <Dialog open={feedbackOpen} onOpenChange={setFeedbackOpen}><DialogContent className="result-aux-dialog"><DialogHeader><DialogTitle>法务反馈与历史</DialogTitle><DialogDescription>{title}</DialogDescription></DialogHeader><LegalFeedbackForm run={run} finding={f} version={version} disabled={locked} initiallyOpen hideTrigger /></DialogContent></Dialog>
    </article>
  </Collapsible.Root>
}
