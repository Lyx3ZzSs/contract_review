import type { RiskStatus } from './data'
import type { ReviewResult } from './review-result-data'
export interface Decision { status: RiskStatus; replacement: string; note: string }
export interface Activity { id: string; riskId: string; action: string; time: string }
export interface ReviewState { version: 1; decisions: Record<string, Decision>; activity: Activity[]; completed: boolean; results?: ReviewResult[]; reopenedAt?: string }
export function initialState(): ReviewState {
  return {version:1, decisions:{}, activity:[], completed:false}
}
