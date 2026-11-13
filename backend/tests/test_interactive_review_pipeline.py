import json
import pytest
from app.interactive_review import review_interactive, prompt_hash, schema_hash
from app.llm import Settings, ExtractionError
from test_structured_review import responses, facts, other


def test_material_prices_and_required_fields_reviewed_without_phantom_reference(monkeypatch):
    values = [facts(calculations=[{'operation':'product','operands':['2','50'],'stated_total':'110','refs':['b2']}], fields=[{'name':'税号','value_state':'blank','timing':'current_required','refs':['b3'],'requirement_refs':['b3']}]),
              {'checks':[{'name':'技术附件','state':'matched','content_refs':['b2','b3'],'basis_refs':['b1'],'explanation':'正文技术及单价要求对应附件条款。'}]}, other()]
    requests = responses(monkeypatch, values)
    bundle = {'id':'bundle', 'materials':[{'id':'material','filename':'技术附件.docx','parse_status':'parsed','blocks':[{'id':'material:p1','text':'服务接口为 HTTPS；两项服务各50元，合计110元。'}, {'id':'material:p2','text':'签署前应填写税号：____。'}]}], 'assertions':[{'statement':'已提供','actor':'用户'}]}
    result = review_interactive(Settings('http://test','secret'), 'm', [{'id':'main:p','text':'技术接口和服务单价见《技术附件》。'}], {}, [], bundle)
    rules = {r['rule_id']:r for r in result['rule_results']}
    assert len(rules) == 5
    assert rules['RL-02']['status'] == 'insufficient_evidence'
    assert rules['RL-02']['computed_calculations'][0]['computed'] == '100'
    assert rules['RL-05']['status'] == 'flag'
    assert rules['RL-05']['evidence'][0]['block_id'] == 'material:p2'
    assert len(result['attachment_checks']) == 1
    assert result['attachment_checks'][0]['status'] == 'no_flag_for_target_rule'
    payload = json.loads(requests[0]['messages'][1]['content'])
    assert len(payload['blocks']) == 3 and payload['blocks'][1]['origin'] == 'material'
    assert payload['attachment_reference_candidates'][0]['name'] == '技术附件'


def test_material_title_cannot_generate_main_document_reference(monkeypatch):
    responses(monkeypatch, [facts(), other()])
    result = review_interactive(Settings('http://test','s'), 'm', [{'id':'p','text':'合同总价100元。'}], {}, [], {'materials':[{'id':'m','parse_status':'parsed','filename':'报价附件.docx','blocks':[{'id':'m:p','text':'《报价附件》'}]}]})
    assert result['attachment_checks'] == []
    assert next(r for r in result['rule_results'] if r['rule_id']=='RL-04')['status'] == 'no_flag_for_target_rule'


def test_now_received_pricing_annex_resolves_old_missing_observation(monkeypatch):
    responses(monkeypatch, [facts(), {'checks':[{'name':'报价附件','state':'matched','content_refs':['b2'],'basis_refs':['b1'],'explanation':'单价与计价基数已提供。'}]}, other()])
    result = review_interactive(Settings('http://test','s'), 'm', [{'id':'p','text':'单价以《报价附件》为准，本次未提供。'}], {}, [], {'materials':[{'id':'m','parse_status':'parsed','filename':'报价附件.docx','blocks':[{'id':'m:p','text':'每件服务单价100元，含税，每月按实际交付件数结算。'}]}]})
    assert next(r for r in result['rule_results'] if r['rule_id']=='RL-02')['status'] == 'no_flag_for_target_rule'


def test_bundle_limit_is_not_truncated():
    with pytest.raises(ExtractionError) as error:
        review_interactive(Settings('http://test','s'), 'm', [{'id':'p','text':'合同'}], {}, [], {'materials':[{'id':'m','parse_status':'parsed','blocks':[{'id':'m:p','text':'a'*81000}]}]})
    assert error.value.code == 'input_too_large'
    assert len(prompt_hash()) == len(schema_hash()) == 64


def test_explicit_annex_number_title_is_one_reference():
    from app.interactive_review import reference_candidates
    from app.structured_review import Sources
    sources = Sources([{'id':'p','text':'技术标准详见附件一《技术协议》。'}, {'id':'q','text':'附件一 技术协议'}])
    seeds, aliases = reference_candidates(sources)
    assert aliases == {'附件一':'技术协议'}
    assert [s['name'] for s in seeds] == ['技术协议']
    assert seeds[0]['references'] == ['b1','b2']


def test_named_agreement_reference_is_indexed_without_annex_number():
    from app.interactive_review import reference_candidates
    from app.structured_review import Sources
    seeds, _ = reference_candidates(Sources([{'id':'p','text':'交付技术标准以《数据接口协议》V2版为准。'}]))
    assert [s['name'] for s in seeds] == ['数据接口协议']
    assert seeds[0]['references'] == ['b1']
    assert seeds[0]['technical_refs'] == ['b1']


def test_quoted_law_is_not_promoted_to_attachment():
    from app.interactive_review import reference_candidates
    from app.structured_review import Sources
    seeds, _ = reference_candidates(Sources([{'id':'p','text':'双方按照《中华人民共和国民法典》履行义务。'}]))
    assert seeds == []


def test_every_model_stage_uses_only_short_paragraph_refs_and_persistence_keeps_real_ids(monkeypatch):
    responses_to_send = [facts(), {'checks':[{'name':'接口协议','state':'matched','content_refs':['b3'],'basis_refs':['b1'],'explanation':'接口用途和V2版本均相符。'}]}, other()]
    requests = responses(monkeypatch, responses_to_send)
    main = [{'id':'document-uuid:p1','text':'技术要求以《接口协议》V2版为准。'}]
    bundle = {'materials':[{'id':'material-uuid','filename':'接口协议.docx','parse_status':'parsed','blocks':[
        {'id':'material-uuid:p1','text':'接口协议 V2版'}, {'id':'material-uuid:p2','text':'接口每10分钟传输JSON数据。'}]}],
        'links':[{'reference_name':'接口协议','target_material_version_id':'material-uuid','target_block_ids':['material-uuid:p2']}],
        'assertions':[{'statement':'已补充','actor':'业务'}]}
    result = review_interactive(Settings('http://test','s'), 'm', main, {}, [], bundle)
    for request in requests:
        payload = json.loads(request['messages'][1]['content'])
        serialized = json.dumps(payload, ensure_ascii=False)
        for real_id in ('document-uuid:p1','material-uuid:p1','material-uuid:p2'):
            assert real_id not in serialized
        assert payload['candidate_links'][0]['target_block_ids'] == ['b3']
    attachment_payload = json.loads(requests[1]['messages'][1]['content'])
    assert attachment_payload['attachment_references'][0]['reference_evidence'][0]['block_id'] == 'b1'
    assert attachment_payload['attachment_content_candidates'][0]['required_version_evidence'][0]['block_id'] == 'b1'
    other_payload = json.loads(requests[2]['messages'][1]['content'])
    assert {e['block_id'] for e in other_payload['attachment_checks'][0]['content_evidence']} == {'b2','b3'}
    assert {e['block_id'] for e in result['attachment_checks'][0]['evidence']} == {'document-uuid:p1','material-uuid:p1','material-uuid:p2'}


def test_real_paragraph_id_in_model_output_is_still_rejected(monkeypatch):
    bad = {'checks':[{'name':'技术附件','state':'unreadable','content_refs':[],
                     'basis_refs':['document-uuid:p1'],'explanation':'本次无法读取附件内容。'}]}
    requests = responses(monkeypatch, [facts(), bad, bad])
    with pytest.raises(ExtractionError) as error:
        review_interactive(Settings('http://test','s'), 'm', [{'id':'document-uuid:p1','text':'技术要求详见《技术附件》。'}], {}, [], {'materials':[]})
    assert error.value.code == 'invalid_structured_extraction'
    assert error.value.diagnostics[0]['reason'] == 'unknown_paragraph'
    assert len(requests) == 3
