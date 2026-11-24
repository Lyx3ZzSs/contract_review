import type { PartyDetails } from './party-types'
import { remoteContracts } from './backend-api'
import type { Conclusion } from './review-result-data'
import type { ReviewConfiguration } from './rule-data'

export type ContractStatus = '待审阅' | '审阅中' | '待业务确认' | '已完成'
export interface WorkbenchContract {
  reviewActive?: boolean
  partyDetails?: PartyDetails
  id: string; number: string; title: string; counterpart: string; type: string
  owner: string; department: string; deadline: string; updated: string
  status: ContractStatus; amount: string; project: string; position: string
  high: number; medium: number; low: number; processed: number; total: number
  hasDocument: boolean; example: boolean; note: string; reviewConfig?: ReviewConfiguration; resultSummary?: {revision:number;conclusion:Conclusion;opinion:string;completedAt:string;ignored:number}
}
export const contractTypes = ['功率预测服务', '软件采购', '技术开发', '运维服务', '保密协议', '其他', '未分类']
export const owners = ['我', '待分配']
export async function loadContracts(): Promise<WorkbenchContract[]> {
  return remoteContracts()
}
