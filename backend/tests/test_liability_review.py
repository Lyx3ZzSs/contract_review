import pytest
from app.liability_review import LiabilityFacts, validate_liability
from app.structured_review import Sources

def run(text, **kw):
    facts=LiabilityFacts.model_validate({'events':[dict(trigger='迟延', liable_party='乙方', quote=text, refs=['b1'], **kw)]})
    return validate_liability(facts,Sources([{'id':'p1','text':text}]),{'our_party':'乙方'})

def test_unlimited():
    assert run('乙方迟延每次扣款5000元，扣款次数不设上限。')[0]['review_reason']=='missing_aggregate_cap'

def test_compensation():
    assert run('乙方迟延支付违约金，并赔偿甲方全部损失。')[0]['rule_id']=='CR-02'

def test_exceptions():
    for text in ['乙方迟延支付违约金，赔偿损失时抵扣已付违约金。','乙方迟延扣款，累计责任不超过合同总额。','乙方迟延时仅未履约服务费不予支付。']:
        assert run(text)==[]

def test_grounding():
    facts=LiabilityFacts.model_validate({'events':[{'trigger':'迟延','liable_party':'乙方','quote':'虚构','refs':['b1']}]})
    with pytest.raises(Exception):
        validate_liability(facts,Sources([{'id':'p1','text':'正常履约'}]),{})

def test_distinct_events_and_linked_refs_not_added():
    assert run('乙方迟延支付违约金。甲方泄密赔偿损失。') == []
    sources=Sources([{'id':'p1','text':'乙方迟延支付违约金。'},{'id':'p2','text':'甲方泄密赔偿损失。'}])
    facts=LiabilityFacts(events=[dict(trigger='迟延',liable_party='乙方',quote='乙方迟延支付违约金。',refs=['b1'],related_refs=['b2']),dict(trigger='泄密',liable_party='甲方',refs=['b2'])])
    assert validate_liability(facts,sources,{'our_party':'乙方'})==[]

def test_cap_exception_and_roles():
    text='乙方迟延每次扣款5000元，累计责任不超过总价，但故意行为不受上限限制。'
    assert run(text)
    for party in ['甲方','乙方','不确定']:
        facts=LiabilityFacts(events=[dict(trigger='迟延',liable_party='甲方',quote=text.replace('乙方','甲方'),refs=['b1'])])
        result=validate_liability(facts,Sources([{'id':'p','text':text.replace('乙方','甲方')}]),{'our_party':party})
        assert result
        if party=='不确定':assert '角色需确认' in result[0]['explanation']

def test_revised_local_cap_and_unperformed_fee():
    assert run('乙方迟延单次扣款五千元，本项扣减金额上限为固定费用的10%。')==[]
    assert run('乙方迟延不予支付未提供服务期限的服务费，另支付违约金。')==[]

def test_original_mechanisms_fixed_fact_simulation():
    cases=[
      '乙方迟延单次扣款五千元，次数无上限。',
      '乙方迟延支付延误违约金，如另给甲方造成电力交易损失的，应当另外予以赔偿。',
      '乙方迟延解除合同，承担违约金，并赔偿甲方的全部损失。',
      '乙方迟延应退还全部合同所得并赔偿全部损失，并承担违约金。',
      '乙方迟延甲方有权不予支付当季及所有未付服务费，另支付违约金，且赔偿全部损失。',
    ]
    assert all(run(text) for text in cases)


# Verbatim calibration paragraphs read from the original DOCX.
ORIGINAL_PARAGRAPHS=['7.3合同有效期内，若目标电站月度交易电价连续两个月或任意三个月未达到约定的电价目标，则甲方有权单方书面通知乙方无条件终止或解除合同及相关补充协议且不承担解约赔偿。其中，甲方不承担服务期内固定代理交易服务费及激励分成费用，若甲方已支付费用，乙方应退回甲方已支付所有费用。', '7.4乙方未按合同要求按时开展电力交易相关服务工作的，自合同签订之日起，乙方以承保电价对应的收益为基数，以5‰日的利率水平计算应向甲方支付的延误违约金，如另给甲方造成电力交易损失的，应当另外予以赔偿，赔偿金额以所造成实际损失金额确定；乙方延迟开展服务工作超10日历日时，甲方有权单方无条件书面解除本协议，且乙方需按以上约定向甲方进行赔偿。乙方在合同期内无故提出终止或解除合同或根本违约的，乙方需承担合同价款（即本合同3.1.3条约定上限价）10%的违约金，并赔偿甲方的全部损失。', '7.5若乙方未按合同要求满足甲方需求、不配合甲方工作（包括合同第一点中服务内容款项、第五点乙方权利义务款项等），在经过甲方书面或邮件等形式通知后仍不整改，甲方有权针对该次不配合情况对乙方下达罚款单，单次五千元，体现在当季度固定代理交易服务费中结算扣减，次数无上限。', '7.6乙方提供的电力交易相关服务存在重大缺陷工作的，包括但不限于交易策略失误、通过与其他利益相关方联合恶意做低甲方电价、未经甲方同意擅自转委托等因乙方故意或过失给甲方造成损失的情形，乙方应当赔偿给甲方所造成的全部损失（其中关于电价损失的部分计算公式为：损失金额=当月结算电量×（承保电价-当月代理场站同市场口径结算电价），且甲方有权单方无条件书面解除本协议，乙方应退还全部合同所得（如有）并赔偿甲方全部损失，并承担合同总价款（即本合同3.1.3条约定上限价）10%的违约金。', '9.3乙方不得以任何理由（包括但不限于法律法规、国家政策（含省政府）等强制性规定）单方中止或解除本合同。如乙方未经甲方书面同意单方提出中止或解除本合同，或因乙方原因导致合同无法继续履行的，视为乙方根本违约，甲方有权不予支付当季及所有未付服务费，另乙方应立即向甲方支付本合同第3.1.3条约定的费用上限的20%作为违约金，且赔偿甲方因此遭受的全部损失（包括但不限于电价损失、替代交易成本、律师费、因重新委托第三方产生的额外费用等）。甲方有权依据本款约定书面通知乙方解除合同，解除自通知到达乙方之日起生效。']

def test_verbatim_original_five_targets():
    assert len(ORIGINAL_PARAGRAPHS)==5
    for text in ORIGINAL_PARAGRAPHS:
        facts=LiabilityFacts(events=[dict(trigger=text[:20],liable_party='乙方',quote=text,refs=['b1'],clause_ids=['invented'])])
        result=validate_liability(facts,Sources([{'id':'stable-id','text':text}]),{'our_party':'乙方'})
        assert result, text
        assert all('stable-id' in x['subject_key'] and 'invented' not in x['clause_ids'] for x in result)

def test_uncovered_and_noncontiguous_evidence_fail():
    with pytest.raises(Exception):
        validate_liability(LiabilityFacts(),Sources([{'id':'p','text':'扣款次数无上限'}]),{})
    facts=LiabilityFacts(events=[dict(trigger='扣款',quote='扣款\n无上限',refs=['b1','b2'])])
    with pytest.raises(Exception):
        validate_liability(facts,Sources([{'id':'p','text':'扣款'},{'id':'q','text':'无上限'}]),{})

def test_compact_payload_and_empty_quote():
    from app.liability_review import liability_candidate_payload
    sources=Sources([{'id':'p','text':'乙方迟延支付违约金，并赔偿全部损失。'}, {'id':'q','text':'固定服务费按月结算。'}, {'id':'r','text':'联系人张三'}])
    payload=liability_candidate_payload(sources)
    assert payload['candidate_refs']==['b1']
    assert [b['id'] for b in payload['blocks']]==['b1','b2']
    facts=LiabilityFacts(events=[dict(trigger='迟延',liable_party='乙方',refs=['b1'])])
    assert validate_liability(facts,sources,{'our_party':'乙方'})
    with pytest.raises(Exception):
        validate_liability(LiabilityFacts(),sources,{})

def test_explicit_continuation_and_unrelated_cap():
    assert run('乙方迟延须支付违约金。乙方还应赔偿全部损失。')
    assert run('乙方迟延每次违约扣款5000元。另一事件累计赔偿不超过10000元。')

def test_empty_trigger_and_unverified_relationship():
    sources=Sources([{'id':'p','text':'乙方违约支付违约金，并赔偿损失。'}, {'id':'q','text':'费用累计上限1000元。'}])
    facts=LiabilityFacts(events=[dict(refs=['b1'],related_refs=['b2'])])
    result=validate_liability(facts,sources,{})
    assert result and '适用关系尚未确认' in result[0]['explanation']

def test_verified_numbered_relationship_is_explained():
    sources=Sources([{'id':'p','text':'乙方违约按第2.8条考核，支付违约金，并赔偿损失。'}, {'id':'q','text':'2.8考核费用累计上限1000元。'}])
    facts=LiabilityFacts(events=[dict(refs=['b1'],related_refs=['b2'])])
    assert '关联费用或考核依据已引用' in validate_liability(facts,sources,{})[0]['explanation']


def test_explicit_qie_joins_penalty_and_damages():
    from app.structured_review import Sources
    s=Sources([{'id':'v:p1','text':'乙方应支付20%作为违约金，且赔偿甲方因此遭受的全部损失。'}])
    issues=validate_liability({'events':[{'refs':['b1'],'liable_party':'乙方'}]},s,{'our_party':'乙方'})
    assert any(i['review_reason']=='possible_cumulative_liability' for i in issues)


def test_liability_batches_cover_all_blocks_without_truncation():
    from app.liability_review import liability_batches
    payload={'context':{'our_party':'乙方'},'blocks':[{'id':f'b{i}','text':'赔偿'+('合同条款'*200)} for i in range(1,10)],'candidate_refs':[f'b{i}' for i in range(1,10)]}
    batches=liability_batches(payload,limit=3000)
    assert len(batches)>1
    assert [b for p in batches for b in p['blocks']]==payload['blocks']
    assert [r for p in batches for r in p['candidate_refs']]==payload['candidate_refs']


def test_liability_batch_refuses_oversized_single_paragraph():
    from app.liability_review import liability_batches
    from app.llm import ExtractionError
    with pytest.raises(ExtractionError,match='未截断'):
        liability_batches({'blocks':[{'id':'b1','text':'赔偿'*1000}],'candidate_refs':['b1']},limit=1000)
