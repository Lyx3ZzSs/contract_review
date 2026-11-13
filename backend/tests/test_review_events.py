import pytest
from app.review_events import event_identity,validate_events,EventResults
from app.structured_review import Sources


def test_same_paragraph_two_events_stay_distinct():
    sources=Sources([{'id':'v:p1','text':'乙方延误服务应支付违约金，并赔偿损失。乙方无故解除合同应支付违约金，并赔偿损失。'}])
    facts=EventResults(events=[{'ref':'b1','quote':q,'rule_id':'CR-02','mechanisms':['possible_cumulative_liability'],'title':'违约金与损失关系','explanation':'同一事件涉及违约金和赔偿。'} for q in ['乙方延误服务应支付违约金，并赔偿损失。','乙方无故解除合同应支付违约金，并赔偿损失。']])
    issues=validate_events(facts,sources,{'our_party':'乙方'})
    assert len(issues)==2 and len({i['event_id'] for i in issues})==2
    assert issues[0]['evidence'][0]['end']<issues[1]['evidence'][0]['end']
    assert len(validate_events(EventResults(events=facts.events+facts.events),sources,{'our_party':'乙方'}))==2


def test_ambiguous_quote_and_unsupported_mechanism_rejected():
    sources=Sources([{'id':'v:p1','text':'费用已支付。费用已支付。'}])
    with pytest.raises(Exception):
        validate_events(EventResults(events=[{'ref':'b1','quote':'费用已支付。','rule_id':'CR-02','mechanisms':['possible_cumulative_liability'],'title':'费用','explanation':'需核对'}]),sources,{})


def test_same_event_merges_mechanisms_without_losing_evidence():
    text='乙方迟延应退还全部费用，支付违约金并赔偿损失。'
    s=Sources([{'id':'v:p1','text':text}])
    raw=EventResults(events=[{'ref':'b1','quote':text,'rule_id':'CR-02','mechanisms':[m],'title':'责任','explanation':'需要核对'} for m in ['possible_cumulative_liability','performed_fee_exposure']])
    result=validate_events(raw,s,{'our_party':'乙方'})
    assert len(result)==1 and len(result[0]['mechanisms'])==2


def test_development_family_survives_prefix_edit(tmp_path,monkeypatch):
    import json
    import app.event_review_pipeline as pipeline
    monkeypatch.setattr(pipeline,'__file__',str(tmp_path/'backend/app/event_review_pipeline.py'))
    path=tmp_path/'analysis/legal-corpus/alignment-v1/S01/inputs.jsonl'
    path.parent.mkdir(parents=True)
    case={'family_id':'S01','blocks':[{'id':'p','text':'本工程样例约定乙方提供测试服务，每月提交测试报告，并按照双方确认的验收流程核验交付内容。'}]}
    path.write_text(json.dumps(case,ensure_ascii=False)+'\n')
    case['blocks'][0]['text']='注'+case['blocks'][0]['text']
    assert 'S01' in pipeline.known_family_ids(case['blocks'])


def test_existing_cap_is_not_missing_and_server_seeds_split_delay_termination():
    from app.review_events import indexed_events
    capped=Sources([{'id':'p','text':'任何一方违约责任累计不超过合同金额10%。'}])
    assert indexed_events(capped)==[]
    s=Sources([{'id':'p','text':'乙方延误服务支付违约金，并赔偿损失。乙方无故解约支付违约金，并赔偿全部损失。'}])
    assert len(indexed_events(s))==2


def test_contract_price_ceiling_is_not_another_events_liability_cap():
    s=Sources([{'id':'v:p1','text':'乙方延误支付违约金，并赔偿损失。乙方无故解约按合同上限价10%支付违约金，并赔偿损失。'}])
    raw=EventResults(events=[{'ref':'b1','quote':'乙方延误支付违约金，并赔偿损失。','rule_id':'CR-02','mechanisms':['possible_cumulative_liability'],'title':'延误责任','explanation':'需核对'}])
    assert len(validate_events(raw,s,{'our_party':'乙方'}))==1
