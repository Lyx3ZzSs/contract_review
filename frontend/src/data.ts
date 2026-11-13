export type RiskStatus = 'pending' | 'accepted' | 'ignored'
export type Severity = 'high' | 'medium' | 'low'
export interface Risk {
  id: string; title: string; severity: Severity; chapter: number; clause: string;
  category: string; original: string; suggestion: string; explanation: string;
  rule: string; rationale: string; reference: string; referenceText: string
}
export const severityLabel: Record<Severity, string> = {high:'高风险',medium:'中风险',low:'提示'}
export const statusLabel: Record<RiskStatus, string> = {pending:'待处理',accepted:'已采纳',ignored:'已忽略'}
