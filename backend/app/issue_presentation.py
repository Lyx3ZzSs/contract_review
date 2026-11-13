"""Read-only presentation of saved facts, never a migration or a new review."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pydantic import ValidationError
from .field_review import FieldObservation, classify, classify_one
from .amount_review import AmountObservation, classify as classify_amount
from .models import IssuePresentation


def field_presentation(item):
    raw = item.get('field_checks')
    if not isinstance(raw, list) or not raw:
        return None
    fields = [FieldObservation.model_validate(f) for f in raw]
    # A historic rule may have differed. Preserve that verdict and explanation.
    if classify(fields)[0] != item.get('status'):
        return None
    observations = [dict(name=f.name, status=classify_one(f)[0],
                         evidence=[e.model_dump() for e in f.evidence],
                         requirement_evidence=[e.model_dump() for e in f.requirement_evidence]) for f in fields]
    actionable = [o for o in observations if o['status'] != 'no_flag_for_target_rule']
    if not actionable:
        title = '本轮未发现需要处理的字段缺项'
        summary = '已核对字段的填写状态与适用阶段，详细判断保留在依据中。'
        next_step = '可查看其他字段判断及对应原文。'
    else:
        one = actionable[0]
        title = (one['name'] + ('仍有空白或占位' if one['status'] == 'flag' else '的填写要求待确认')) if len(actionable) == 1 else f'{len(actionable)} 个字段需要核验'
        summary = '；'.join(f"{o['name']}：" + ('存在空白或占位，并有当前填写要求的原文依据' if o['status'] == 'flag' else '内容或本阶段填写要求尚不能确认') for o in actionable) + '。'
        next_step = '核对字段内容和本阶段填写要求，并记录核验依据；如有补充事实，可添加说明。'
    return dict(version='issue-presentation-v1', title=title, summary=summary,
                next_step=next_step, observations=observations)


def amount_presentation(item):
    raw, saved = item.get('amount_checks'), item.get('computed_calculations')
    if not isinstance(raw, list) or not raw or not isinstance(saved, list) or not saved:
        return None
    observations = [AmountObservation.model_validate(o) for o in raw]
    if any(o.basis != 'consistent' or o.issue != 'calculation' for o in observations):
        return None
    status, _, computed = classify_amount(observations)
    # Only show values actually saved by the original engine and matching its facts.
    if status != item.get('status') or len(computed) != len(saved):
        return None
    for actual, old in zip(computed, saved):
        if any(actual.get(k) != old.get(k) for k in ('operation','operands','stated_total','computed','difference')):
            return None
        if any(not Decimal(old[k]).is_finite() for k in ('stated_total','computed','difference')):
            return None
    changed = [c for c in saved if Decimal(c['difference']) != 0]
    if not changed:
        return None
    summary = '；'.join(f"复算值 {c['computed']}，列示值 {c['stated_total']}，差额 {c['difference']}" for c in changed) + '。容差与舍入口径尚需人工核实。'
    return dict(version='issue-presentation-v1', title='计算结果与列示值存在差额',
                summary=summary, next_step='定位计价依据，核对单位、税口径及舍入方式后记录结论。', observations=[])


def enrich_run_presentation(value):
    """Decorate copies; old, invalid or incompatible observations fall back intact."""
    result = deepcopy(value)
    for key in ('findings', 'issues', 'rule_results'):
        items = result.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                candidate = field_presentation(item) if item.get('rule_id') == 'RL-05' else amount_presentation(item) if item.get('rule_id') == 'RL-02' else None
                if candidate:
                    item['presentation'] = IssuePresentation.model_validate(candidate).model_dump()
            except (ValidationError, ValueError, TypeError, KeyError, InvalidOperation, AttributeError):
                # Display conveniences must never make a historical review unreadable.
                continue
    return result
