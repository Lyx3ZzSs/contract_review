import {useState,useEffect,useRef} from 'react'
import {Check,ChevronDown,LoaderCircle,AlertCircle,Circle,Minus} from 'lucide-react'
import type {ExecutionState} from './review-execution'
import type {Evidence,Version} from './backend-api'
import {artifactSections,processTaskTitle,reviewProcess,CONFIGURED_REVIEW_POLICY,type ProcessItem,type ProcessState,type ProcessSection,type ProcessRules} from './review-process'
import {evidenceLabel} from './review-card-content'
import {MaterialEvidencePreview} from './material-evidence-preview'
import './review-agent.css'

const labels:Record<ProcessState,string>={queued:'等待',running:'进行中',completed:'完成',failed:'未完成',unavailable:'未记录',attention:'待核实'}
function StatusIcon({state}:{state:ProcessState}){
 return state==='running'?<Minus size={14} aria-hidden="true"/>:state==='completed'?<Check size={14}/>:['failed','attention'].includes(state)?<AlertCircle size={14}/>:<Circle size={13}/>
}
type Sources={version:Version|null;cid:string;bundleId?:string}
type LocationProps={onLocate:(e:Evidence)=>void;disabled:boolean;sources?:Sources}
function Content({section,onLocate,disabled,sources,type=false}:{section:ProcessSection;type?:boolean}&LocationProps){
 const [expanded,setExpanded]=useState(false)
 return <section data-reading-anchor={`analysis:${section.key}`} className={section.provisional?'agent-provisional':''}>
  {!type&&!section.check_id&&section.title&&<h4>{section.title}</h4>}
  {type?<div className="agent-facts">{section.text.split('\n').filter(Boolean).map((line,i)=><span key={i}>{line}</span>)}</div>:<p>{section.text}</p>}
  {section.evidence.length>0&&<div className="agent-source-links">{(expanded?section.evidence:section.evidence.slice(0,3)).map((e,j)=>{
   const key=`${e.block_id}:${e.start}:${j}`
   if(sources?.bundleId&&sources.version&&!sources.version.blocks.some(block=>block.id===e.block_id))return <MaterialEvidencePreview key={key} cid={sources.cid} bundleId={sources.bundleId} evidence={e}/>
   const label=sources?evidenceLabel(sources.version,e):`原文依据 ${j+1}`
   return <button type="button" key={key} aria-label={sources?`定位${label}`:undefined} disabled={disabled} onClick={()=>onLocate(e)} title={e.quote}>{label}</button>
  })}{section.evidence.length>3&&<button type="button" aria-expanded={expanded} onClick={()=>setExpanded(v=>!v)}>{expanded?'收起依据':`全部 ${section.evidence.length} 处依据`}</button>}</div>}
 </section>
}
function CheckSteps({steps,...location}:{steps:NonNullable<ProcessItem['steps']>}&LocationProps){
 return <ul className="agent-check-steps">{steps.map(task=><li key={task.id} data-reading-anchor={`task:${task.id}`}>
  <div><StatusIcon state={task.state}/><span>{task.title}</span><small>{labels[task.state]}</small></div>
  {task.message&&<p className="agent-step-note">{task.message}</p>}
  {task.sections?.map((section,i)=><Content key={i} section={{...section,key:task.id+i,provisional:false}} {...location}/>)}
 </li>)}</ul>
}
function BasicRuleRow({item,...location}:{item:ProcessItem}&LocationProps){
 const [choice,setChoice]=useState<boolean|null>(null)
 const steps=item.steps??[],fields=item.formEntries??[]
 const open=choice??item.state==='running'
 const details=steps.length>0||fields.length>0
 const awaitingResult=item.state==='running'&&steps.length>0&&steps.every(step=>step.state==='completed')
 const heading=<><StatusIcon state={item.state}/><span>{item.title}</span><small>{item.statusLabel??(awaitingResult?'等待结论':labels[item.state])}</small></>
 return <div className={`agent-process-row agent-rule-row process-${item.state}`} data-reading-anchor={`process:${item.id}`}>
  {details?<button type="button" className="agent-process-label" aria-expanded={open} title={open?'收起核查过程':'展开核查过程'} onClick={()=>setChoice(!open)}>
   {heading}<ChevronDown size={13} className={open?'is-open':''}/>
  </button>:<div className="agent-process-label">{heading}</div>}
  {!!item.sections.length&&<div className="agent-process-content">{item.sections.map(section=><Content key={section.key} section={section} {...location}/>)}</div>}
  {item.message&&item.state==='failed'&&<p className="agent-error">{item.message}</p>}
  {item.revisionMessage&&<p className="agent-revision-status">{item.revisionMessage}</p>}
  {open&&details&&<div className="agent-rule-details">
   {!!steps.length&&<CheckSteps steps={steps} {...location}/>}
   {!!fields.length&&<div className="agent-process-content">{fields.map(entry=><Content key={entry.key} section={entry} {...location}/>)}</div>}
  </div>}
 </div>
}
function ProcessRow({item,onLocate,disabled,sources}:{item:ProcessItem}&LocationProps){
 const [choice,setChoice]=useState<boolean|null>(null)
 if(item.basicCheck)return <BasicRuleRow item={item} onLocate={onLocate} disabled={disabled} sources={sources}/>
 const open=choice??true
 return <div className={`agent-process-row process-${item.state}`} data-reading-anchor={`process:${item.id}`}>
  <button type="button" className="agent-process-label" onClick={()=>setChoice(!open)} aria-expanded={open}><StatusIcon state={item.state}/><span>{item.title}</span><small>{item.statusLabel??labels[item.state]}</small><ChevronDown size={13} className={open?'is-open':''}/></button>
  {open&&<>
   {!!item.steps?.length&&<CheckSteps steps={item.steps} onLocate={onLocate} disabled={disabled} sources={sources}/>}
   {!!item.clauses?.length&&<ul className="agent-check-steps">{item.clauses.map(row=><li key={row.id} data-reading-anchor={`clause-progress:${row.id}`}>
    <div><StatusIcon state={row.state}/><button type="button" className="agent-clause-link" disabled={disabled} onClick={()=>onLocate(row.anchor)} title={row.anchor.quote}>{row.issue?.title||row.anchor.quote}</button></div>
    <small>{row.message}</small>
    {row.issue?.sections.map(section=><Content key={section.key} section={section} onLocate={onLocate} disabled={disabled} sources={sources}/>)}
   </li>)}</ul>}
   {!!item.sections.length&&<div className="agent-process-content">{item.sections.map(section=><Content key={section.key} section={item.id==='consistency'?{...section,check_id:undefined}:section} onLocate={onLocate} disabled={disabled} sources={sources} type={item.id==='type'}/>)}
   {item.revisionMessage&&<p className="agent-revision-status">{item.revisionMessage}</p>}</div>}
   {item.id==='transaction-overview'&&item.state==='completed'&&!item.sections.length&&<p className="agent-caption">本轮未提取到有原文依据的交易约定。</p>}
   {item.state==='running'&&!item.id.startsWith('rule:')&&!item.steps?.length&&<p className="agent-caption">{item.message||(item.id==='transaction-overview'?'交易分析按段核对原文后显示。':item.sections.length?'内容持续更新，引用核对后可定位原文。':'正在核查，等待分析内容…')}</p>}
   {item.state==='unavailable'&&<p className="agent-caption">本轮未记录此项独立过程。</p>}
   {item.state==='failed'&&<p className="agent-error">{item.message??'本项未完成，已返回内容仍可查看。'}</p>}
  </>}
 </div>
}
export function ReviewAgentPanel({state,onLocate,disabled,policyVersion,run,sources,reading=false}:{reading?:boolean;state:ExecutionState;policyVersion?:string;run?:ProcessRules}&LocationProps){
 const [historyOpen,setHistoryOpen]=useState<boolean|null>(null)
 const [keepProcess,setKeepProcess]=useState<boolean|null>(null)
 const watched=useRef(false)
 const activeRun=['queued','running'].includes(state.status)
 useEffect(()=>{if(activeRun)watched.current=true},[activeRun])
 const phases=Object.values(state.phases??{}),artifacts=Object.values(state.artifacts??{})
 if(!phases.length&&!artifacts.length)return null
 const inProgress=['queued','running'].includes(state.status),failed=phases.filter(p=>p.state==='failed')
 const tasks=Object.values(state.tasks??{}),taskFailures=tasks.filter(t=>t.state==='failed'),running=tasks.filter(t=>t.state==='running'),done=tasks.filter(t=>t.state==='completed')
 const incomplete=state.status==='failed'||failed.length>0||taskFailures.length>0
 const configured=policyVersion===CONFIGURED_REVIEW_POLICY
 const active=phases.filter(p=>p.state==='running')
 const drafting=active.some(p=>p.id==='drafting')
 const specificTasks=running.filter(t=>t.id.startsWith('base:liability-limit:'))
 const currentTask=specificTasks.some(t=>t.id.endsWith('-perspective'))?'核对责任条款对我方的影响':
  specificTasks.some(t=>t.id.includes(':group-'))?'核查责任条款':specificTasks.length?'核对责任金额与适用范围':
  running.length===1?processTaskTitle(running[0]):undefined
 const overview=state.artifacts?.['transaction-overview']
 const rulePhase=state.phases?.rules
 const handoff=configured&&inProgress&&!!rulePhase&&['completed','failed'].includes(rulePhase.state)&&Object.values(state.issues).some(i=>i.review_state==='reviewed'&&['flag','insufficient_evidence'].includes(i.status))
 const configuredSummary=drafting?'风险已返回，正在生成候选改文':overview&&['generating','validating'].includes(overview.state)&&rulePhase?.state==='completed'?'正在整理交易概况':currentTask?`正在${currentTask}`:'正在核查合同'
 const summary=inProgress?(configured?configuredSummary:drafting?'风险检查已返回，正在生成修改稿':active.some(p=>p.id==='synthesis')?'正在复核风险意见':active.length?'审核中':'正在准备核查任务'):'本轮审查已完成，待人工复核'
 const process=reviewProcess(state,policyVersion,run),expanded=inProgress?(keepProcess??true):(historyOpen??(configured&&(keepProcess??(reading||watched.current))))
 const verifiedRuleCount=new Set(Object.values(state.issues??{}).filter(i=>i.review_state==='reviewed'&&i.execution_state!=='failed'&&i.execution_state!=='not_run').map(i=>i.rule_id)).size
 const order=['parse','transaction','rules','discovery','synthesis','drafting','verification']
 const otherArtifacts=artifacts.filter(a=>!a.id.startsWith('transaction')&&!a.id.startsWith('discovery'))
 return <section className="review-agent-panel" aria-label="合同审查过程">
  {(inProgress||(!configured&&!incomplete))&&<div className="agent-current" role="status">{inProgress?<LoaderCircle className="review-spinner" size={14} aria-hidden="true"/>:<StatusIcon state="completed"/>}<div><strong>{summary}{configured&&verifiedRuleCount>0&&` · 已有 ${verifiedRuleCount} 项规则返回结论`}</strong>{inProgress&&!configured&&<p>已生成的分析会显示在下方，审查完成后展示风险与修改建议。</p>}</div></div>}
  {handoff&&<button type="button" className="agent-history-toggle" aria-expanded={expanded} onClick={()=>setKeepProcess(!expanded)}>{expanded?'收起审查过程':'查看审查过程'}<ChevronDown size={14}/></button>}
  {!inProgress&&<button className="agent-history-toggle" aria-expanded={expanded} onClick={()=>setHistoryOpen(!expanded)}>{expanded?'收起审查过程':'查看审查过程'}<ChevronDown size={14}/></button>}
  {expanded&&<div className="agent-process-groups" onClick={()=>{if(inProgress&&configured)setKeepProcess(true)}}>
   {!!process.transaction.length&&<section className="agent-process-group"><h3>合同交易分析</h3>{process.transaction.map(item=><ProcessRow key={item.id} item={item} onLocate={onLocate} disabled={disabled} sources={configured?sources:undefined}/>)}</section>}
   {!!process.risk.length&&<section className="agent-process-group"><h3>合同风险识别</h3>{process.risk.map(item=><ProcessRow key={item.id} item={item} onLocate={onLocate} disabled={disabled} sources={configured?sources:undefined}/>)}</section>}
   {(!configured||!inProgress)&&<details className="agent-coverage" open={configured||undefined}><summary>查看详细执行记录</summary>
    {!!tasks.length&&<p>已完成 {done.length} 项 · 进行中 {running.length} 项{taskFailures.length>0?` · 未完成 ${taskFailures.length} 项`:''}</p>}
    <ol className="agent-phases">{[...phases].sort((a,b)=>order.indexOf(a.id)-order.indexOf(b.id)).map(p=><li key={p.id} className={`phase-${p.state}`}><span>{p.title}</span><small>{labels[p.state]}</small>{p.message&&<p>{p.message}</p>}</li>)}</ol>
    {!!state.coverage?.length&&<div>本轮核查范围 · {state.coverage.reduce((n,c)=>n+c.block_ids.length,0)} 个段落{state.coverage.map(c=><div key={c.batch}><strong>第 {c.batch} 部分</strong>{c.state==='failed'&&<p>{c.message}</p>}{c.topics?.map(t=><p key={t.topic}><b>{t.topic} · {{checked:'已检查',not_applicable:'不适用',insufficient_evidence:'依据不足'}[t.status]}</b><span>{t.reason}</span></p>)}</div>)}</div>}
    {otherArtifacts.map(a=><article className="agent-artifact" key={a.id}><h4>{a.title}</h4>{artifactSections(a).map(s=><Content key={s.key} section={s} onLocate={onLocate} disabled={disabled}/>)}{a.state==='failed'&&<p className="agent-error">{a.message}</p>}</article>)}
   </details>}
  </div>}
 </section>
}
