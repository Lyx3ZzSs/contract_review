"""Deterministic checks on explicitly verified facts; no implicit LLM conclusions."""
from collections import defaultdict
from decimal import Decimal
from .models import Facts

RULES = ['RL-01', 'RL-02', 'RL-03', 'RL-04', 'RL-05']


def check(facts: Facts | None, stage: str):
    results = []
    def emit(rule, status, explanation, evidence=(), calculation=None):
        results.append({'rule_id': rule, 'status': status, 'explanation': explanation,
                        'evidence': [e.model_dump() for e in evidence], 'calculation': calculation,
                        'severity': None, 'scope': 'submitted_verified_facts', 'suggested_text': None})
    if facts is None:
        return [dict(rule_id=r, status='insufficient_evidence', explanation='尚未接入语义抽取，也未提交人工核实事实。',
                     evidence=[], calculation=None, severity=None, scope='not_evaluated', suggested_text=None) for r in RULES]
    groups = defaultdict(list)
    for t in facts.terms:
        groups[(t.subject, t.term_type, t.start_event)].append(t)
    for terms in groups.values():
        ev = [e for t in terms for e in t.evidence]
        if len(terms) < 2 or not all(t.comparison_confirmed for t in terms):
            emit('RL-01', 'insufficient_evidence', '缺少同对象、同期限类型、同起算条件的可比证据或优先关系确认。', ev)
        else:
            conflict = len({t.duration_months for t in terms}) > 1
            emit('RL-01', 'flag' if conflict else 'no_flag_for_target_rule', '可比期限不一致。' if conflict else '提交的可比期限一致。', ev)
    for a in facts.amounts:
        computed = sum(a.components, Decimal('0'))
        delta = a.stated - computed
        calc = {'components': [str(x) for x in a.components], 'computed': str(computed), 'stated': str(a.stated),
                'difference': str(delta), 'currency': a.currency, 'unit': a.unit, 'basis': a.basis}
        if not a.same_basis_confirmed or (delta and a.tolerance is None):
            emit('RL-02', 'insufficient_evidence', '已列出算式；计算范围或差异容差尚未确认，不能直接认定错误。', a.evidence, calc)
        else:
            mismatch = abs(delta) > (a.tolerance or Decimal('0'))
            emit('RL-02', 'flag' if mismatch else 'no_flag_for_target_rule', '金额超出已明确容差。' if mismatch else '提交金额在已明确口径内一致。', a.evidence, calc)
    for t in facts.transfers:
        if t.party not in ('customer', 'both') or t.consent == 'unspecified' or not t.exceptions_resolved:
            emit('RL-03', 'insufficient_evidence', '客户转让保护或例外尚未明确；不等同于明确允许无同意转让。', t.evidence)
        else:
            emit('RL-03', 'flag' if t.consent == 'not_required' else 'no_flag_for_target_rule',
                 '客户转让无需我方同意。' if t.consent == 'not_required' else '提交条款要求取得同意且例外已核对。', t.evidence)
    for a in facts.attachments:
        if a.state == 'provided':
            emit('RL-04', 'no_flag_for_target_rule', f'{a.name}已由核实人确认提供并匹配。', a.evidence)
        elif a.required_now is False:
            emit('RL-04', 'not_applicable', f'{a.name}已确认非当前阶段应提供。', a.evidence)
        elif a.state in ('unreadable', 'future') or not a.bundle_complete or a.required_now is None:
            emit('RL-04', 'insufficient_evidence', f'{a.name}的内容、资料清单或阶段要求待确认。', a.evidence)
        else:
            emit('RL-04', 'flag', f'本次完整资料包未见{a.name}的有效内容。', a.evidence)
    for f in facts.fields:
        if f.required_now is None or stage == 'unknown':
            emit('RL-05', 'insufficient_evidence', f'{f.name}的合同阶段或必填要求未明确。', f.evidence)
        elif not f.required_now:
            emit('RL-05', 'not_applicable', f'{f.name}不是当前阶段必填字段。', f.evidence)
        else:
            emit('RL-05', 'flag' if f.blank else 'no_flag_for_target_rule',
                 f'{f.name}当前应填写但为空。' if f.blank else f'{f.name}已填写。', f.evidence)
    for rule in RULES:
        if not any(r['rule_id'] == rule for r in results):
            emit(rule, 'insufficient_evidence', '未提供该规则的核实事实，未执行完整检查。')
    return results
