import pytest
from app.attachment_review import evaluate_attachment_references
from app.structured_review import Sources
from app.llm import ExtractionError


def check(state='matched', text='技术附件', parse_status='parsed', refs=None):
    sources = Sources([{'id':'main:p','text':'技术要求详见《技术附件》。'}, {'id':'mat:p','text':text}])
    bundle = {'materials':[{'id':'mat','filename':'技术附件.docx','parse_status':parse_status,'blocks':[{'id':'mat:p','text':text}]}], 'links':[{'reference_name':'技术附件','target_material_version_id':'mat','target_block_ids':['mat:p']}], 'assertions':[{'statement':'线下提供了','actor':'业务'}]}
    reference = {'name':'技术附件','reference_evidence':sources.evidence(['b1']), 'observation':{'state':state,'content_refs':refs or ['b2'],'basis_refs':['b1'],'explanation':'检查内容'}}
    return evaluate_attachment_references([reference], bundle, sources)[0]


def test_title_and_user_link_cannot_prove_match():
    assert check()['status'] == 'insufficient_evidence'
    assert check()['attachment_state'] == 'title_only'


def test_unreadable_content_never_passes():
    assert check(text='接口使用 HTTPS，返回 JSON 数据。', parse_status='partial')['attachment_state'] == 'unreadable'


def test_content_match_has_reconstructed_evidence():
    result = check(text='接口使用 HTTPS，返回 JSON 数据。')
    assert result['status'] == 'no_flag_for_target_rule'
    assert result['evidence'][-1]['block_id'] == 'mat:p'


def test_future_exemption_requires_temporal_document_basis():
    assert check(state='future_template')['status'] == 'insufficient_evidence'


def test_unknown_reference_rejected():
    with pytest.raises(ExtractionError):
        check(refs=['invented'])


@pytest.mark.parametrize('has_images, expected', [(False, 'matched'), (True, 'unreadable')])
def test_embedded_substance_and_unreadable_main_document_image_boundary(has_images, expected):
    sources = Sources([{'id':'main:p1','text':'技术要求详见《技术附件》。'},
                       {'id':'main:p2','text':'技术附件'},
                       {'id':'main:p3','text':'接口采用 HTTPS，数据每15分钟更新。'}])
    reference = {'name':'技术附件', 'reference_evidence':sources.evidence(['b1','b2']),
                 'observation':{'state':'matched','content_refs':['b3'],'basis_refs':['b1'],'explanation':'内嵌技术条款符合引用用途。'}}
    bundle = {'materials':[], 'document_parse_status':'partial' if has_images else 'parsed',
              'document_image_block_ids':['main:p4'] if has_images else []}
    result = evaluate_attachment_references([reference], bundle, sources)[0]
    assert result['attachment_state'] == expected
    if has_images:
        assert result['status'] == 'insufficient_evidence'
        assert '图片' in result['explanation']
    else:
        assert result['content_evidence'][0]['block_id'] == 'main:p3'


def test_main_document_image_does_not_invalidate_external_readable_content():
    sources = Sources([{'id':'main:p1','text':'技术要求详见《技术附件》。'},
                       {'id':'mat:p1','text':'接口采用 HTTPS，数据每15分钟更新。'}])
    reference = {'name':'技术附件', 'reference_evidence':sources.evidence(['b1']),
                 'observation':{'state':'matched','content_refs':['b2'],'basis_refs':['b1'],'explanation':'外部技术条款符合引用用途。'}}
    bundle = {'materials':[{'id':'mat','parse_status':'parsed','blocks':[{'id':'mat:p1','text':sources.blocks['b2']['text']}]}],
              'document_parse_status':'partial', 'document_image_block_ids':['main:p4']}
    assert evaluate_attachment_references([reference], bundle, sources)[0]['attachment_state'] == 'matched'


def test_embedded_candidates_have_bounded_content_not_next_attachment():
    from app.attachment_review import index_attachment_contents
    sources = Sources([{'id':'p1','text':'技术接口详见《接口协议》。'}, {'id':'p2','text':'附件甲 接口协议'},
                       {'id':'p3','text':'接口每10分钟传输JSON数据。'}, {'id':'p4','text':'附件乙 报价清单'},
                       {'id':'p5','text':'每项100元。'}])
    refs = [{'name':'接口协议','reference_evidence':sources.evidence(['b1'])}]
    result = index_attachment_contents(refs, {'materials':[]}, sources)
    assert result[0]['candidates'][0]['heading_refs'] == ['b2']
    assert result[0]['candidates'][0]['content_refs'] == ['b3']


def test_reference_sentence_is_not_embedded_attachment_heading():
    from app.attachment_review import index_attachment_contents
    sources = Sources([{'id':'p1','text':'技术要求详见《技术附件》。'}, {'id':'p2','text':'双方未经同意不得转让。'}])
    refs = [{'name':'技术附件','reference_evidence':sources.evidence(['b1'])}]
    assert index_attachment_contents(refs, {'materials':[]}, sources)[0]['candidates'] == []


@pytest.mark.parametrize('received, expected', [('V1','version_conflict'),('V2','matched')])
def test_explicit_document_version_is_checked_even_if_model_calls_match(received, expected):
    sources = Sources([{'id':'p1','text':'技术要求以《接口协议》V2版为准。'},
                       {'id':'m:p1','text':f'接口协议 {received}版'}, {'id':'m:p2','text':'接口每10分钟传输JSON数据。'}])
    refs = [{'name':'接口协议','reference_evidence':sources.evidence(['b1']),
             'observation':{'state':'matched','content_refs':['b3'],'basis_refs':['b1'],'explanation':'内容符合接口用途。'}}]
    bundle = {'materials':[{'id':'m','parse_status':'parsed','filename':'接口协议.docx','blocks':[sources.blocks['b2'],sources.blocks['b3']]}]}
    result = evaluate_attachment_references(refs, bundle, sources)[0]
    assert result['attachment_state'] == expected
    if expected == 'version_conflict':
        assert any(e['block_id']=='m:p1' and received in e['quote'] for e in result['evidence'])


def test_internal_material_id_is_never_contract_version_evidence():
    sources = Sources([{'id':'p1','text':'技术要求以《接口协议》V2版为准。'},
                       {'id':'m:p1','text':'接口协议 V2版'}, {'id':'m:p2','text':'接口每10分钟传输JSON数据。'}])
    refs = [{'name':'接口协议','reference_evidence':sources.evidence(['b1']),
             'observation':{'state':'matched','content_refs':['b3'],'basis_refs':['b1'],'explanation':'内容符合接口用途。'}}]
    bundle = {'materials':[{'id':'V1','parse_status':'parsed','filename':'V1.docx','blocks':[sources.blocks['b2'],sources.blocks['b3']]}]}
    assert evaluate_attachment_references(refs, bundle, sources)[0]['attachment_state'] == 'matched'


def test_long_embedded_attachment_evidence_is_not_rejected_or_truncated():
    from app.attachment_review import AttachmentResults
    blocks = [{'id':'p0','text':'技术要求详见《技术附件》。'}] + [
        {'id':f'p{i}','text':f'技术条款{i}：该接口支持加密传输与定期数据更新。'} for i in range(1, 61)]
    sources = Sources(blocks)
    observation = AttachmentResults.model_validate({'checks':[{'name':'技术附件','state':'matched',
        'content_refs':[f'b{i}' for i in range(2, 62)], 'basis_refs':['b1'], 'explanation':'内嵌技术条款支持引用用途。'}]}).checks[0]
    ref = {'name':'技术附件','reference_evidence':sources.evidence(['b1']), 'observation':observation.model_dump(exclude={'name'})}
    result = evaluate_attachment_references([ref], {'materials':[]}, sources)[0]
    assert len(result['content_evidence']) == 60
    assert result['content_evidence'][-1]['block_id'] == 'p60'


def test_other_attachment_version_in_same_paragraph_does_not_leak():
    sources = Sources([{'id':'p1','text':'技术以《接口协议》V2版为准，安全以《安全规范》V1版为准。'},
                       {'id':'m:p1','text':'接口协议 V2版'}, {'id':'m:p2','text':'接口每10分钟传输JSON数据。'}])
    refs = [{'name':'接口协议','reference_evidence':sources.evidence(['b1']),
             'observation':{'state':'matched','content_refs':['b3'],'basis_refs':['b1'],'explanation':'内容符合接口用途。'}}]
    bundle = {'materials':[{'id':'m','parse_status':'parsed','blocks':[sources.blocks['b2'],sources.blocks['b3']]}]}
    assert evaluate_attachment_references(refs, bundle, sources)[0]['attachment_state'] == 'matched'
