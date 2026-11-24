import {ChevronDown} from 'lucide-react'
import type {ReviewDraft} from './review-execution'
import {draftRiskText} from './review-card-content'

export function ReviewDraftCard({draft,number,collapsed,onExpandedChange}:{draft:ReviewDraft;number:number;collapsed:boolean;onExpandedChange:(open:boolean)=>void}){
 const {issue,fields,state}=draft
 const label=state==='failed'?'未完成':state==='validating'?'核对原文与修改范围':'正在生成'
 const risk=draftRiskText(draft)
 return <article className={`review-finding stream-card stream-${state}`} data-finding-id={issue.id} aria-label={issue.title??'条款核查'}>
  <div className="result-row-header"><span className="result-number">{String(number).padStart(2,'0')}</span><div className="result-row-main">
   <button type="button" className="result-row" aria-expanded={!collapsed} onClick={()=>onExpandedChange(collapsed)}><span className="result-row-title">{issue.title??'条款核查'}</span><ChevronDown className={collapsed?'':'is-open'}/></button>
   <div className="stream-status" role="status"><span>{label}</span>{draft.revision>1&&<span>重新生成 · 第 {draft.revision} 次</span>}</div>
  </div></div>
  {!collapsed&&<div className="result-detail">
   <section className="result-explanation"><h4>风险概述</h4>{risk?<p data-reading-anchor={`${issue.id}:explanation`} className="stream-text">{risk}</p>:<p className="stream-wait">正在核查相关条款，等待模型输出…</p>}</section>
   {fields.modification_plan&&<section className="result-modification-plan"><h4>修改方案</h4><p className="stream-text" data-reading-anchor={`${issue.id}:plan`}>{fields.modification_plan}</p></section>}
   <ReviewDraftContent draft={draft}/>
  </div>}
 </article>
}

export function ReviewDraftContent({draft}:{draft:ReviewDraft}){
 const fields=draft.fields
 const edits=Array.from({length:5},(_,i)=>({i,text:fields[`edit:${i}:after_text`],reason:fields[`edit:${i}:rationale`]})).filter(e=>e.text!==undefined||e.reason)
 return <section className={`stream-card stream-${draft.state}`} aria-label="正在生成的修改建议">
  <h4>具体修订 <small>{draft.state==='failed'?'未完成':draft.state==='validating'?'正在核对原文与修改范围':'生成中'}</small></h4>
  {edits.map(e=><div className="stream-proposal" key={e.i}>{e.text!==undefined&&<p className="stream-text" data-reading-anchor={`${draft.issue.id}:edit:${e.i}`}>{e.text||'建议删除原文片段，具体范围正在核验。'}</p>}{!fields.modification_plan&&e.reason&&<p className="stream-rationale">{e.reason}</p>}</div>)}
  {!edits.length&&<p className="stream-wait">正在结合原文拟定修改，等待模型返回…</p>}
  <p className="stream-disclaimer">{draft.state==='failed'?'以下候选内容未完成核验，不能用于修改正文。':'候选内容，核验完成后显示修注预览。'}</p>
  {draft.message&&<p className="stream-error" role="status">{draft.message}</p>}
 </section>
}
