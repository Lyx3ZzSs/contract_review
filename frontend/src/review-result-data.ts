import type { Risk } from './data'
import type { Decision, ReviewState } from './review-state'
import type { WorkbenchContract } from './workbench-data'

export const conclusions = ['建议按修订稿推进', '待业务确认', '暂不建议推进'] as const
export type Conclusion = typeof conclusions[number]
export interface CompletionInput { conclusion: Conclusion; opinion: string; reservations: string; acknowledged: boolean }
export interface ReviewResult {
  id: string; revision: number; completedAt: string; reviewer: string
  conclusion: Conclusion; opinion: string; reservations: string
  contract: Pick<WorkbenchContract,'id'|'number'|'title'|'counterpart'|'position'|'reviewConfig'>
  isDemo: boolean; rules: string; documentName: string; document: Blob
  risks: (Risk & {decision: Decision})[]; changes: number; comments: number
}
