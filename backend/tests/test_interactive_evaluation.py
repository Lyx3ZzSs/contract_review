from evaluation.run_interactive_review import assemble_input, grade, summarize


def label(approved=True, provenance='historical'):
    return {'case_id': 'x', 'provenance': provenance, 'approved_for_scoring': approved,
            'expected_checks': [{'rule_id': 'RL-04', 'statuses': ['no_flag_for_target_rule']}]}


def test_extra_false_positive_fails_entire_rule():
    result = {'findings': [{'rule_id': 'RL-04', 'status': s} for s in ['no_flag_for_target_rule', 'flag']]}
    assert not grade(result, label())[0]['passed']


def test_failed_call_remains_in_denominator():
    checks = grade(None, label())
    summary = summarize([{'status': 'failed', 'group': 'legal_confirmed', 'checks': checks}])
    assert summary['legal_confirmed']['checks'] == 1
    assert summary['legal_confirmed']['passed'] == 0
    assert summary['legal_confirmed']['failed_requests'] == 1


def test_unapproved_labels_never_enter_legal_accuracy():
    checks = grade({'findings': [{'rule_id': 'RL-04', 'status': 'no_flag_for_target_rule'}]}, label(False))
    assert checks[0]['scorable'] is False
    summary = summarize([{'status': 'validated', 'group': 'real_observation', 'checks': checks}])
    assert summary['real_observation']['checks'] == 0


def test_input_assembly_excludes_labels_and_metadata():
    case = {'case_id': 'x', 'blocks': [], 'context': {}, 'bundle': {'materials': []},
            'expected_checks': 'SECRET_EXPECTATION', 'provenance': 'not model data'}
    assert set(assemble_input(case, [])) == {'blocks', 'context', 'bundle', 'rules'}
    assert 'SECRET_EXPECTATION' not in str(assemble_input(case, []))


def test_empty_expectations_do_not_report_success():
    assert grade({'findings': []}, {'expected_checks': [], 'provenance': 'historical', 'approved_for_scoring': False}) == []


def test_extra_issue_false_positive_cannot_hide_behind_rule_summary():
    result = {'rule_results': [{'rule_id': 'RL-04', 'status': 'no_flag_for_target_rule'}],
              'issues': [{'rule_id': 'RL-04', 'ai_status': 'flag'}]}
    assert not grade(result, label())[0]['passed']


def test_missing_issue_schema_does_not_look_like_zero_issues():
    expected = label()
    expected['expected_checks'][0]['issue_count'] = 0
    result = {'findings': [{'rule_id': 'RL-04', 'status': 'no_flag_for_target_rule'}]}
    assert not grade(result, expected)[0]['passed']


def test_comparison_reports_regression_and_configuration_mismatch():
    from evaluation.compare_interactive_reports import compare_reports
    base = {'model': 'm', 'timeout_seconds': 90, 'gateway_sha256': 'g', 'rules_sha256': 'r', 'dataset_sha256': 'd',
            'expected_requests': 1, 'records': [{'case_id':'x', 'repeat':1, 'input_sha256':'i',
                'status':'validated', 'result':{'findings':[{'rule_id':'RL-04','status':'no_flag_for_target_rule'}]}}]}
    candidate = dict(base, model='other', records=[dict(base['records'][0], status='failed', result=None)])
    report = compare_reports(base, candidate, {'x':label(True)})
    assert not report['same_configuration']
    assert report['regressions'][0]['case_id'] == 'x'
    assert not report['enable_candidate']


def test_attachment_state_score_distinguishes_missing_and_unreadable():
    from evaluation.compare_interactive_reports import attachment_score
    expected = {'expected_attachment_states': ['unreadable']}
    assert not attachment_score({'attachment_checks': [{'match_state':'missing'}]}, expected)['passed']
    assert attachment_score({'attachment_checks': [{'match_state':'unreadable'}]}, expected)['passed']
    assert attachment_score({}, expected)['available'] is False


def test_scoring_requires_literal_approval_boolean():
    from evaluation.run_interactive_review import group_for
    assert group_for(label('false')) == 'real_observation'
    assert group_for(label(1)) == 'real_observation'
