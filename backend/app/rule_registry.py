"""Explicit runtime packs. Historical approvals are never modified."""
import json
from pathlib import Path
from hashlib import sha256
from copy import deepcopy

CONFIGURED_RULES_POLICY = 'review-configured-rules-v1'
BASE_IDS = tuple(f'RL-0{i}' for i in range(1, 6))
ROOT=Path(__file__).resolve().parents[2]


def resolve_rules(policy_version, *, liability_policy=None):
    source=json.loads((ROOT/'analysis/legal-corpus/draft-v0.1/rules.json').read_text())
    ids=BASE_IDS+(('CR-01','CR-02') if policy_version=='review-liability-v1' else ())
    by_id={r['id']:r for r in source['rules']}
    rules=[]
    for rid in ids:
        r=deepcopy(by_id[rid])
        r.update(execution_mode='case_advisory' if rid.startswith('CR-') else 'confirmed_rule',
                 policy_threshold=None,runtime_enabled=True,execution_version=policy_version)
        if rid=='RL-03' and policy_version == CONFIGURED_RULES_POLICY:
            r.update(require_bilateral_protection=False,
                     non_trigger_or_exceptions=[
                         '仅限制我方转让不构成客户可未经同意转让的证据，不新增补充限制待办',
                         '客户转让须经我方同意或已被禁止，且无相反例外时不命中',
                         '未约定客户转让不等同明确允许，不仅因条款缺失要求补证'],
                     insufficient_evidence_behavior='已识别客户转让条款，但角色、范围、同意主体或例外不明确时，针对该条款核验；不将仅限制我方或未写客户限制列为保护缺项。',
                     proposed_output='指出客户转让的明确许可及同意条件，或实际条款中影响判断的具体不确定内容。',
                     runtime_scope_basis='按合同中客户转让的明示许可及其同意条件核验。')
        rules.append(r)
    if policy_version == CONFIGURED_RULES_POLICY:
        from .liability_limit import rule_definition
        rules.append(rule_definition(liability_policy))
    return rules


def rule_snapshot(policy_version, *, liability_policy=None):
    rules=resolve_rules(policy_version, liability_policy=liability_policy)
    digest=sha256(json.dumps(rules,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return {'version':policy_version,'pack_sha256':digest,'rules':rules}


def matches_rule_snapshot(policy_version, snapshot):
    """Rebuild the rule text with the financial parameters frozen at enqueue."""
    if not isinstance(snapshot, dict):
        return False
    policy = None
    if policy_version == CONFIGURED_RULES_POLICY:
        limit = next((r for r in snapshot.get('rules', []) if r.get('id') == 'VL-01'), None)
        if not limit:
            return False
        policy = {'version':limit['version'], 'source':limit['authority'], 'supplier_bands':limit['supplier_bands']}
    return snapshot == rule_snapshot(policy_version, liability_policy=policy)
