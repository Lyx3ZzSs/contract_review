import threading

import pytest

from app import liability_limit
from app.accurate_review import BasicFinding, verify_deadlines
from app.attachment_review import evaluate_attachment_references
from app.configured_review import draft_group, review_configured
from app.llm import ExtractionError, Settings
from app.reference_index import index_references
from app.review_issues import liability_issues
from app.revision_proposals import (
    ProposalResults, configured_draft_targets, validate_configured_drafts,
    verify_combined_draft_effects,
)
from app.rule_registry import CONFIGURED_RULES_POLICY, resolve_rules
from app.structured_review import PRICE, TECH, Sources, fail, grounded_role


def test_deadline_comparison_checks_same_matter_trigger_and_duration():
    blocks = Sources([
        {'id': 'p1', 'text': '自合同生效之日起部署期限20天。'},
        {'id': 'p2', 'text': '自合同生效之日起服务期限30天。'},
        {'id': 'p3', 'text': '自合同生效之日起部署期限30天。'},
        {'id': 'p4', 'text': '自合同生效之日起须在20天内完成部署。'},
        {'id': 'p5', 'text': '自合同生效之日起须在30天内完成部署。'},
    ])
    observations = [
        dict(ref='b1', subject_quote='部署期限', start_quote='自合同生效之日起', duration_quote='20天'),
        dict(ref='b2', subject_quote='服务期限', start_quote='自合同生效之日起', duration_quote='30天'),
    ]
    finding = BasicFinding(rule_id='RL-01', status='flag', explanation='期限需核对',
                           refs=['b1', 'b2', 'b3'], deadlines=observations)
    assert not verify_deadlines(finding, blocks)
    observations[1].update(ref='b3', subject_quote='部署期限')
    assert verify_deadlines(BasicFinding(rule_id='RL-01', status='flag', explanation='期限需核对',
                                         refs=['b1', 'b3'], deadlines=observations), blocks)
    observations[0].update(ref='b4', subject_quote='部署')
    observations[1].update(ref='b5', subject_quote='部署')
    assert not verify_deadlines(BasicFinding(rule_id='RL-01', status='flag', explanation='期限需核对',
                                             refs=['b4', 'b5'], deadlines=observations), blocks)


def test_mixed_rate_bases_and_unrelated_attachment_cannot_be_confirmed():
    sources = Sources([
        {'id': 'p1', 'text': '合同总价10000元，首付款为设备价的40%，尾款为服务价的50%。'},
        {'id': 'p2', 'text': '验收按《技术验收标准》执行。'},
        {'id': 'm:p1', 'text': '员工食堂营业时间及送餐范围详见通知。'},
    ])
    _, plans = index_references(sources, grounded_role, TECH, PRICE)
    assert plans == []
    reference = {'name': '技术验收标准', 'reference_evidence': sources.evidence(['b2']),
                 'observation': {'state': 'matched', 'content_refs': ['b3'], 'basis_refs': ['b2']}}
    bundle = {'materials': [{'id': 'm', 'filename': '食堂安排.docx', 'parse_status': 'parsed',
                             'blocks': [sources.blocks['b3']]}]}
    assert evaluate_attachment_references([reference], bundle, sources, require_identity=True)[0]['attachment_state'] == 'candidate'


def test_cumulative_amount_deduplicates_references_and_keeps_separate_issue():
    sources = {
        'b1': ('b1', '', 'p1', '', '乙方为供应方，年度服务费10万元，开具6%发票。'),
        'b2': ('b2', '', 'p2', '', '乙方逾期须支付8000元违约金；乙方另须退还服务费8000元。'),
    }
    amount = {'money': {'ref': 'b2', 'literal': '8000元'}}
    data = dict(supplier='乙方', role_refs=['b1'], uncertainties=[], tax={'ref': 'b1', 'literal': '6%'},
                annual_fee={'ref': 'b1', 'literal': '10万元'},
                clause_exposures=[dict(ref='b2', title='逾期责任', status='flag', trigger_quote='逾期须支付',
                                       explanation='触发违约金。', direction='明确迟延范围。')])
    rule = liability_limit.rule_definition()
    confirmation = {'source': '合成口径', 'effective_from': '2026-01-01', 'supplier_bands': rule['supplier_bands']}

    def compute(components):
        facts = liability_limit.LimitFacts(**data, scenarios=[dict(name='逾期', refs=['b2'], components=components)])
        return liability_limit.evaluate(facts, sources, '乙方', rule, confirmation, clause_details=True)

    repeated = compute([amount, amount])
    assert repeated['numeric_grounding']['scenarios'][0]['exposure_yuan'] == '8000'
    independent = compute([
        amount | {'obligation_ref': 'b2', 'obligation_quote': '支付8000元违约金'},
        amount | {'obligation_ref': 'b2', 'obligation_quote': '退还服务费8000元'},
    ])
    assert independent['numeric_grounding']['scenarios'][0]['exposure_yuan'] == '16000'
    assert [item['execution_mode'] for item in liability_issues(independent)] == ['liability_limit', 'liability_clause']
    different_quotes = compute([
        amount,
        amount | {'obligation_ref': 'b2', 'obligation_quote': '乙方逾期须支付8000元违约金'},
        amount | {'obligation_ref': 'b2', 'obligation_quote': '支付8000元违约金'},
    ])
    assert different_quotes['numeric_grounding']['scenarios'][0]['exposure_yuan'] == '8000'


def test_role_contradiction_and_direct_or_combined_reversal_are_rejected():
    original = '甲方逾期应向乙方支付违约金。'
    sources = Sources([{'id': 'p1', 'text': original}])
    exposures = liability_limit.ClauseFindings(clause_exposures=[
        dict(ref='b1', title='违约金', status='flag', trigger_quote='甲方逾期',
             explanation='已有付款义务。', direction='明确付款条件。'),
    ])
    vote = liability_limit.PerspectiveCheck(decisions=[
        dict(ref='b1', evidence_ref='b1', quote=original, liability_bearer='甲方',
             proposed_change_beneficiary='乙方', effect_on_our_party='承担责任', verdict='keep'),
    ])
    with pytest.raises(ExtractionError, match='结构化'):
        liability_limit.verify_perspective(vote, exposures, {'b1': ('b1', '', 'p1', '', original)}, '乙方')
    issue = dict(event_id='e1', rule_id='VL-01', status='flag', execution_mode='liability_clause',
                 execution_state='completed', explanation='付款责任核对。', evidence=sources.evidence(['b1']))
    targets, _ = configured_draft_targets([issue], sources)
    raw = ProposalResults(proposals=[dict(event_ids=['e1'], ref='b1', operation='replace',
        before_text=original, after_text='乙方逾期应向甲方支付违约金。', rationale='明确付款主体。')])
    assert validate_configured_drafts(raw, targets, sources, 'v', [issue]) == []
    drafts = [
        {'state': 'draft', 'anchor': {'block_id': 'p1', 'start': 0, 'end': 2}, 'after_text': '乙方'},
        {'state': 'draft', 'anchor': {'block_id': 'p1', 'start': 6, 'end': 8}, 'after_text': '甲方'},
    ]
    verify_combined_draft_effects(drafts, {'p1': original})
    assert [edit['state'] for edit in drafts] == ['invalid', 'invalid']


def test_same_paragraph_liability_findings_require_one_source_checked_draft():
    original = '乙方向甲方支付违约金，并赔偿全部损失。'
    sources = Sources([{'id': 'p1', 'text': original}])
    issues = [dict(event_id=eid, rule_id='VL-01', status='flag', execution_mode='liability_clause',
                   execution_state='completed', explanation=description, evidence=sources.evidence(['b1']))
              for eid, description in [('e1', '违约金可能重复计收'), ('e2', '赔偿范围过宽')]]
    targets, _ = configured_draft_targets(issues, sources)

    def invoke(after, event_ids):
        def model_call(settings, model, prompt, schema, payload, validate, deadline, trace):
            assert payload['coordinated_groups'] == [{'ref': 'b1', 'event_ids': ['e1', 'e2']}]
            value = schema(proposals=[dict(event_ids=event_ids, ref='b1', operation='replace',
                           before_text=original, after_text=after, rationale='明确责任范围')], pending=[])
            return value, validate(value)
        return draft_group(model_call, Settings('test', 'key'), 'mock', '乙方', '', targets, issues,
                           sources, 'v', 'draft', lambda *args, **kwargs: None)

    after = '乙方向甲方支付违约金，并赔偿超过违约金的直接损失。'
    edits, reasons, _ = invoke(after, ['e1', 'e2'])
    assert len(edits) == 1 and edits[0]['event_ids'] == ['e1', 'e2'] and not reasons
    for invalid, ids in [(after, ['e1']), (after.replace('直接', '12元'), ['e1', 'e2']),
                         ('甲方向乙方支付违约金，并赔偿超过违约金的直接损失。', ['e1', 'e2'])]:
        edits, reasons, trace = invoke(invalid, ids)
        assert not edits and reasons and trace[-1]['unresolved'] == ['e1', 'e2']

    def invoke_patches(patches, feedback=None):
        def model_call(settings, model, prompt, schema, payload, validate, deadline, trace):
            assert payload['draft_units'] == [{'unit':1, 'event_ids':['e1','e2'], 'refs':['b1']}]
            return validate.read({'proposals':[{'unit':1, 'ref':'b1', 'edits':patches,
                'rationale':'明确责任范围'}], 'pending':[]}, None, trace)
        return draft_group(model_call, Settings('test', 'key'), 'mock', '乙方', '', targets, issues,
                           sources, 'v', 'draft', lambda *args, **kwargs: None, feedback=feedback)

    edits,reasons,_ = invoke_patches([{'before':'全部损失','after':'超过违约金的直接损失'}])
    assert len(edits) == 1 and edits[0]['before_text'] == original and edits[0]['after_text'] == after
    assert not reasons
    repaired,reasons,_ = invoke_patches([{'before':'全部损失','after':'超过违约金的直接损失'}],
                                        {'e1':'仅修改目标片段','e2':'保留其他约定'})
    assert not reasons and repaired[0]['after_text'] == after
    for patches in [
        [{'before':'全部损失','after':'直接损失'}, {'before':'赔偿全部损失','after':'赔偿直接损失'}],
        [{'before':'全部损失','after':'赔偿12元'}],
        [{'before':'乙方向甲方','after':'甲方向乙方'}],
    ]:
        edits,reasons,_ = invoke_patches(patches)
        assert not edits and reasons.keys() == targets.keys()


def test_single_liability_draft_uses_grounded_patch():
    original = '乙方向甲方支付违约金，并赔偿全部损失。'
    sources = Sources([{'id': 'p1', 'text': original}])
    issue = dict(event_id='e1', rule_id='VL-01', status='flag', execution_mode='liability_clause',
                 execution_state='completed', explanation='赔偿范围过宽', evidence=sources.evidence(['b1']))
    targets, _ = configured_draft_targets([issue], sources)

    def model_call(settings, model, prompt, schema, payload, validate, deadline, trace):
        assert payload['draft_units'] == [{'unit': 1, 'event_ids': ['e1'], 'refs': ['b1']}]
        return validate.read({'proposals': [{'unit': 1, 'ref': 'b1', 'rationale': '限定赔偿范围',
            'edits': [{'before': '全部损失', 'after': '直接损失'}]}]}, None, trace)

    edits, reasons, _ = draft_group(model_call, Settings('test', 'key'), 'mock', '乙方', '', targets,
                                    [issue], sources, 'v', 'draft', lambda *args, **kwargs: None)
    assert not reasons
    assert [(edit['before_text'], edit['after_text']) for edit in edits] == [('全部损失', '直接损失')]


def test_perspective_repair_only_rechecks_unverified_candidates():
    a, b = '乙方逾期应向甲方支付违约金', '乙方另向甲方退还服务费'
    sources = Sources([{'id': 'p1', 'text': '乙方为供应方。' + a + '。' + b + '。'}])
    requests = []

    def model_call(settings, model, prompt, schema, payload, validate, deadline, trace):
        if schema is liability_limit.LimitFacts:
            value = schema(supplier='乙方', role_refs=['b1'], scenarios=[], uncertainties=[])
        elif schema is liability_limit.ClauseFindings:
            value = schema(clause_exposures=[dict(ref='b1', title=quote, status='flag',
                trigger_quote=quote, explanation='核对责任范围', direction='限定责任范围') for quote in (a, b)])
        else:
            quotes = [item['trigger_quote'] for item in payload['candidates']]
            requests.append(quotes)
            parts = payload['evidence'][0]['parts']
            assert ''.join(text for _, text in parts) == sources.blocks['b1']['text']
            assert [item['i'] for item in payload['candidates']] == list(range(1, len(quotes)+1))
            ids = {text.rstrip('。'):n for n,text in parts}
            value, result = validate.read({'decisions':[
                {'i':i, 's':9999 if quote == b and len(quotes) == 2 else ids[quote],
                 'b':'乙方','e':'承担责任','w':'乙方','v':'keep'} for i,quote in enumerate(quotes,1)
            ]}, None, trace)
            assert all(v.quote in sources.blocks['b1']['text'] for v in value.decisions)
            return value, result
        return value, validate(value)

    result = liability_limit.run_limit(model_call, Settings('test', 'key'), 'mock', sources, {},
        {'our_party': '乙方'}, liability_limit.rule_definition(), [], indexed_numbers=True, clause_details=True)
    assert requests == [[a, b], [b]]
    assert result['coverage'] == [{'block_id':'p1', 'state':'reviewed'}]
    assert {x['trigger_quote'] for x in result['card_content']['risk_paragraphs']} == {a, b}


def test_priority_schedule_keeps_every_target_and_chooses_a_grounded_payer():
    from app.liability_schedule import documented_supplier, responsibility_batches

    blocks = Sources([{'id': 'p1', 'text': '本合同为甲方委托乙方开展交易。'},
                      {'id': 'p2', 'text': '乙方提供本条所述各项服务。'}] +
                     [{'id': f'p{idx}', 'text': '乙方应向甲方支付违约金。' if idx == 7 else '支付及赔偿条件。' * idx}
                      for idx in range(3, 10)])
    rows = {ref:(ref, '', block['id'], '', block['text']) for ref, block in blocks.blocks.items()}
    assert documented_supplier(rows) == ('乙方',['b1','b2'])
    refs = [f'b{idx}' for idx in range(3,10)]
    batches = responsibility_batches(refs, rows, '乙方')
    assert batches[0] == ['b7']
    assert sorted(ref for batch in batches for ref in batch) == sorted(refs)
    rows['b10'] = ('b10','','p10','','甲方为供应方。')
    assert documented_supplier(rows) is None
    rows['b10'] = ('b10','','p10','','双方尚未确认甲方为供应方。')
    assert documented_supplier(rows) == ('乙方',['b1','b2'])
    assert documented_supplier({'b1':('b1','','p1','','若本合同为甲方委托乙方，另行约定。')}) is None


@pytest.mark.parametrize('amount_supplier',['乙方','甲方'])
def test_source_proven_supplier_publishes_verified_clause_before_amounts(amount_supplier):
    arrived = threading.Event()
    quote = '乙方逾期应向甲方支付违约金'
    sources = Sources([{'id': 'p1', 'text':'本合同为甲方委托乙方开展交易。'},
                       {'id': 'p2', 'text':'乙方提供本条所述各项服务。'},
                       {'id': 'p3', 'text':quote+'。'}])

    def on_group(record):
        assert record['card_content']['risk_paragraphs'][0]['trigger_quote'] == quote
        arrived.set()

    def model_call(settings, model, prompt, schema, payload, validate, deadline, trace):
        if schema is liability_limit.LimitFacts:
            assert arrived.wait(2)
            value = schema(supplier=amount_supplier, role_refs=['b1'], scenarios=[], uncertainties=[])
        elif schema is liability_limit.ClauseFindings:
            value = schema(clause_exposures=[dict(ref='b3', title='逾期责任', status='flag',
                trigger_quote=quote, explanation='核对责任范围', direction='限定责任范围')])
        else:
            value = schema(decisions=[dict(ref='b3', evidence_ref='b3', trigger_quote=quote,
                quote=quote, liability_bearer='乙方', proposed_change_beneficiary='乙方',
                effect_on_our_party='承担责任', verdict='keep')])
        return value, validate(value)

    result = liability_limit.run_limit(model_call, Settings('test', 'key'), 'mock', sources, {},
        {'our_party': '乙方'}, liability_limit.rule_definition(), [], indexed_numbers=True, clause_details=True,
        on_group=on_group)
    assert result['coverage'] == [{'block_id':'p3','state':'reviewed'}]
    if amount_supplier == '甲方':
        assert result['execution_state'] == 'failed'
        assert result['review_reason'] == 'liability_aggregate_invalid'


@pytest.mark.parametrize('failure,code', [
    ('group', 'liability_group_failed'),
    ('aggregate', 'liability_aggregate_invalid'),
])
def test_verified_attachment_obligation_survives_other_liability_failures(failure, code):
    first_published = threading.Event()
    first_group_started = threading.Event()
    blocks = [
        {'id': 'p1', 'text': '乙方为供应方，年度服务费10万元，开具6%发票。'},
        {'id': 'p2', 'text': '乙方逾期支付8000元违约金。' + '正文相关约定。' * 135},
    ]
    bundle = {'materials': [{'id': 'annex-v1', 'filename': '补充协议.docx', 'parse_status': 'parsed',
                             'blocks': [{'id': 'annex:p1', 'text': '乙方逾期应向甲方退还服务费。'}]}]}
    events = []

    def emit(event_type, **payload):
        events.append((event_type, payload))
        if event_type == 'issue_upserted' and payload['issue'].get('event_anchor', {}).get('block_id') == 'annex:p1':
            first_published.set()

    def model_call(settings, model, prompt, schema, payload, validate, deadline, trace):
        if schema is liability_limit.LimitFacts:
            assert first_group_started.wait(2)
            data = dict(supplier='乙方', role_refs=['b1'], scenarios=[], uncertainties=[], candidate_refs=[])
            if failure == 'aggregate':
                data.update(tax={'ref': 'b1', 'literal': '6%'}, annual_fee={'ref': 'b1', 'literal': '10万元'},
                            scenarios=[{'name': '逾期', 'refs': ['b2'], 'components': [{
                                'money': {'ref': 'b2', 'literal': '8000元'},
                                'obligation_ref': 'b2', 'obligation_quote': '乙方逾期支付',
                            }]}])
        elif schema is liability_limit.ClauseFindings:
            if payload['target_refs'] == ['b2']:
                first_group_started.set()
                assert first_published.wait(2)
                if failure == 'group':
                    raise fail('synthetic_group_failure')
                data = {'clause_exposures': [], 'excluded': [
                    {'ref': 'b2', 'quote': '乙方逾期支付8000元违约金', 'reason': '该约定有确定金额'}
                ]}
            else:
                assert payload['target_refs'] == ['m1p1']
                data = {'clause_exposures': [dict(ref='m1p1', title='退费范围', status='flag',
                          trigger_quote='退还服务费', explanation='可能涉及已履行服务费。', direction='核对退费范围。')],
                        'excluded': [{'ref':'m1p1', 'quote':'该句未出现在材料中', 'reason':'模型给出的其他排除依据'}]}
        elif schema is liability_limit.PerspectiveCheck:
            data = {'decisions': [dict(ref='m1p1', evidence_ref='m1p1', quote='乙方逾期应向甲方退还服务费',
                    liability_bearer='乙方', proposed_change_beneficiary='乙方',
                    effect_on_our_party='承担责任', verdict='keep')]}
        else:
            data = {
                'TransactionOverview': {'sections': []},
                'BasicResults': {'findings': [dict(rule_id=r, status='no_flag_for_target_rule', explanation='已检查', refs=[])
                                              for r in ['RL-01', 'RL-04']]},
                'GroundedFacts': {'attachments': [], 'calculations': [], 'missing_prices': [], 'fields': []},
                'AssignmentFacts': {'clauses': []},
            }[schema.__name__]
        value = schema.model_validate(data)
        return value, validate(value)

    result = review_configured(Settings('test', 'key'), 'mock', blocks, {'our_party': '乙方'},
                               resolve_rules(CONFIGURED_RULES_POLICY), bundle=bundle, document_version_id='v',
                               model_call=model_call, execution_callback=emit)
    liability_issues = [i for i in result['issues'] if i['rule_id'] == 'VL-01']
    assert len(liability_issues) == 2, result['module_errors']
    summary, issue = liability_issues
    assert summary['execution_state'] == 'failed'
    assert next(item['state'] for item in summary['coverage'] if item['block_id'] == 'annex:p1') == 'unresolved'
    assert issue['execution_state'] == 'completed'
    assert issue['evidence_sources'][0]['source_version_id'] == 'annex-v1'
    assert issue['revision_plan']['state'] == 'needs_confirmation'
    assert [item['code'] for item in result['module_errors']] == [code]


def test_indexed_liability_findings_bind_identical_penalties_to_their_own_table_rows():
    penalty = '不予退还投标保证金。'
    blocks = [dict(id='role', text='乙方为供应方。')]
    for row, condition in enumerate(('未中标时提供虚假业绩', '中标后拒绝签约'), 1):
        for cell, text in enumerate((condition, penalty), 1):
            blocks.append(dict(id=f'p{row}-{cell}', text=text,
                               table_location=dict(table=1,row=row,cell=cell)))
    attachment = dict(id='annex', filename='附件', parse_status='parsed', blocks=[
        dict(id='annex-1', text='其他文档内的条件', table_location=dict(table=1,row=1,cell=1))])
    visited = []

    def call(settings, model, prompt, schema, payload, validate, deadline, trace):
        if schema is liability_limit.LimitFacts:
            facts = schema(supplier='乙方', role_refs=['b1'], scenarios=[], uncertainties=[])
            return facts, validate(facts)
        if schema is liability_limit.ClauseFindings:
            refs = payload['target_refs']
            visited.append(tuple(refs))
            excluded = []
            for target in payload['targets']:
                ref = target['id']
                assert target['same_row_refs'] == [{'b3':'b2','b5':'b4'}[ref]]
                source, text = target['parts'][0]
                assert text == penalty
                assert all(cell['id'] in target['same_row_refs'] for cell in target['same_row'])
                excluded.append(dict(source=source, reason='已核对本行适用情形。'))
            return validate.read(dict(clause_exposures=[], excluded=excluded), None, trace)
        pytest.fail(schema.__name__)

    result = liability_limit.run_limit(call, Settings('test','key'), 'mock', Sources(blocks),
        {'materials':[attachment]}, {'our_party':'乙方'}, liability_limit.rule_definition(), [],
        indexed_numbers=True, clause_details=True)
    assert sorted(visited) == [('b3',), ('b5',)]
    assert [(c['block_id'], c['state'], c['quote']) for c in result['coverage']] == [
        ('p1-2','excluded',penalty), ('p2-2','excluded',penalty)]


def test_clause_finding_reader_rejects_an_unknown_part_or_a_non_target_cell():
    from app.llm import ExtractionError
    validate = liability_limit.FindingsReader({1:('b2','乙方应退还服务费。'), 2:('b1','终止服务。')}, ['b2'], {'b2':['b1']}, lambda v:v)
    finding = dict(source=1,title='退费范围',status='flag',explanation='退费未限定范围。',
                   direction='限定退费范围。')
    for invalid in [dict(source=2), dict(source=99), dict(related_sources=[999])]:
        with pytest.raises(ExtractionError):
            validate.read(dict(clause_exposures=[finding | invalid], excluded=[]), None, [])
    value, _ = validate.read(dict(clause_exposures=[finding], excluded=[]), None, [])
    item, = value.clause_exposures
    assert (item.ref,item.trigger_quote,item.related_refs) == ('b2','乙方应退还服务费。',['b1'])


def test_rejected_interpretation_is_reextracted_from_target_before_publication():
    text = '乙方违约时不予退还保证金。'
    blocks = [dict(id='p1',text='乙方为供应方。'), dict(id='p2',text=text)]
    requests = []

    def call(settings, model, prompt, schema, payload, validate, deadline, trace):
        if schema is liability_limit.LimitFacts:
            value = schema(supplier='乙方',role_refs=['b1'],scenarios=[],uncertainties=[])
            return value, validate(value)
        if schema is liability_limit.ClauseFindings:
            reconsidered = bool(payload.get('previously_unverified'))
            requests.append(reconsidered)
            part, = payload['targets'][0]['parts']
            return validate.read(dict(clause_exposures=[dict(source=part[0], status='flag',
                title='保证金未约定退还条件' if reconsidered else '另收百分之五罚金',
                explanation='核对违约后果。', direction='明确责任范围。')], excluded=[]), None, trace)
        candidate, = payload['candidates']
        part, = payload['evidence'][0]['parts']
        # A claimed penalty from a different row cannot be confirmed. Only a
        # fresh reading of the target yields an independently verifiable issue.
        vote = dict(i=1, s=part[0], b='乙方', e='承担责任', w='乙方',
                    v='keep' if '保证金' in candidate['title'] else 'discard')
        return validate.read(dict(decisions=[vote]), None, trace)

    record = liability_limit.run_limit(call, Settings('test','key'), 'mock', Sources(blocks),
        {}, {'our_party':'乙方'}, liability_limit.rule_definition(), [], indexed_numbers=True, clause_details=True)
    assert requests == [False, True]
    assert record['coverage'] == [dict(block_id='p2',state='reviewed')]
    card, = record['card_content']['risk_paragraphs']
    assert card['title'] == '保证金未约定退还条件' and card['trigger_quote'] == text
