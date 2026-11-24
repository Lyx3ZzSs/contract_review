from datetime import date
import json
import pytest

from app import liability_limit as limit
from app.llm import ExtractionError


def num(ref, literal):
    return {"ref": ref, "literal": literal}


def money(ref, literal, rate=None):
    return {"money": num(ref, literal), "rate": rate}


paragraphs = {
    "b1": (
        "b1",
        "v",
        "p1",
        "",
        "乙方为服务方，服务期三年，年度服务费10万元，合同总价30万元，开具6%发票。",
    ),
    "b2": ("b2", "v", "p2", "", "乙方服务不达标时，退还8000元并支付5000元违约金。"),
    "m1p1": (
        "m1p1",
        "a",
        "a1",
        "补充协议",
        "乙方就一项或多项违约承担的全部责任累计不得超过合同总价的10%。",
    ),
}
confirmed = {
    "source": "运管记录A",
    "effective_from": "2026-11-01",
    "supplier_bands": limit.rule_definition()["supplier_bands"],
}


def facts():
    return dict(
        supplier="乙方",
        role_refs=["b1"],
        tax=num("b1", "6%"),
        annual_fee=num("b1", "10万元"),
        contract_total=num("b1", "30万元"),
        aggregate_cap=money("b1", "30万元", num("m1p1", "10%")),
        cap_refs=["m1p1"],
        scenarios=[
            dict(
                name="服务不达标",
                refs=["b2"],
                components=[money("b2", "8000元"), money("b2", "5000元")],
            )
        ],
        uncertainties=[],
    )


def run(data, confirmation=confirmed, role="乙方", partial=False, sources=paragraphs):
    return limit.evaluate(
        limit.LimitFacts(**data),
        sources,
        role,
        limit.rule_definition(),
        confirmation,
        partial,
    )


def test_cumulative_exposure_cross_material_cap_and_annual_basis():
    result = run(facts())
    assert result["status"] == "flag"
    assert (
        "内部限额 10000 元" in result["explanation"]
        and "超过限额 3000 元" in result["explanation"]
    )
    assert result["content_evidence"][0]["block_id"] == "a1"
    assert [e["block_id"] for e in result["evidence"]] == ["p2", "p1"]


def test_cumulative_cap_equal_to_internal_limit_passes():
    data = facts()
    data["aggregate_cap"] = money("b1", "10万元", num("m1p1", "10%"))
    sources = dict(paragraphs)
    sources["m1p1"] = (
        *paragraphs["m1p1"][:-1],
        paragraphs["m1p1"][-1].replace("合同总价", "年度服务费"),
    )
    assert run(data, sources=sources)["status"] == "no_flag_for_target_rule"


def test_configured_review_links_daily_charge_and_refund_to_distinct_clauses():
    data = facts()
    sources = dict(paragraphs, b3=('b3','main_document','p3',None,
                                  '1.1 乙方未按期完成技术服务的，每逾期1天，应向甲方支付相当于服务报酬0.5%的违约金。'),
                   b4=('b4','main_document','p4',None,
                       '1.4合同因乙方原因解除的，甲方有权要求乙方退还甲方已支付的全部款项，且乙方应支付相当于服务报酬5%的违约金。'))
    result = limit.evaluate(limit.LimitFacts(**data),sources,'乙方',limit.rule_definition(),None,clause_details=True)
    assert 'card_content' not in result
    data['clause_exposures'] = [
        dict(ref='b3',title='累计期间',status='flag',trigger_quote='每逾期1天',explanation='累计期间待核实。',direction='明确计费期间。'),
        dict(ref='b4',title='结算范围',status='insufficient_evidence',trigger_quote='退还甲方已支付的全部款项',explanation='结算范围待查。',direction='依履约记录核对。'),
    ]
    result = limit.evaluate(limit.LimitFacts(**data),sources,'乙方',limit.rule_definition(),None,clause_details=True)
    assert [(c['text'],c['direction'],c['evidence'][0]['block_id']) for c in result['card_content']['risk_paragraphs']] == [
        ('累计期间待核实。','明确计费期间。','p3'), ('结算范围待查。','依履约记录核对。','p4')]


def test_contract_total_band_and_specific_override():
    sources = dict(paragraphs)
    sources["b1"] = (*paragraphs["b1"][:-1], paragraphs["b1"][-1].replace("6%", "13%"))
    data = facts()
    data["tax"] = num("b1", "13%")
    assert "内部限额 90000 元" in run(data, sources=sources)["explanation"]
    override = dict(
        confirmed, supplier_bands={"13": {"basis": "contract_total", "percent": 4}}
    )
    assert run(data, confirmation=override, sources=sources)["status"] == "flag"


def test_review_status_without_policy_role_basis_or_coverage():
    assert run(facts(), confirmation=None)["status"] == "insufficient_evidence"
    assert run(facts(), role="甲方")["status"] == "not_applicable"
    assert run(facts(), partial=True)["status"] == "insufficient_evidence"
    assert run(dict(facts(), annual_fee=None))["status"] == "insufficient_evidence"
    assert (
        run(dict(facts(), uncertainties=["需核对另附责任减免条款"]))["status"]
        == "insufficient_evidence"
    )


def test_distinct_scenarios_do_not_stack():
    data = facts()
    data["scenarios"] = [
        {"name": "情形", "refs": ["b2"], "components": [component]}
        for component in data["scenarios"][0]["components"]
    ]
    assert run(data)["status"] == "insufficient_evidence"


def test_reject_amount_not_found_in_its_source():
    data = facts()
    data["annual_fee"] = num("b1", "0万元")
    with pytest.raises(ExtractionError):
        run(data)


def test_confirmations_match_contract_and_effective_dates(tmp_path, monkeypatch):
    path = tmp_path / "confirmations.json"
    path.write_text(
        json.dumps({"test-id": dict(confirmed, effective_until="2026-11-19")})
    )
    monkeypatch.setattr(limit, "CONFIRMATIONS_FILE", path)
    assert (
        limit.project_confirmation("test-id", date(2026, 11, 5))["source"]
        == "运管记录A"
    )
    for day in [date(2026, 10, 31), date(2026, 11, 20)]:
        assert limit.project_confirmation("test-id", day) is None
    assert limit.project_confirmation("another-id", date(2026, 11, 5)) is None


def test_worker_persists_frozen_project_override_and_calculation(tmp_path, monkeypatch):
    import io
    from docx import Document
    from fastapi.testclient import TestClient
    from app import configured_review as agent
    from app.main import create_app
    from app.llm import Settings
    from app.store import Store
    from app.worker import tick
    def base(settings, model, blocks, context, rules, **kwargs):
        records = [dict(rule_id=r['id'], status='no_flag_for_target_rule', explanation='未触发', evidence=[])
                   for r in rules]
        return dict(rule_results=records, issues=[], attachment_checks=[], module_errors=[], diagnostics={})
    monkeypatch.setattr(agent, "baseline_review", base)

    def extract(*args):
        schema, validate = args[3], args[5]
        if schema.__name__ == 'TransactionOverview':
            from app.llm import ExtractionError
            raise ExtractionError('gateway_timeout', '概况超时')
        if schema is limit.LimitFacts:
            raw = facts()
            raw["aggregate_cap"]["rate"]["ref"] = "b3"
            raw["cap_refs"] = ["b3"]
            value = schema(**raw)
            return value, validate(value)
        if schema is limit.ClauseFindings:
            value = schema(clause_exposures=[])
            return value, validate(value)
        if schema is agent.ConfiguredDraftResults:
            target, = args[4]['issues']
            anchor, = target['evidence'][:1]
            value = schema(proposals=[dict(event_ids=[target['event_id']], ref=anchor['ref'],
                                           before_text=anchor['quote'], after_text=anchor['quote']+'累计责任由双方核对。',
                                           operation='replace',
                                           rationale='限制累计扣款范围')], pending=[])
            return value, validate(value)
        pytest.fail(f'unexpected schema {schema.__name__}')

    monkeypatch.setattr(agent, "extract_call", extract)
    db = tmp_path / "run.db"
    client = TestClient(create_app(db))
    cid = client.post(
        "/api/v1/contracts",
        json={"title": "服务合同", "contract_type": "数据服务", "our_party": "乙方"},
    ).json()["id"]
    document = Document()
    for *_, text in paragraphs.values():
        document.add_paragraph(text)
    buf = io.BytesIO()
    document.save(buf)
    assert (
        client.post(
            f"/api/v1/contracts/{cid}/versions",
            files={"file": ("test.docx", buf.getvalue())},
        ).status_code
        == 201
    )
    path = tmp_path / "policy.json"
    path.write_text(json.dumps({cid: dict(confirmed, effective_from="2020-01-01")}))
    monkeypatch.setattr(limit, "CONFIRMATIONS_FILE", path)
    response = client.post(
        f"/api/v1/contracts/{cid}/reviews", json={"idempotency_key": "limit"}
    )
    assert response.status_code == 202
    path.unlink()
    assert tick(Store(db), Settings("test", "key"))
    run = client.get("/api/v1/runs/" + response.json()["id"]).json()
    assert not run["module_errors"]
    finding = next(item for item in run["issues"] if item["rule_id"] == "VL-01")
    assert finding["status"] == "flag"
    assert finding["numeric_grounding"]["internal_limit_yuan"] == "10000"
    assert finding["numeric_grounding"]["scenarios"][0]["exposure_yuan"] == "13000"
    assert finding["evidence"][0]["quote"] == paragraphs["b2"][-1]


def test_queued_rule_uses_frozen_bands_when_reference_changes(monkeypatch):
    from app.rule_registry import rule_snapshot, matches_rule_snapshot
    from app.rule_registry import CONFIGURED_RULES_POLICY

    old = rule_snapshot(CONFIGURED_RULES_POLICY)
    data = limit.policy_data()
    data["supplier_bands"]["6"]["percent"] = 9
    monkeypatch.setattr(limit, "policy_data", lambda: data)
    assert old != rule_snapshot(CONFIGURED_RULES_POLICY)
    assert matches_rule_snapshot(CONFIGURED_RULES_POLICY, old)
    old["rules"][-1]["supplier_bands"]["6"]["percent"] = 99
    assert not matches_rule_snapshot(CONFIGURED_RULES_POLICY, old)


def test_current_project_override_precedes_confirmed_supplier_default(tmp_path, monkeypatch):
    path = tmp_path / "confirmations.json"
    default = dict(confirmed, source="运管通用口径")
    project = dict(confirmed, source="项目特批", effective_until="2026-11-20")
    path.write_text(json.dumps({"*": default, "contract-a": project}))
    monkeypatch.setattr(limit, "CONFIRMATIONS_FILE", path)
    assert limit.project_confirmation("contract-a", date(2026, 11, 20))["source"] == "项目特批"
    assert limit.project_confirmation("contract-b", date(2026, 11, 20))["scope"] == "*"
    assert limit.project_confirmation("contract-a", date(2026, 11, 21))["source"] == "运管通用口径"


def test_uncertain_additional_loss_does_not_hide_proven_excess():
    sources = dict(paragraphs)
    sources["b2"] = (*sources["b2"][:-1], sources["b2"][-1] + "另赔偿甲方实际损失。")
    data = dict(facts(), additional_loss_refs=["b2"])
    assert run(data, sources=sources)["status"] == "flag"


def test_unpriced_exposure_keeps_related_evidence_outside_the_edit_target():
    from app.review_issues import build_review_issues
    from app.revision_proposals import configured_draft_targets
    from app.structured_review import Sources
    blocks = [
        {'id':'v:p1', 'text':'3.1 服务不达标时甲方扣减月度服务费。'},
        {'id':'v:p2', 'text':'7.3 乙方连续未达标时甲方可解除合同，乙方应退还全部已付费用。'},
    ]
    sources = Sources(blocks)
    rows = {ref:(ref,'main',b['id'],None,b['text']) for ref,b in sources.blocks.items()}
    data = limit.LimitFacts(supplier='乙方', role_refs=['b2'], scenarios=[], uncertainties=[],
        clause_exposures=[dict(ref='b2',title='已履行部分的结算',status='flag',trigger_quote='退还全部已付费用',
            explanation='退款可能覆盖已提供的服务，另有月度扣减。', direction='保留解除权并区分已履约款项。',
            related_refs=['b1'])])
    rule = limit.evaluate(data,rows,'乙方',limit.rule_definition(),None,clause_details=True)
    issues = build_review_issues('r',[rule],[],expected_rule_ids=['VL-01'],split_liability=True)['issues']
    issue, = issues
    assert [e['block_id'] for e in issue['evidence']] == ['v:p2','v:p1']
    targets, _ = configured_draft_targets(issues,sources)
    assert [e['ref'] for e in targets[issue['event_id']]['evidence']] == ['b2']
    assert [e['ref'] for e in targets[issue['event_id']]['related_evidence']] == ['b1']
    data.clause_exposures[0].trigger_quote = '并无此项原文'
    with pytest.raises(ExtractionError):
        limit.evaluate(data,rows,'乙方',limit.rule_definition(),None,clause_details=True)


def test_distinguish_bracketed_monthly_fee_chinese_penalty_and_daily_permille():
    from app.liability_numbers import number_catalog
    rows = dict(paragraphs)
    rows['b2'] = ('b2','v','p2','','月费【10000】元/月，单次扣五千元，另以五千元为基数按5‰计费。')
    catalog = list(number_catalog(rows.values()).values())
    assert [(ref,literal) for ref,literal in catalog if ref=='b2'] == [
        ('b2','【10000】元'),('b2','五千元'),('b2','5‰')]
    data = dict(facts(),scenarios=[dict(name='单日费用',refs=['b2'],
                components=[money('b2','五千元',num('b2','5‰'))])])
    assert run(data,sources=rows)['numeric_grounding']['scenarios'][0]['exposure_yuan']=='25'


def test_monthly_or_capped_price_cannot_be_substituted_for_annual_fee():
    for text, literal in [('代理费用为【10000】元/月。','【10000】元'),
                          ('正常履行时固定费与分成费用上限为人民币180000元。','180000元')]:
        row = dict(paragraphs,b3=('b3','v','p3','',text))
        rule = run(dict(facts(),annual_fee=num('b3',literal)),sources=row)
        assert rule['status']=='insufficient_evidence'
        assert 'internal_limit_yuan' not in rule['numeric_grounding']


def test_only_supplied_clause_findings_with_valid_related_refs_are_published():
    from app.liability_limit import ClauseExposure, grounded_clause_exposures
    texts = {
        'b1':'按月计算考核服务费=电价差×结算电量，每季度考核上限为五千元。',
        'b2':'4.1 乙方未达到约定电价，甲方可解除合同，乙方应退回甲方已支付的所有费用。',
        'b3':'4.2 乙方未按时履行，按电价收益每日5‰支付违约金，并赔偿甲方全部损失。',
        'b4':'4.3 乙方未按通知整改，单次罚款单扣五千元，次数无上限。',
    }
    rows = {r:(r,'main',r,None,t) for r,t in texts.items()}
    candidate = ClauseExposure(ref='b1',title='按月扣费',status='flag',trigger_quote='按月计算',
                               explanation='按月扣费',direction='核实',related_refs=[])
    f = limit.LimitFacts(supplier='乙方',role_refs=['b2'],scenarios=[
        dict(name=r,refs=[r],components=[]) for r in texts],uncertainties=[],clause_exposures=[candidate])
    assert grounded_clause_exposures(f,rows) == {'b1':[candidate]}
    f.clause_exposures.append(candidate.model_copy(update={'explanation':'第二个已定位的后果。'}))
    rule = limit.evaluate(f,rows,'乙方',limit.rule_definition(),None,clause_details=True)
    card, = rule['card_content']['risk_paragraphs']
    assert card['text'] == '按月扣费 第二个已定位的后果。'
    candidate.related_refs = ['missing']
    with pytest.raises(ExtractionError):
        grounded_clause_exposures(f,rows)


def test_perspective_review_requires_one_grounded_decision_per_candidate():
    candidate = limit.ClauseExposure(ref='b2',title='退款范围',trigger_quote='退还8000元',
                                    explanation='需核对退款范围',direction='明确退款边界',status='flag')
    candidates = limit.ClauseFindings(clause_exposures=[candidate])
    decision = dict(ref='b2',evidence_ref='b2',quote='乙方服务不达标时',liability_bearer='乙方',
                    proposed_change_effect='将退费限定于未履约部分。',proposed_change_beneficiary='乙方',
                    effect_on_our_party='承担责任',reason='乙方承担退款责任',verdict='keep')
    def check(*items):
        result = limit.PerspectiveCheck(decisions=list(items))
        return limit.verify_perspective(result,candidates,paragraphs,'乙方')
    fixed = candidate.model_copy(update={'direction':'明确退回未履约部分费用。'})
    assert check(dict(decision,verdict='revise',revision=fixed)) == [fixed]
    assert check(decision) == [candidate]
    for items in [[], [decision,decision], [dict(decision,ref='b3')], [dict(decision,quote='未出现的引文')],
                  [dict(decision,verdict='discard')], [dict(decision,verdict='revise')],
                  [dict(decision,proposed_change_beneficiary='甲方')]]:
        with pytest.raises(ExtractionError):
            check(*items)


def test_indexed_liability_numbers_require_the_original_paragraph_and_correct_unit():
    from app.liability_numbers import LimitReader, number_catalog

    catalog = number_catalog([('b7', None, None, None, '总额 10.00 万元，税率6％。'),
                              ('b8', None, None, None, '违约金为总额的6％。')])
    reader = LimitReader(catalog, lambda facts: facts)
    enums = reader.wire_schema.model_json_schema()['$defs']
    assert enums['MoneyID']['const'] == 'm1' and enums['PercentageID']['enum'] == ['p2','p3']
    raw = dict(supplier='乙方', role_refs=['b7'], tax='p2', contract_total='m1',
               scenarios=[dict(name='延迟交付', refs=['b8'], components=[dict(money='m1', rate='p3')])],
               uncertainties=[])
    facts, _ = reader.read(raw, None, [])
    assert facts.contract_total.model_dump() == {'ref':'b7', 'literal':'10.00 万元'}
    assert (facts.tax.ref, facts.scenarios[0].components[0].rate.ref) == ('b7', 'b8')
    for invalid in ('m1', 'p99'):
        with pytest.raises(ExtractionError):
            reader.read({**raw, 'tax':invalid}, None, [])
