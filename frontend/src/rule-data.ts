import { api } from './backend-api'

export const positions = ['乙方 · 服务提供方', '甲方 · 采购方', '中立审查'] as const
export type Position = typeof positions[number]
export interface RedlineRule {
  execution_mode?: 'confirmed_rule'|'case_advisory'; source_ids?: string[]; policy_threshold?: number|null
  id: string; title: string; version: string; source_principle: string; proposed_scope: string
  trigger: string; non_trigger_or_exceptions: string[]; required_inputs: string[]
  insufficient_evidence_behavior: string; proposed_output: string; authority: string
  severity: string; enabled: boolean; execution_logic_status: string
}
export interface RulePack {
  presentation: RulePresentation
  version: string; pack_sha256: string; rules: RedlineRule[]
  execution_policy: {version: string; prompt_sha256: string; instructions: string; mode: string; scope: string; production_approved: boolean}
}
export interface ReviewConfiguration {
  mode: 'rules' | 'manual'; position: Position; contractType: string; createdAt: string
  // Informational at upload. The server snapshots the actual policy when a review starts.
  policyVersion?: string; rulePackVersion?: string
}
export const loadRules = () => api<RulePack>('/rules')

export interface RulePresentation {
  version: string
  items: Record<string, {title: string; summary: string}>
  current_scope: string
  sources: {id: string; filename: string; sha256: string}[]
  confirmation: {id: string; date: string; user_statement: string; scope: string; pending_configuration: string[]; not_covered: string[]}
}
export interface CaseTrial {
  repeat: number; status: string; actual: string; passed: boolean | null; explanation: string
  evidence: {block_id: string; quote: string}[]; error_code: string | null
  policy_version: string; prompt_sha256: string; created_at: string; model: string; rejected_attempts: number
}
export interface RuleCase {
  id: string; category: 'historical' | 'engineering' | 'attachment'; title: string
  expected: string; label_status: string; approved_for_scoring: boolean
  excerpts: {location: string; text: string; source_id?: string}[]
  reviewer_comment?: string; trials: CaseTrial[]; limitation: string; source_file: string
}
export interface RuleCases {
  rule_id: string; cases: RuleCase[]
  summary: {historical_cases: number; engineering_cases: number; recorded_requests: number; differences: number; failed_requests: number}
}
export const loadRuleCases = (id: string) => api<RuleCases>(`/rules/${encodeURIComponent(id)}/cases`)

export const isCaseAdvisory = (rule: Pick<RedlineRule,'id'|'execution_mode'>) => rule.execution_mode==='case_advisory'||rule.id.startsWith('CR-')
