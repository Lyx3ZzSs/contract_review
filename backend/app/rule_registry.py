"""Explicit runtime packs. Historical approvals are never modified."""
import json
from pathlib import Path
from hashlib import sha256
from copy import deepcopy

BASE_IDS=tuple(f'RL-0{i}' for i in range(1,6))
ACCURATE_POLICIES=('review-grounded-v1','review-liability-v1','review-context-v1','review-events-v1','review-events-v2')
ROOT=Path(__file__).resolve().parents[2]


def resolve_rules(policy_version):
    source=json.loads((ROOT/'analysis/legal-corpus/draft-v0.1/rules.json').read_text())
    ids=BASE_IDS+(('CR-01','CR-02','CR-03','CR-04','CR-05') if policy_version=='review-events-v1' else ('CR-01','CR-02') if policy_version in ('review-liability-v1','review-context-v1','review-events-v2') else ())
    by_id={r['id']:r for r in source['rules']}
    rules=[]
    for rid in ids:
        r=deepcopy(by_id[rid])
        r.update(execution_mode='case_advisory' if rid.startswith('CR-') else 'confirmed_rule',
                 policy_threshold=None,runtime_enabled=True,execution_version=policy_version)
        if rid=='RL-03' and policy_version=='review-events-v2':
            # Current review boundary corrected from user feedback on 5.3.
            # Source drafts and legacy runtime packs remain available as history.
            r.update(require_bilateral_protection=False,
                     non_trigger_or_exceptions=[
                         '仅限制我方转让不构成客户可未经同意转让的证据，不新增补充限制待办',
                         '客户转让须经我方同意或已被禁止，且无相反例外时不命中',
                         '未约定客户转让不等同明确允许，不仅因条款缺失要求补证'],
                     insufficient_evidence_behavior='已识别客户转让条款，但角色、范围、同意主体或例外不明确时，针对该条款核验；不将仅限制我方或未写客户限制列为保护缺项。',
                     proposed_output='指出客户转让的明确许可及同意条件，或实际条款中影响判断的具体不确定内容。',
                     runtime_scope_basis='2026-11-12用户指出武威5.3不属于法务审查意见；按明确客户转让许可触发，不扩展缺失保护检查。')
        rules.append(r)
    return rules


def rule_snapshot(policy_version):
    rules=resolve_rules(policy_version)
    digest=sha256(json.dumps(rules,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    return {'version':policy_version,'pack_sha256':digest,'rules':rules}
