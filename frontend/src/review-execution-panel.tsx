import {processTaskTitle} from './review-process'
import type { ExecutionState } from './review-execution'
import type { Evidence } from './backend-api'
export function ReviewExecutionPanel({state,onLocate,canLocate}:{state:ExecutionState;onLocate:(anchor:Evidence)=>void;canLocate:boolean}){
 const tasks=Object.values(state.tasks).sort((a,b)=>(a.first_seq??0)-(b.first_seq??0)),done=tasks.filter(t=>t.state==='completed').length,failed=tasks.filter(t=>t.state==='failed').length
 if(!tasks.length)return null
 return <section className="review-execution" aria-label="本轮审查任务">
 <strong>本轮审查任务</strong><p role="status">已识别 {tasks.length} 项 · 完成 {done} 项{failed>0?` · 未完成 ${failed} 项`:''}</p>
 <p className="review-execution-note">意见通过证据校验后陆续显示，最终结论以本轮汇总为准。</p>
 <ul>{tasks.map(t=><li key={t.id}><span className={`execution-state ${t.state}`}>{({queued:'等待',running:'核查中',completed:'完成',failed:'未完成'})[t.state]}</span><span>{processTaskTitle(t)??'核查相关条款'}{t.message&&<small>{t.message}</small>}</span>{t.anchor&&<button type="button" disabled={!canLocate} onClick={()=>onLocate(t.anchor!)}>定位</button>}</li>)}</ul>
 </section>
}
