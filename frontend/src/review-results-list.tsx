import {ReviewClauseResult} from './review-clause-result'
import type {ReviewDraft} from './review-execution'
import {ReviewDraftCard} from './review-draft-card'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { FileCheck2 } from 'lucide-react'
import { Tabs, TabsList, TabsTrigger, TabsContent } from './components/ui/tabs'
import { Button } from './components/ui/button'
import { ReviewFindingCard } from './review-finding-card'
import { RevisionDisclosureContext, RevisionProposalCard } from './revision-proposal-card'
import { buildReviewResultView, groupClauseResults, orderRevisionProposals, resultCategory, type ResultCategory, riskCategories, riskCategory, resultEmptyState } from './review-result-view'
import { summarizeReview } from './review-status'
import type { Finding, ServerRun, Version } from './backend-api'
import type { SupplementMode } from './review-issue-presentation'
import {stableIssueOrder} from './review-reference'

type Props = {
  compactStream?:boolean
  initialMode?:'risk'|'clause'; run: ServerRun; version: Version | null; cid: string; locked: boolean; ready: boolean; canApply?: boolean; locateLocked?:boolean; active?:boolean
  focusedBlockId?: string
  activeEvidenceKey?: string
  drafts?: Record<string,ReviewDraft>
  notice?: ReactNode
  onLocate: (finding: Finding, index: number, replace?: boolean) => void
  onDecision: (finding: Finding, action: string) => void
  onSupplement: (finding: Finding, mode: SupplementMode) => void
}

export function ReviewResultsList({ initialMode, run, version, cid, locked, ready, canApply = true, locateLocked = locked, active = false, compactStream=false, drafts = {}, notice, focusedBlockId, activeEvidenceKey, onLocate, onDecision, onSupplement }: Props) {
  const view = buildReviewResultView(run)
  const order=useRef<string[]>([])
  const ordered=stableIssueOrder(order.current,[...view.pending,...view.handled])
  useEffect(()=>{order.current=ordered.map(f=>f.id)},[run.issues,run.findings])
  const pendingIds=new Set(view.pending.map(f=>f.id))
  view.pending=ordered.filter(f=>pendingIds.has(f.id));view.handled=ordered.filter(f=>!pendingIds.has(f.id))
  const { decisions } = summarizeReview(run)
  const [mode,setMode]=useState<'risk'|'clause'>(initialMode??'risk')
  const [riskType,setRiskType]=useState('all')
  const [jump,setJump]=useState<{kind:'finding'|'clause';id:string}|null>(null)
  const root=useRef<HTMLDivElement>(null)
  const [filter, setFilter] = useState<'pending' | 'handled'>(view.defaultFilter)
  const [category, setCategory] = useState<ResultCategory | 'all'>('all')
  const [revisionChoices,setRevisionChoices]=useState<Record<string,Record<string,boolean>>>({risk:{},clause:{}})
  const [returnPoint,setReturnPoint]=useState<{mode:typeof mode;filter:typeof filter;category:typeof category;riskType:string;expanded:string|null|undefined;scroll:{element:HTMLElement;top:number}[]}|null>(null)
  const [restoreScroll,setRestoreScroll]=useState<{element:HTMLElement;top:number}[]|null>(null)
  const rememberPosition=()=>{const scroll:{element:HTMLElement;top:number}[]=[];let element:HTMLElement|null=root.current;while(element){if(element.scrollHeight>element.clientHeight)scroll.push({element,top:element.scrollTop});element=element.parentElement}setReturnPoint({mode,filter,category,riskType,expanded,scroll})}
  const returnToSource=()=>{if(!returnPoint)return;setMode(returnPoint.mode);setFilter(returnPoint.filter);setCategory(returnPoint.category);setRiskType(returnPoint.riskType);setExpanded(returnPoint.expanded);setJump(null);setRestoreScroll(returnPoint.scroll);setReturnPoint(null)}
  useEffect(()=>{if(!restoreScroll)return;const frame=requestAnimationFrame(()=>{for(const {element,top} of restoreScroll)element.scrollTop=top;setRestoreScroll(null)});return ()=>cancelAnimationFrame(frame)},[restoreScroll])
  // undefined selects the first visible item; null is an intentional collapse.
  const [expanded, setExpanded] = useState<string | null | undefined>(undefined)
  const [allChoices,setAllChoices]=useState<Record<string,Record<string,boolean>>>({risk:{},clause:{}})
  const choices=allChoices[mode]
  const setChoices=(update:(v:Record<string,boolean>)=>Record<string,boolean>)=>setAllChoices(old=>({...old,[mode]:update(old[mode])}))
  // Streaming updates must not reopen or replace the card the reader chose.
  useEffect(()=>{if(focusedBlockId){const f=[...view.pending,...view.handled].find(i=>(i.event_anchor?[i.event_anchor]:i.evidence??[]).some(e=>e.block_id===focusedBlockId));setExpanded(f?.id??null);if(f)setChoices(v=>({...v,[f.id]:true}))}},[focusedBlockId])
  const candidates = filter === 'pending' ? view.pending : view.handled
  const visible = compactStream ? ordered : candidates.filter(f => (category === 'all' || resultCategory(f) === category) && (riskType==='all'||resultCategory(f)==='clauses'&&riskCategory(f)===riskType))
  const limit = visible.some(f=>f.execution_mode==='liability_clause')
    ? run.rule_results?.find(r=>r.rule_id==='VL-01')?.numeric_grounding
    : undefined
  useEffect(()=>{if(expanded===undefined&&visible[0])setExpanded(visible[0].id)},[expanded,visible[0]?.id])
  useEffect(()=>{if(active&&!compactStream)setChoices(old=>{const next={...old};let changed=false;for(const f of visible)if(next[f.id]===undefined){next[f.id]=true;changed=true}return changed?next:old})},[active,compactStream,run.issues,run.findings])
  const activeId = expanded === null ? null : visible.some(f => f.id === expanded) ? expanded : visible[0]?.id
  const filtered = !compactStream && (category !== 'all' || riskType!=='all')
  const structured = run.result_schema_version === 'interactive-review-v3'
  const clauseResults=structured?groupClauseResults(ordered,run,version):[]
  const visibleIds=new Set(visible.map(f=>f.id))
  const visibleGroups=clauseResults.filter(g=>g.issues.some(f=>visibleIds.has(f.id)))
  const grouped=structured&&mode==='clause'
  const empty=resultEmptyState(run,filtered,!compactStream&&filter==='handled',view.handled.length>0)
  const clearFilters=()=>{setCategory('all');setRiskType('all');setExpanded(undefined)}
  const navigateFinding=(f:Finding)=>{rememberPosition();clearFilters();setFilter(pendingIds.has(f.id)?'pending':'handled');setMode('risk');setAllChoices(old=>({...old,risk:{...old.risk,[f.id]:true}}));setExpanded(f.id);setJump({kind:'finding',id:f.id})}
  const navigateClause=(id:string)=>{rememberPosition();clearFilters();const g=clauseResults.find(g=>g.id===id);if(g)setFilter(g.issues.some(f=>pendingIds.has(f.id))?'pending':'handled');setJump({kind:'clause',id})}
  useEffect(()=>{if(!jump)return;const el=Array.from(root.current?.querySelectorAll<HTMLElement>(jump.kind==='finding'?'[data-finding-id]':'[data-clause-result]')??[]).find(el=>el.getAttribute(jump.kind==='finding'?'data-finding-id':'data-clause-result')===jump.id);if(el){el.scrollIntoView({block:'nearest'});const button=el.querySelector<HTMLElement>('button,summary');button?.focus({preventScroll:true});setJump(null)}},[jump,mode,filter,riskType,category])
  // Never silently drop proposals whose event is absent from the actionable list.
  const unlinked = structured ? orderRevisionProposals((run.revision_proposals ?? []).filter(p => !(run.issues??run.findings).some(f => f.event_id && p.event_ids.includes(f.event_id))),version) : []

  const renderFinding=(f:Finding,index:number,grouped:boolean)=> drafts[f.id]&&!f.review_state?<ReviewDraftCard key={f.id} number={index+1} draft={drafts[f.id]} collapsed={!(choices[f.id]??true)} onExpandedChange={open=>setChoices(v=>({...v,[f.id]:open}))}/>:<ReviewFindingCard key={f.id} draft={drafts[f.id]} number={index + 1} finding={f} onNavigateFinding={navigateFinding} hideRevision={grouped} activeEvidenceKey={activeEvidenceKey} run={run} decision={decisions.get(f.id)} version={version} cid={cid} locked={locked} locateLocked={locateLocked} ready={ready} canApply={canApply && !structured} collapsed={!(choices[f.id]??(!compactStream&&active||activeId===f.id))} onExpandedChange={open => {setChoices(v=>({...v,[f.id]:open}));setExpanded(open ? f.id : null)}} onLocate={(i, replace) => onLocate(f, i, replace)} onLocateEvidence={e=>onLocate({...f,event_anchor:e},-1)} onDecision={action => onDecision(f, action)} onSupplement={mode => onSupplement(f, mode)} />

  const categories=!compactStream&&<div className="result-category-tabs" role="group" aria-label="风险类型">
    {[{id:'all',label:'全部'},...riskCategories.filter(c=>c.id!=='other'||ordered.some(f=>resultCategory(f)==='clauses'&&riskCategory(f)==='other'))].map(c=>{
      const count=c.id==='all'?candidates.length:candidates.filter(f=>resultCategory(f)==='clauses'&&riskCategory(f)===c.id).length
      return <button type="button" key={c.id} aria-pressed={riskType===c.id&&category==='all'} onClick={()=>{setRiskType(c.id);setCategory('all')}}>{c.label}<small>{count}</small></button>
    })}
    {view.categories.filter(c=>c.id!=='clauses').map(c=><button type="button" key={c.id} aria-pressed={category===c.id} onClick={()=>{setRiskType('all');setCategory(c.id)}}>{c.label}<small>{candidates.filter(f=>resultCategory(f)===c.id).length}</small></button>)}
  </div>
  const changeFilter=(value:typeof filter)=>{setFilter(value);setExpanded(undefined)}
  const findings=<div className="review-findings">
    {grouped?visibleGroups.map(g=>resultCategory(g.issues[0])!=='clauses'?renderFinding(g.issues[0],ordered.findIndex(f=>f.id===g.issues[0].id),false):<ReviewClauseResult key={g.id} group={g} onNavigateClause={navigateClause} onNavigateFinding={navigateFinding} run={run} version={version} locked={locked} locateLocked={locateLocked||!ready} onLocate={(f,e)=>onLocate({...f,event_anchor:e},-1)} renderIssue={f=>renderFinding(f,ordered.findIndex(item=>item.id===f.id),true)}/>):visible.map(f=>renderFinding(f,ordered.findIndex(finding=>finding.id===f.id),false))}
    {!(grouped?visibleGroups.length:visible.length) && <div className="result-empty" role="status"><FileCheck2 /><strong>{empty.title}</strong><p>{empty.text}</p>{filtered && <Button variant="outline" size="sm" onClick={clearFilters}>清除筛选</Button>}</div>}
  </div>
  return <RevisionDisclosureContext.Provider value={{choices:revisionChoices[mode],setChoice:(id,collapsed)=>setRevisionChoices(old=>({...old,[mode]:{...old[mode],[id]:collapsed}}))}}><div ref={root}><Tabs className="result-browser" value={filter} onValueChange={value=>changeFilter(value as typeof filter)}>
    {!compactStream&&<><div className="result-status-bar">
      <TabsList variant="line" className="result-status-tabs" aria-label="意见处理状态">
        <TabsTrigger value="pending">{active?'阶段性意见':'待处理'} <span>{view.pending.length}</span></TabsTrigger>
        <TabsTrigger value="handled">已处理 <span>{view.handled.length}</span></TabsTrigger>
      </TabsList>
    </div>
    {categories}</>}
    <div className="result-list-notices">{notice}
      {view.contextWarnings.length > 0 && <aside className="review-context-warning" role="status"><strong>待核对事项</strong>{view.contextWarnings.map(w => <p key={w}>{w}</p>)}</aside>}
    </div>
    {run.issues?.some(f=>['merged','retracted'].includes(f.review_state??''))&&<details className="review-reconciliation-history"><summary>整体复核变更记录</summary>{run.issues.filter(f=>['merged','retracted'].includes(f.review_state??'')).map(f=><article key={f.id}><strong>{f.review_state==='merged'?'已合并':'已撤回'} · {f.title}</strong><p>{f.reconciliation_note}</p>{f.related_issue_key&&<p>保留意见：{run.issues?.find(i=>(i.event_id??i.subject_key??i.rule_id)===f.related_issue_key)?.title??'关联核查项'}</p>}<details><summary>查看初步意见</summary><p>{f.reconciliation?.previous_explanation??f.explanation}</p></details></article>)}</details>}
    {limit&&!Array.isArray(limit)&&limit.confirmed&&limit.internal_limit_yuan&&<p className="result-counts">
      累计责任限额 {limit.internal_limit_yuan} 元
    </p>}
    {!compactStream&&<p className="result-counts">{view.riskEventCount} 个风险 · {clauseResults.filter(g=>g.issues.some(f=>resultCategory(f)==='clauses')).length} 个条款 · {new Set((run.revision_proposals??[]).map(p=>p.proposal_id??p.id)).size} 条修订</p>}
    <span className="result-live-count sr-only" aria-live="polite">当前显示 {grouped?visibleGroups.length:visible.length} 项{structured ? `；问题事件 ${view.riskEventCount}；修改建议 ${view.proposalCount}` : ''}</span>
    {compactStream?<section className="result-list-content" aria-label="审查意见">{findings}</section>:
      (['pending','handled'] as const).map(state=><TabsContent value={state} key={state} className="result-list-content">{findings}</TabsContent>)}
    {unlinked.length > 0 && <details className="revision-proposals"><summary>其他修改建议（{unlinked.length}）</summary>{unlinked.map(p => <RevisionProposalCard key={p.proposal_id ?? p.id} proposal={p} run={run} version={version} locked={locked} />)}</details>}
  </Tabs>{returnPoint&&<button type="button" className="result-return-link" onClick={returnToSource}>← 返回跳转前的位置</button>}</div></RevisionDisclosureContext.Provider>
}
