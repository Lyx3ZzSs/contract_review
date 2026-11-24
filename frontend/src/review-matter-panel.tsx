import type {ReactNode} from 'react'
import type {ReviewMatter} from './review-matters'
import type {ReferenceVisit} from './review-reference'
const labels={queued:'等待核查',checking:'正在核查',settling:'等待核查意见',attention:'有意见待核对',incomplete:'核查未完成',finished:'本项任务已结束'}
export function ReviewMatterPanel({matters,current,visit,disabled,onSelect,onReturn,onRetry,children}:{matters:ReviewMatter[];current?:ReviewMatter;visit:ReferenceVisit|null;disabled:boolean;onSelect:(matter:ReviewMatter)=>void;onReturn:()=>void;onRetry:()=>void;children?:ReactNode}){
 if(!matters.length)return null
 const related=current?.evidence.filter(e=>e.block_id!==current.anchor.block_id)??[]
 const index=matters.findIndex(m=>m.id===current?.id),next=matters.slice(index+1).find(m=>m.phase!=='queued')
 const readingLabel=visit?({locating:'正在定位关联依据',viewing:'正在查看关联依据',returning:'正在返回事项原文',paused:'关联核对已暂停',error:'关联依据定位未完成'})[visit.phase]:'正在查看事项原文'
 return <section className="review-matter-panel" aria-label="当前核查事项" data-matter-id={current?.id}>
  <div className="matter-heading"><strong>当前核查事项</strong>{current&&<span data-matter-phase={current.phase}>{labels[current.phase]}</span>}</div>
  {current?<><h3>{current.title}</h3><p>{current.detail}</p>
   <div className="matter-reading-context"><strong>{readingLabel}</strong><span role="status">{visit?`为核对「${current.title}」查看关联原文；当前事项保持不变。`:related.length?`本事项另有 ${related.length} 处关联依据，可在下方逐一核对。`:'新的核查结果会更新本事项；正文保持当前阅读位置。'}</span>{visit&&<><span>{visit.message??visit.destination.title}</span><div className="reading-actions"><button disabled={disabled} onClick={onReturn}>返回事项原文</button>{['error','paused'].includes(visit.phase)&&<button disabled={disabled} onClick={onRetry}>重新定位证据</button>}</div></>}</div>
   {children}</>:<p>等待后台开始具体核查；可选择一个事项查看原文。</p>}
  {current&&<div className="reading-actions"><button disabled={disabled||!!visit||!next} onClick={()=>next&&onSelect(next)}>查看下一事项</button></div>}
  <details className="matter-queue"><summary>本轮核查事项（{matters.length}）</summary><ol>{matters.map(m=><li key={m.id}><button disabled={disabled} aria-current={m.id===current?.id?'step':undefined} onClick={()=>onSelect(m)}><span>{m.title}</span><small>{labels[m.phase]}</small></button></li>)}</ol></details>
 </section>
}
