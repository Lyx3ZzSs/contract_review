import pytest
from app.case_guidance import text_digest, bind_guidance


def snapshot(blocks):
    return {'version':'case-guidance-test-v1','scope':'exact_document_only',
            'confirmation':{'answer':'先按各合同的个案意见处理，不推广到其他合同'},
            'entries':[{'id':'S04-E04','family_id':'S04','input_text_sha256':text_digest(blocks),
                        'role':'party_b','stage':'起草阶段','source_sha256':'a'*64,
                        'source_target':'E04','instruction':'本项扣减上限为服务期内固定费用10%',
                        'authorized_texts':['本项扣减金额上限为服务期内固定费用的10%']}]}


def test_guidance_requires_exact_document_role_and_stage():
    blocks=[{'id':'p1','text':'乙方按次扣款，次数无上限。'}]
    context={'our_party_code':'party_b','stage':'起草阶段'}
    bound=bind_guidance(snapshot(blocks),blocks,context,'v1')
    assert bound[0]['basis_kind']=='case_specific_guidance'
    assert bound[0]['document_version_id']=='v1'
    assert bind_guidance(snapshot(blocks),[{'id':'p1','text':'另一合同'}],context,'v2')==[]
    assert bind_guidance(snapshot(blocks),blocks,{**context,'our_party_code':'party_a'},'v1')==[]
    assert bind_guidance(snapshot(blocks),blocks,{**context,'stage':'履行阶段'},'v1')==[]


def test_no_implicit_or_global_guidance():
    blocks=[{'id':'p1','text':'合同'}]
    assert bind_guidance(None,blocks,{},'v1')==[]
    s=snapshot(blocks);s['scope']='company_policy'
    with pytest.raises(ValueError):bind_guidance(s,blocks,{},'v1')
