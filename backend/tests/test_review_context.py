from app.review_context import normalize_review_context


def test_actual_ui_labels_and_neutral_are_not_unknown():
    assert normalize_review_context({'our_party':'乙方 · 服务提供方'})['our_party_code']=='party_b'
    assert normalize_review_context({'our_party':'甲方 · 采购方'})['our_party_code']=='party_a'
    assert normalize_review_context({'our_party':'中立审查'})['our_party_code']=='neutral'
    assert normalize_review_context({'our_party':'未知乙方部门'})['our_party_code']=='unknown'


def test_conflicting_labels_never_override_explicit_role():
    c=normalize_review_context({'our_party':'乙方 · 服务提供方','our_party_code':'party_a'})
    assert c['our_party_code']=='unknown' and c['role_conflict']


def test_retired_scope_fields_cannot_influence_review_context():
    payload = {'our_party': '乙方 · 服务提供方', 'stage': 'pre_sign',
               'contract_type': '功率预测服务', 'contract_type_declared': '功率预测服务',
               'business_scope': 'power_trading', 'business_scope_code': 'power_trading',
               'business_scope_state': 'conflict'}
    original = dict(payload)
    result = normalize_review_context(payload)
    assert result == normalize_review_context({'our_party': payload['our_party'], 'stage': 'pre_sign'})
    assert result['our_party_code'] == 'party_b'
    assert payload == original
