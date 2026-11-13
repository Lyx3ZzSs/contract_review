"""Independent issue identities and deterministic rule aggregation."""
from copy import deepcopy
from hashlib import sha256

RESULT_SCHEMA_VERSION = 'interactive-review-v1'
STATUSES = {'flag', 'insufficient_evidence', 'no_flag_for_target_rule', 'not_applicable'}


def summarize_rule_status(statuses):
    if not statuses or any(s not in STATUSES for s in statuses):
        raise ValueError('Rule aggregation requires valid coverage results')
    for status in ('flag', 'insufficient_evidence', 'no_flag_for_target_rule', 'not_applicable'):
        if status in statuses:
            return status


def build_review_issues(run_id, findings, attachment_checks, *, expected_rule_ids=None, additional_issues=None):
    expected_rule_ids = expected_rule_ids or [f'RL-0{i}' for i in range(1, 6)]
    if sorted(f['rule_id'] for f in findings) != sorted(expected_rule_ids):
        raise ValueError('Exactly five rule coverage results required')
    rules = deepcopy(findings)
    issues = []
    for rule in rules:
        rid = rule['rule_id']
        if rid == 'RL-04':
            candidates = deepcopy(attachment_checks)
            if candidates:
                rule['status'] = summarize_rule_status([c['status'] for c in candidates])
                rule['explanation'] = '已逐项核验正文引用的附件；各项状态及依据见独立核验项。'
                rule['evidence'] = list({(e['block_id'], e['start'], e['end']): e for c in candidates for e in c['evidence']}.values())
            rule['attachment_checks'] = deepcopy(candidates)
            if additional_issues is not None and not candidates and rule['status'] in ('flag','insufficient_evidence'):
                candidates=[deepcopy(rule)]
        elif rid.startswith('CR-'):
            candidates = [deepcopy(i) for i in additional_issues or [] if i['rule_id'] == rid]
            if not candidates and rule.get('execution_state') == 'failed': candidates = [deepcopy(rule)]
        else:
            candidates = [deepcopy(rule)]
        for item in candidates:
            key = item.get('subject_key', rid)
            item.update(id='issue-' + sha256(f'{run_id}:{rid}:{key}'.encode()).hexdigest()[:24], run_id=run_id,
                        rule_id=rid, subject_key=key, kind='attachment' if rid == 'RL-04' else 'rule',
                        ai_status=item['status'], clause_ids=item.get('clause_ids', []), supersedes_issue_id=None)
            issues.append(item)
    return {'result_schema_version': 'interactive-review-v2' if additional_issues is not None else RESULT_SCHEMA_VERSION, 'rule_results': rules, 'issues': issues, 'findings': deepcopy(issues)}
