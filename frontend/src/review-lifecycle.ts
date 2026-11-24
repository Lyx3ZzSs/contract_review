import type {Finding,ServerRun} from './backend-api'
export function reviewLifecycle(f:Finding,run:ServerRun){
 const active=['queued','running'].includes(run.status)
 const labels={preliminary:'初步意见',drafting:'正在生成修改',pending_reconciliation:'待整体复核',reviewed:'已完成整体复核',adjusted:'整体复核已调整',merged:'已合并',retracted:'已撤回',incomplete:'本项未完成'}
 const state=f.review_state
 return {label:state?labels[state]:active?'阶段性意见':'',message:f.review_state_reason??(state==='preliminary'?'初步判断，修改方案和整体复核尚未完成。':state==='pending_reconciliation'?'本项核查已返回，仍需检查与其他意见的关系。':active?'审查尚未结束，意见可能继续调整。':''),archived:state==='merged'||state==='retracted'}
}
