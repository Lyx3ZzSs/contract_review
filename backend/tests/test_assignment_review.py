import pytest
from app.assignment_review import AssignmentFacts, validate_assignment
from app.structured_review import Sources

def test_missing_is_uncertain():
    r=validate_assignment(AssignmentFacts(clauses=[]),Sources([]),{'our_party':'甲方'})
    assert r['status']=='insufficient_evidence' and r['evidence']==[]

def test_omission_rejected():
    with pytest.raises(Exception):
        validate_assignment(AssignmentFacts(clauses=[]),Sources([{'id':'x','text':'甲方可转让本合同。'}]),{'our_party':'乙方'})

def observation(quote='甲方可以转让本合同，无需乙方同意。',**changes):
    c=dict(transferor='甲方',consent_party='乙方',permission='allowed_without_consent',scope='contract',exceptions=[],refs=['b1'],quote=quote)
    c.update(changes)
    return AssignmentFacts(clauses=[c])

def test_role_swap():
    s=Sources([{'id':'x','text':'甲方可以转让本合同，无需乙方同意。'}])
    assert validate_assignment(observation(),s,{'our_party':'乙方'})['status']=='flag'
    assert validate_assignment(observation(),s,{'our_party':'甲方'})['status']=='insufficient_evidence'
    assert validate_assignment(observation(),s,{})['status']=='insufficient_evidence'

def test_fake_quote_and_permission():
    s=Sources([{'id':'x','text':'甲方不得转让本合同，须经乙方同意。'}])
    with pytest.raises(Exception): validate_assignment(observation(),s,{'our_party':'乙方'})
    with pytest.raises(Exception): validate_assignment(observation(quote=s.text(['b1'])),s,{'our_party':'乙方'})

def test_bilateral():
    q='任何一方转让本合同须经双方书面同意。'
    s=Sources([{'id':'x','text':q}])
    f=observation(q,transferor='双方',consent_party='双方',permission='consent_required')
    assert validate_assignment(f,s,{'our_party':'甲方'})['status']=='no_flag_for_target_rule'


@pytest.mark.parametrize('q,changes', [
 ('甲方转让本合同须经乙方同意。', {'transferor':'乙方','consent_party':'甲方','permission':'consent_required'}),
 ('甲方转让本合同无需乙方同意。', {'permission':'consent_required'}),
 ('甲方转委托服务无需乙方同意。', {'scope':'contract'}),
])
def test_false_structured_directions_rejected(q, changes):
    with pytest.raises(Exception):
        validate_assignment(observation(q,**changes),Sources([{'id':'x','text':q}]),{'our_party':'乙方'})


def test_customer_only_and_third_party_consent_remain_pending():
    q='甲方转让本合同须经乙方书面同意。'
    r=validate_assignment(observation(q,permission='consent_required'),Sources([{'id':'x','text':q}]),{'our_party':'乙方'})
    assert r['status']=='insufficient_evidence'
    assert r['review_reason']=='missing_bilateral_protection'
    q='甲方转让本合同须经主管部门书面同意。'
    f=observation(q,permission='consent_required',consent_party='不确定')
    assert validate_assignment(f,Sources([{'id':'x','text':q}]),{'our_party':'乙方'})['status']=='insufficient_evidence'


# Synthetic clauses; names retained for local regression imports.
REAL_53='5.3 乙方应组织测试服务团队，并按约定向甲方交付测试报告。未经甲方书面同意，不得将本合同项下权利义务转让或委托给任何第三方。'
REAL_76='7.6 乙方提供的测试服务不符合约定标准，包括未经甲方同意擅自转委托等情形，乙方应当按照第3.1.2条约定承担考核服务费。'


def test_long_assignment_and_subcontract_with_empty_quotes():
    sources=Sources([{'id':'a','text':REAL_53},{'id':'b','text':REAL_76}])
    clauses=[dict(transferor='乙方',consent_party='甲方',permission='consent_required',scope=scope,refs=[ref]) for scope,ref in [('contract','b1'),('subcontract','b2')]]
    assert validate_assignment({'clauses':clauses},sources,{'our_party':'乙方'})['status']=='insufficient_evidence'
    clauses[0]['transferor']='甲方'
    with pytest.raises(Exception):validate_assignment({'clauses':clauses},sources,{'our_party':'乙方'})


def test_assignment_payload_keeps_original_short_refs_and_material_candidates():
    from app.assignment_review import assignment_payload
    s=Sources([{'id':'a','text':'普通段落'},{'id':'m:1','text':REAL_53},{'id':'m:2','text':REAL_76}])
    payload=assignment_payload(s)
    assert payload['candidate_refs']==['b2','b3']
    assert [b['id'] for b in payload['blocks']]==['b2','b3']


@pytest.mark.parametrize('refs',[['5.3'],['b1','b2']])
def test_invalid_clause_number_or_ambiguous_quote_reconstruction_rejected(refs):
    sources=Sources([{'id':'a','text':REAL_53},{'id':'b','text':REAL_76}])
    with pytest.raises(Exception):
        validate_assignment({'clauses':[dict(transferor='乙方',consent_party='甲方',permission='consent_required',scope='contract',refs=refs)]},sources,{'our_party':'乙方'})

@pytest.mark.parametrize('suffix',['，但甲方可向关联方转让。','。甲方转让给关联方无需乙方同意。'])
def test_truncated_bilateral_quote_cannot_hide_exception(suffix):
    quote='双方转让本合同须经双方书面同意'
    s=Sources([{'id':'x','text':quote+suffix}])
    with pytest.raises(Exception):
        validate_assignment(observation(quote,transferor='双方',consent_party='双方',permission='consent_required'),s,{'our_party':'乙方'})


def test_short_quote_uses_full_paragraph_for_subject_context():
    s=Sources([{'id':'v:p1','text':REAL_76}])
    f={'clauses':[dict(transferor='乙方',consent_party='甲方',permission='consent_required',scope='subcontract',refs=['b1'],quote='未经甲方同意擅自转委托')]}
    assert validate_assignment(f,s,{'our_party':'乙方'})['status']=='insufficient_evidence'


QIRUI_TERMINATION='11.2乙方有下列情形之一的，甲方有权解除合同：'
QIRUI_ASSIGNMENT='11.2.6乙方未经甲方书面同意将其合同下的权利义务转让给第三方的。'


def test_live_qirui_assignment_condition_uses_parent_termination_evidence():
    s=Sources([{'id':'parent','text':QIRUI_TERMINATION},{'id':'child','text':QIRUI_ASSIGNMENT}])
    facts={'clauses':[dict(transferor='乙方',consent_party='甲方',permission='consent_required',scope='contract',refs=['b2'],quote='')]}
    result=validate_assignment(facts,s,{'our_party':'乙方'})
    assert result['status']=='insufficient_evidence'
    assert {e['block_id'] for e in result['evidence']}=={'parent','child'}
    from app.assignment_review import assignment_payload
    assert [b['id'] for b in assignment_payload(s)['blocks']]==['b1','b2']


@pytest.mark.parametrize('header,actor,consenter',[
    ('无关联标题','乙方','甲方'),
    ('11.3乙方有下列情形之一的，甲方有权解除合同：','乙方','甲方'),
    (QIRUI_TERMINATION,'甲方','乙方'),
])
def test_assignment_termination_inheritance_requires_correct_parent_and_direction(header,actor,consenter):
    s=Sources([{'id':'parent','text':header},{'id':'child','text':QIRUI_ASSIGNMENT}])
    facts={'clauses':[dict(transferor=actor,consent_party=consenter,permission='consent_required',scope='contract',refs=['b2'])]}
    with pytest.raises(Exception):validate_assignment(facts,s,{'our_party':'乙方'})


def test_live_weather_bilateral_counterparty_written_consent():
    q='12.1 在未取得对方书面同意前，任何一方都不得将本合同项下的权利及义务转让给任何第三方。'
    facts=observation(q,transferor='双方',consent_party='双方',permission='consent_required')
    assert validate_assignment(facts,Sources([{'id':'p','text':q}]),{'our_party':'乙方'})['status']=='no_flag_for_target_rule'
    with pytest.raises(Exception):
        validate_assignment(observation(q,transferor='甲方',consent_party='乙方',permission='consent_required'),Sources([{'id':'p','text':q}]),{'our_party':'乙方'})


def test_storage_capacity_transfer_and_funds_are_not_contract_assignment():
    from app.assignment_review import assignment_payload
    s=Sources([{'id':'p','text':'如有特殊情况，甲方应在规定时间内告知其充放电空间转让或出租需求以及事后处理需求。'}, {'id':'money','text':'乙方应按指定路径转移资金。'}])
    assert assignment_payload(s)['candidate_refs']==[]
    assert validate_assignment({'clauses':[]},s,{'our_party':'乙方'})['status']=='insufficient_evidence'


@pytest.mark.parametrize('our,actor,consenter',[('乙方','乙方','甲方'),('甲方','甲方','乙方')])
def test_explicit_permission_scope_does_not_turn_our_restriction_into_customer_issue(our,actor,consenter):
    q=f'{actor}转让本合同须经{consenter}书面同意。'
    f=observation(q,transferor=actor,consent_party=consenter,permission='consent_required')
    r=validate_assignment(f,Sources([{'id':'p','text':q}]),{'our_party':our},require_bilateral_protection=False)
    assert r['status']=='no_flag_for_target_rule'
    assert r['review_reason']=='no_customer_assignment_permission'


@pytest.mark.parametrize('q,permission,consenter,expected',[
    ('甲方可以转让本合同，无需乙方同意。','allowed_without_consent','乙方','flag'),
    ('甲方转让本合同须经乙方书面同意。','consent_required','乙方','no_flag_for_target_rule'),
    ('甲方转让本合同须经主管部门书面同意。','consent_required','不确定','insufficient_evidence'),
])
def test_explicit_customer_permission_and_ambiguity_remain_checked(q,permission,consenter,expected):
    f=observation(q,permission=permission,consent_party=consenter)
    r=validate_assignment(f,Sources([{'id':'p','text':q}]),{'our_party':'乙方'},require_bilateral_protection=False)
    assert r['status']==expected


def test_silence_is_not_a_customer_permission_but_legacy_scope_is_preserved():
    s=Sources([{'id':'p','text':'普通服务约定。'}])
    assert validate_assignment({'clauses':[]},s,{'our_party':'乙方'},require_bilateral_protection=False)['status']=='no_flag_for_target_rule'
    assert validate_assignment({'clauses':[]},s,{'our_party':'乙方'})['status']=='insufficient_evidence'


@pytest.mark.parametrize('q,changes',[
    ('甲方转让本合同须经乙方同意，但向关联方转让除外。',{'permission':'consent_required','exceptions':['但向关联方转让除外']}),
    ('甲方可以转让本合同。',{'transferor':'不确定','consent_party':'不确定','permission':'unclear'}),
    ('甲方可以转让本合同。',{'consent_party':'不确定','permission':'unclear','scope':'unclear'}),
])
def test_explicit_scope_does_not_suppress_observed_exceptions_or_uncertainty(q,changes):
    result=validate_assignment(observation(q,**changes),Sources([{'id':'p','text':q}]),{'our_party':'乙方'},require_bilateral_protection=False)
    assert result['status']=='insufficient_evidence'
    assert result['review_reason']=='customer_assignment_conditions_unclear'


@pytest.mark.parametrize('extra', ['', '但集团内部转让除外。'])
def test_local_transfer_reader_requires_complete_unqualified_condition(extra):
    from app.assignment_review import assignment_payload, termination_transfer_facts
    blocks = [{'id':'parent','text':QIRUI_TERMINATION}, {'id':'child','text':QIRUI_ASSIGNMENT + extra}]
    sources = Sources(blocks)
    refs = assignment_payload(sources)['candidate_refs']
    facts = termination_transfer_facts(sources, refs)
    if extra:
        assert facts is None
    else:
        assert facts.clauses[0].permission == 'consent_required'
        assert {e['block_id'] for e in validate_assignment(facts, sources, {'our_party':'乙方'})['evidence']} == {'parent','child'}
        mixed = Sources(blocks + [{'id':'second','text':'甲方可以转让本合同。'}])
        assert termination_transfer_facts(mixed, assignment_payload(mixed)['candidate_refs']) is None
        assert termination_transfer_facts(Sources(blocks[1:]), ['b1']) is None
