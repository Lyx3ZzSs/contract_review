import {reviewLifecycle} from './review-lifecycle'
import type {ReviewDraft} from './review-execution'
import {ReviewDraftContent} from './review-draft-card'
import {cardContent, draftRiskText, evidenceLabel} from './review-card-content'
import {anchorKey} from './review-follow'
import { RevisionDiff } from './revision-diff'
import { useState } from 'react'
import { ChevronDown, ChevronRight, Target } from 'lucide-react'
import { Collapsible, DropdownMenu } from 'radix-ui'
import {ReviewCardMenu} from './review-card-menu'
import {linkedProposals} from './review-result-view'
import {IssueMarkupRecovery} from './proposal-actions'
import { toast } from 'sonner'
import { LegalFeedbackForm } from './legal-feedback-form'
import { RevisionProposalCard } from './revision-proposal-card'
import type { Evidence, Finding, ReviewDecision, ServerRun, Version } from './backend-api'
import { Button } from './components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from './components/ui/dialog'
import { decisionLabels, isResolved } from './review-status'
import { isInteractive } from './review-issues'
import { MaterialEvidencePreview } from './material-evidence-preview'
import { AttachmentIssue } from './attachment-issue'
import { issuePresentation, findingHeading, evidenceKey, type SupplementMode } from './review-issue-presentation'

export function ReviewFindingCard({ finding: f, draft, onNavigateFinding, hideRevision = false, activeEvidenceKey, run, decision: d, version, cid, locked, ready, locateLocked = locked, canApply = true, number = 1, collapsed = true, onExpandedChange, onLocate, onLocateEvidence, onDecision, onSupplement }: {
  onNavigateFinding?:(finding:Finding)=>void; finding: Finding; hideRevision?:boolean; draft?:ReviewDraft; activeEvidenceKey?:string; run: ServerRun; decision?: ReviewDecision; version: Version | null; cid: string; locked: boolean; ready: boolean; locateLocked?:boolean; canApply?: boolean; number?: number | null
  collapsed?: boolean; onExpandedChange?: (open: boolean) => void
  onLocate: (index: number, replace?: boolean) => void; onDecision: (action: string) => void; onSupplement: (mode: SupplementMode) => void
  onLocateEvidence?: (evidence:Evidence)=>void
}) {
  const lifecycle=reviewLifecycle(f,run)
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const structured = run.result_schema_version === 'interactive-review-v3'
  const advisory = f.execution_mode === 'case_advisory' || f.rule_id.startsWith('CR-')
  const resolved = isResolved(d)
  const presentation = issuePresentation(f, run.rule_snapshot?.rules.find(r => r.id === f.rule_id)?.title ?? f.rule_id)
  const canReplace = f.evidence.length === 1 && !!version?.blocks.some(b => b.id === f.evidence[0]?.block_id)
  const state = d ? decisionLabels[d.action] ?? d.action : '待处理'
  const {clause,title} = findingHeading(f,presentation.title)
  const location = clause ? `第 ${clause} 条` : f.attachment_name ?? f.reference_name ?? '合同相关条款'
  const proposals = structured ? linkedProposals(f,run,version) : []
  const evidence = f.event_anchor && !presentation.evidence.some(e => evidenceKey(e) === evidenceKey(f.event_anchor!)) ? [f.event_anchor, ...presentation.evidence] : presentation.evidence
  const materialEvidence = run.material_bundle_id ? evidence.filter(e=>!version?.blocks.some(b=>b.id===e.block_id)) : []
  const content=cardContent(f,proposals)
  const liabilityClauses=f.rule_id==='VL-01'&&content.paragraphs.length>0
  const clauseAnchors = liabilityClauses
    ? [...new Map(content.paragraphs.flatMap(p=>p.evidence)
        .filter(e=>version?.blocks.some(b=>b.id===e.block_id)).map(e=>[evidenceKey(e),e])).values()]
    : []
  const primaryEvidence = liabilityClauses ? clauseAnchors[0] : f.event_anchor ?? presentation.evidence[0]
  const canLocate = primaryEvidence && version?.blocks.some(b=>b.id===primaryEvidence.block_id)
  const streamingRisk=draftRiskText(draft)
  const drafting=f.revision_plan?.state==='generating'
  const plan=draft?draft.fields.modification_plan:drafting?'':content.plan
  function locateEvidence(e:Evidence){
    if(f.event_anchor&&evidenceKey(e)===evidenceKey(f.event_anchor)){
      onLocate(-1)
      return
    }
    const index=f.evidence.findIndex(original=>evidenceKey(original)===evidenceKey(e))
    if(index>=0)onLocate(index)
  }
  const citation=(e:Evidence)=>{
    const block=version?.blocks.find(b=>b.id===e.block_id)
    const label=evidenceLabel(version,e)
    const selected=activeEvidenceKey===anchorKey(e)
    const canReadMaterial = !block && materialEvidence.some(source=>evidenceKey(source)===evidenceKey(e))
    return <button key={evidenceKey(e)} type="button" className="result-evidence-chip" aria-label={block?`定位${label}`:`查看附件依据：${label}`} aria-pressed={block?selected:undefined} disabled={!block&&!canReadMaterial} title={e.quote} onClick={()=>block?locateEvidence(e):setFeedbackOpen(true)}><Target aria-hidden="true"/><span>{block?label:`附件 · ${label}`}</span></button>
  }
  const locateAction = clauseAnchors.length>1
    ? <DropdownMenu.Root modal={false}>
        <DropdownMenu.Trigger asChild><button type="button" className="result-locate"><Target aria-hidden="true"/>定位原文<ChevronDown aria-hidden="true"/></button></DropdownMenu.Trigger>
        <DropdownMenu.Portal><DropdownMenu.Content className="result-options-menu" align="start" sideOffset={6}>
          {clauseAnchors.map(e=><DropdownMenu.Item key={evidenceKey(e)} onSelect={()=>locateEvidence(e)}>{evidenceLabel(version,e)}</DropdownMenu.Item>)}
        </DropdownMenu.Content></DropdownMenu.Portal>
      </DropdownMenu.Root>
    : canLocate && <button type="button" className="result-locate" onClick={()=>locateEvidence(primaryEvidence)}><Target aria-hidden="true"/>{liabilityClauses?`定位${evidenceLabel(version,primaryEvidence)}`:'定位原文'}</button>
  const needsCheck = !f.suggested_text && !advisory && (f.status === 'insufficient_evidence' || f.applicability_state === 'needs_context')
  const liabilityIssue = f.execution_mode==='liability_clause'
  const guidanceTitle = f.suggested_text ? '修改建议' : liabilityIssue?'处理建议':liabilityClauses ? '下一步' : needsCheck ? '待核对事项' : '修改方向'
  const guidance = f.suggested_text || presentation.nextStep
  const original = canReplace ? version?.blocks.find(b=>b.id===f.evidence[0].block_id) : undefined
  const verifiedBefore = original && original.text.slice(f.evidence[0].start,f.evidence[0].end) === f.evidence[0].quote ? f.evidence[0].quote : null
  const showDiff = !!f.suggested_text && !!verifiedBefore && !run.stale && version?.id === run.document_version_id
  async function copyOpinion() {
    try { await navigator.clipboard.writeText(`${title}\n\n审查意见：${presentation.summary}${content.plan?`\n\n修改方案：${content.plan}`:proposals.length ? '' : `\n\n${guidanceTitle}（待核对）：${guidance}`}`); toast.success('审查意见已复制，正文未修改') }
    catch { toast.error('复制失败，请选择意见文本手动复制') }
  }
  return <Collapsible.Root open={!collapsed} onOpenChange={open => {
    onExpandedChange?.(open)
  }} asChild>
    <article className={`review-finding finding-${f.status} ${resolved ? 'is-resolved' : ''}`} aria-label={presentation.title} data-finding-id={f.id}>
      <div className="result-row-header">
        {number!=null&&<span className="result-number" aria-hidden="true">{String(number).padStart(2, '0')}</span>}
        <div className="result-row-main">
          <Collapsible.Trigger asChild><button type="button" className="result-row" aria-label={presentation.title}><span className="result-row-title">{title}</span><ChevronRight className="result-chevron" /></button></Collapsible.Trigger>
          <div className="result-row-meta"><span>{location}</span>{draft&&lifecycle.label&&<span className={`review-lifecycle lifecycle-${f.review_state??'preliminary'}`} role="status">{draft?(draft.state==='failed'?'修改生成未完成':draft.state==='validating'?'核对修改依据':'正在生成修改'):lifecycle.label}</span>}{!collapsed && locateAction}{d && <span className={`result-human-state ${resolved ? 'resolved' : ''}`} title={d.note||undefined}>{state}</span>}{proposals.length>0&&<span>{proposals.length} 条关联修订</span>}{collapsed && f.applicability_state === 'needs_context' && <span className="result-context-label">待确认</span>}</div>
          {drafting&&<p className="agent-revision-status" role="status">{f.revision_plan?.message}</p>}
          {collapsed && <p className="result-row-preview">{presentation.summary}</p>}
        </div>
        <ReviewCardMenu label={`更多操作：${title}`}>
          {!resolved&&<Button size="sm" variant="ghost" disabled={locked} onClick={()=>onDecision('acknowledged')}>记录处理</Button>}
          <Button size="sm" variant="ghost" onClick={()=>void copyOpinion()}>复制意见</Button>
          {!resolved&&<><Button size="sm" variant="ghost" disabled={locked} onClick={()=>onDecision('ignored')}>忽略</Button><Button size="sm" variant="ghost" disabled={locked} onClick={()=>onDecision('needs_business_confirmation')}>待业务确认</Button><Button size="sm" variant="ghost" disabled={locked} onClick={()=>onDecision('false_positive')}>标记误报</Button><Button size="sm" variant="ghost" disabled={locked} onClick={()=>onDecision('exception_recorded')}>记录例外</Button></>}
          <Button size="sm" variant="ghost" onClick={()=>setFeedbackOpen(true)}>法务反馈与历史</Button>
          {isInteractive(run)&&run.material_bundle_id&&<Button size="sm" variant="ghost" disabled={locked} onClick={()=>onSupplement('statement')}>补充审查要求</Button>}
        </ReviewCardMenu>
      </div>
      <Collapsible.Content inert={collapsed} className="result-detail">
        <div className="result-detail-surface">
          {f.reconciliation_note&&f.review_state==='adjusted'&&<p className="result-applicability">{f.reconciliation_note}</p>}
          {f.applicability_state === 'needs_context' && <p className="result-applicability">适用条件待确认：请补充业务范围或政策依据。</p>}
          {f.applicability_state === 'not_applicable' && <p className="result-applicability">当前适用性判断：本案不适用。</p>}
          <section className="result-explanation"><h4>{liabilityClauses?'条款核对':'风险概述'}</h4>
            {streamingRisk?<p className="stream-text" data-reading-anchor={`${f.id}:explanation`}>{streamingRisk}</p>:liabilityClauses?
              <ul className="grid list-none gap-2 p-0" aria-label="累计责任条款">{content.paragraphs.map((p,i)=><li className="result-cited-paragraph" key={i} data-reading-anchor={`${f.id}:risk:${i}`}>{p.text} {p.evidence.map(citation)}</li>)}</ul>
              :content.paragraphs.length?content.paragraphs.map((p,i)=><p className="result-cited-paragraph" key={i} data-reading-anchor={`${f.id}:risk:${i}`}>{p.text} {p.evidence.map(citation)}</p>):<p data-reading-anchor={`${f.id}:explanation`}>{presentation.summary}</p>}
            {!streamingRisk&&!content.paragraphs.length&&evidence.length>0&&<nav className="result-evidence-chips" aria-label="本项意见的原文引用">{evidence.map(citation)}</nav>}
            {!streamingRisk&&!evidence.length&&<small>没有可定位的原文证据</small>}
          </section>
          {plan&&<section className="result-modification-plan"><h4>修改方案</h4><p className={draft?'stream-text':undefined} data-reading-anchor={`${f.id}:plan`}>{plan}</p></section>}
          {!hideRevision&&f.revision_plan&&!drafting&&proposals.length===0&&!draft&&<p className="revision-blocker" role="status">{f.revision_plan.message}</p>}
          {!hideRevision&&(draft?<ReviewDraftContent draft={draft}/>:proposals.length ? <section className="result-inline-proposals" aria-label="本条意见的修改建议">{proposals.map((p,i) => <RevisionProposalCard initialCollapsed={i>0} onNavigateFinding={onNavigateFinding} key={p.proposal_id ?? p.id} proposal={p} run={run} version={version} locked={locked} locateLocked={locateLocked||!ready} onLocate={onLocateEvidence?()=>onLocateEvidence(p.anchor):undefined} />)}</section> : <section className={`result-guidance ${needsCheck ? 'is-verification' : 'is-direction'}`}><h4>{guidanceTitle}<span className="result-confirm-label">{advisory ? '待法务确认' : '待核对'}</span></h4><p>{guidance}</p>{showDiff && <RevisionDiff before={verifiedBefore!} after={f.suggested_text!}/>}</section>)}
          {liabilityIssue&&proposals.length===0&&<IssueMarkupRecovery issueId={f.id}/>}
          {f.suggested_text && canApply && !structured && <Button size="sm" variant="outline" disabled={locked || !ready || !canReplace} onClick={() => onLocate(0, true)}>写入修订</Button>}
        </div>
      </Collapsible.Content>
      <Dialog open={feedbackOpen} onOpenChange={setFeedbackOpen}>
        <DialogContent className="result-aux-dialog">
          <DialogHeader><DialogTitle>法务反馈与历史</DialogTitle><DialogDescription>{title}</DialogDescription></DialogHeader>
          {materialEvidence.map(e=><MaterialEvidencePreview key={evidenceKey(e)} cid={cid} bundleId={run.material_bundle_id} evidence={e}/>)}
          {isInteractive(run)&&<AttachmentIssue issue={f} runId={run.id} disabled={locked} onSupplement={mode=>{setFeedbackOpen(false);onSupplement(mode)}} />}
          <LegalFeedbackForm run={run} finding={f} version={version} disabled={locked} initiallyOpen hideTrigger />
        </DialogContent>
      </Dialog>
    </article>
  </Collapsible.Root>
}
