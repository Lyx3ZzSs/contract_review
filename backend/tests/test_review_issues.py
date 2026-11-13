import pytest
from app.review_issues import summarize_rule_status, build_review_issues


def test_summary_preserves_unresolved_and_flag():
    assert summarize_rule_status(['no_flag_for_target_rule', 'insufficient_evidence']) == 'insufficient_evidence'
    assert summarize_rule_status(['flag', 'insufficient_evidence']) == 'flag'
    with pytest.raises(ValueError):
        summarize_rule_status([])


def test_three_attachments_keep_independent_identity_and_status():
    findings = [dict(rule_id=f'RL-0{i}', status='no_flag_for_target_rule', explanation='已检查', evidence=[]) for i in range(1, 6)]
    checks = [dict(reference_name=name, subject_key=name, attachment_state=state, status=status, evidence=[], explanation=name) for name, state, status in [('A', 'matched', 'no_flag_for_target_rule'), ('B', 'missing', 'insufficient_evidence'), ('C', 'unreadable', 'insufficient_evidence')]]
    result = build_review_issues('run', findings, checks)
    attachments = [i for i in result['issues'] if i['rule_id'] == 'RL-04']
    assert len(attachments) == len({i['id'] for i in attachments}) == 3
    assert next(r for r in result['rule_results'] if r['rule_id'] == 'RL-04')['status'] == 'insufficient_evidence'


def test_no_references_has_no_attachment_issue():
    findings = [dict(rule_id=f'RL-0{i}', status='no_flag_for_target_rule', explanation='已检查', evidence=[]) for i in range(1, 6)]
    assert not any(i['rule_id'] == 'RL-04' for i in build_review_issues('r', findings, [])['issues'])
