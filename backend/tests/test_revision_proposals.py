from app.revision_proposals import ProposalResults,validate_proposals,preview_proposal
from app.structured_review import Sources


def result(after='',operation='delete'):
    return ProposalResults(proposals=[{'event_ids':['e1'],'ref':'b1','operation':operation,'before_text':'，并赔偿全部损失','after_text':after,'rationale':'避免重复责任','basis_refs':[]}])


def test_delete_is_real_action_and_preserves_other_words():
    sources=Sources([{'id':'v:p1','text':'支付10%违约金，并赔偿全部损失。'}])
    p=validate_proposals(result(),sources,'v',[{'event_id':'e1','evidence':[{'block_id':'v:p1'}]}],[])[0]
    assert p['state']=='draft'
    assert preview_proposal(sources.blocks['b1']['text'],p)=='支付10%违约金。'


def test_new_threshold_and_missing_basis_are_not_asserted():
    sources=Sources([{'id':'v:p1','text':'支付10%违约金，并赔偿全部损失。'}])
    p=validate_proposals(result('，全部责任不超过80%', 'replace'),sources,'v',[{'event_id':'e1','evidence':[{'block_id':'v:p1'}]}],[])[0]
    assert p['state']=='context_required'


def test_unknown_event_and_overlapping_edits_are_rejected():
    sources=Sources([{'id':'v:p1','text':'支付10%违约金，并赔偿全部损失。'}])
    p=validate_proposals(result(),sources,'v',[],[])[0]
    assert p['state']=='invalid'
    raw=result();raw.proposals.append(raw.proposals[0].model_copy())
    p=validate_proposals(raw,sources,'v',[{'event_id':'e1','evidence':[{'block_id':'v:p1'}]}],[])
    assert len(p)==1


def test_cannot_edit_unrelated_sentence_of_same_paragraph():
    text='甲方应按时付款。乙方迟延服务应支付10%违约金，并赔偿全部损失。'
    sources=Sources([{'id':'v:p1','text':text}]);start=text.index('乙方')
    event={'event_id':'e1','event_anchor':{'block_id':'v:p1','start':start,'end':len(text),'quote':text[start:]},'evidence':[{'block_id':'v:p1'}]}
    raw=ProposalResults(proposals=[{'event_ids':['e1'],'ref':'b1','operation':'delete','before_text':'甲方应按时付款。','after_text':'','rationale':'修改'}])
    assert validate_proposals(raw,sources,'v',[event],[])[0]['state']=='invalid'


def test_existing_number_cannot_be_repurposed_as_global_policy():
    text='乙方迟延应支付10%违约金。';sources=Sources([{'id':'v:p1','text':text}])
    raw=ProposalResults(proposals=[{'event_ids':['e1'],'ref':'b1','operation':'replace','before_text':text,'after_text':'乙方全部责任累计以合同总额10%为限。','rationale':'修改'}])
    event={'event_id':'e1','evidence':[{'block_id':'v:p1'}]}
    assert validate_proposals(raw,sources,'v',[event],[])[0]['state']=='context_required'
    raw.proposals[0].after_text='乙方按第99.9条承担赔偿责任。'
    assert validate_proposals(raw,sources,'v',[event],[])[0]['state']=='invalid'


def test_wrong_reference_label_resolves_only_inside_known_event():
    text='支付10%违约金，并赔偿全部损失。';s=Sources([{'id':'p1','text':text}]);r=result();r.proposals[0].ref='1.1'
    event={'event_id':'e1','event_anchor':{'block_id':'p1','start':0,'end':len(text),'quote':text},'evidence':[{'block_id':'p1'}]}
    assert validate_proposals(r,s,'v',[event],[])[0]['state']=='draft'


def test_case_parameter_cannot_leak_across_version_event_or_wording():
    text='次数无上限';s=Sources([{'id':'p1','text':text}])
    event={'event_id':'e1','rule_id':'CR-01','event_anchor':{'block_id':'p1','start':0,'end':len(text),'quote':text},'evidence':[{'block_id':'p1'}]}
    approved='本项扣减金额上限为服务期内固定费用的10%'
    raw=ProposalResults(proposals=[{'event_ids':['e1'],'ref':'b1','operation':'replace','before_text':text,'after_text':approved,'rationale':'本案已确认','basis_refs':['g1']}])
    basis={'id':'g1','basis_kind':'case_specific_guidance','document_version_id':'v1','rule_id':'CR-01','scope_quote':text,'authorized_texts':[approved]}
    assert validate_proposals(raw,s,'v1',[event],[basis])[0]['state']=='draft'
    assert validate_proposals(raw,s,'v2',[event],[basis])[0]['state']=='context_required'
    assert validate_proposals(raw,s,'v1',[{**event,'rule_id':'CR-02'}],[basis])[0]['state']=='context_required'
    raw.proposals[0].after_text='全部责任上限为服务期内固定费用的10%'
    assert validate_proposals(raw,s,'v1',[event],[basis])[0]['state']=='context_required'


def test_one_revision_preserves_the_text_between_edits_and_confirmation_state():
    from app.revision_proposals import consolidate_configured_proposals
    source = '如违约，退还全部费用；保留解除权并支付20%违约金，另赔全部损失。'
    sources = Sources([dict(id='p1', text=source)])
    event = dict(event_id='exit', evidence=[dict(block_id='p1')])
    raw = ProposalResults(proposals=[
        dict(event_ids=['exit'],ref='b1',operation='delete',before_text='，另赔全部损失',after_text='',rationale='删除另赔义务。'),
        dict(event_ids=['exit'],ref='b1',operation='replace',before_text='退还全部费用',after_text='退还预收款',
             rationale='收窄退款范围。',requires_context=True,missing_context='确认退款范围。')])
    edits = validate_proposals(raw,sources,'v',[event],[])
    combined, pending = consolidate_configured_proposals(edits,{'p1':source})
    proposal, = combined
    assert not pending and proposal['state']=='context_required' and proposal['message']=='确认退款范围。'
    assert preview_proposal(source,proposal)=='如违约，退还预收款；保留解除权并支付20%违约金。'
    assert proposal['rationale']=='收窄退款范围。 删除另赔义务。'
    assert consolidate_configured_proposals(edits[::-1],{'p1':source})==(combined,pending)
    assert consolidate_configured_proposals(combined,{'p1':source})==(combined,pending)

def test_related_clause_can_be_cited_without_importing_its_financial_terms():
    from app.revision_proposals import validate_configured_drafts
    source = Sources([dict(id='p1', text='履行情况由双方协商。'), dict(id='p2', text='4.2 双方按协商程序处理，费用为90元。')])
    targets = {'e1':dict(evidence=[{'ref':'b1','quote':source.blocks['b1']['text']}],
                         related_evidence=[{'ref':'b2','quote':source.blocks['b2']['text']}],calculations=[])}
    event = dict(event_id='e1',evidence=[dict(block_id='p1')])
    raw = ProposalResults(proposals=[dict(event_ids=['e1'],ref='b1',operation='replace',before_text='由双方协商',
                                          after_text='依据第4.2条协商',rationale='引用约定的程序。')])
    assert validate_configured_drafts(raw,targets,source,'v',[event])
    raw.proposals[0].after_text += '并收取90元'
    assert not validate_configured_drafts(raw,targets,source,'v',[event])


def test_nested_item_citation_is_bound_to_its_own_parent_and_item():
    from app.clause_structure import block_citations, build_clauses
    from app.revision_proposals import configured_draft_targets, validate_configured_drafts
    sources = Sources([
        dict(id='fee',text='4.2 费用结算'),
        dict(id='item',text='（3）按月结算服务费。'),
        dict(id='termination',text='7.3 甲方可以解除合同。'),
        dict(id='risk',text='8.1 乙方另行承担全部损失。')])
    paths = block_citations(build_clauses('v',list(sources.blocks.values())))
    assert paths['item'] == '第4.2条第（3）项'
    issue = dict(event_id='e',rule_id='VL-01',execution_mode='liability_clause',execution_state='completed',
                 explanation='结算和赔偿可能重复。', evidence=sources.evidence(['b4','b2']))
    targets, _ = configured_draft_targets([issue],sources,paths)
    for citation, valid in [('第4.2条第（3）项',True),('第4.2条第（4）项',False),('第7.3条',False)]:
        raw = ProposalResults(proposals=[dict(event_ids=['e'],ref='b4',operation='replace',
            before_text='另行承担全部损失',after_text=f'赔偿扣除按{citation}结算款后的损失',rationale='核对重复承担部分。')])
        rejected = {}
        assert bool(validate_configured_drafts(raw,targets,sources,'v',[issue],rejections=rejected)) == valid
        if not valid:
            assert '交叉引用' in rejected['e'] and citation in rejected['e']


def test_payment_draft_preserves_named_fee_recipient_and_payment_sentence():
    from app.revision_proposals import validate_configured_drafts
    source = Sources([dict(id='p1',text='服务奖励按月结算。'),dict(id='p2',text='甲方的月度服务费计算方式为按月结算。')])
    targets = {'e':dict(evidence=[dict(ref='b1',quote=source.blocks['b1']['text'])],
                        related_evidence=[dict(ref='b2',quote=source.blocks['b2']['text'])],calculations=[])}
    for replacement, valid in [('不超过甲方已收取的月度服务费。',True),('不超过乙方已收取的月度服务费。',False),
                               ('乙方应向本合同第一条约定的费用上限作为违约金。',False)]:
        raw = ProposalResults(proposals=[dict(event_ids=['e'],ref='b1',operation='replace',before_text='按月结算',
                                              after_text=replacement,rationale='核对收付款义务。')])
        assert bool(validate_configured_drafts(raw,targets,source,'v',[dict(event_id='e',evidence=[dict(block_id='p1')])])) == valid


def test_attachment_article_requires_the_matching_scope_even_with_repeated_numbers():
    from app.clause_structure import block_citations, build_clauses
    from app.revision_proposals import configured_draft_targets, validate_configured_drafts
    blocks = [
        dict(id='body', text='10.1 交付迟延时按约支付违约金。'),
        dict(id='attachment', text='附件2：违约责任'),
        dict(id='loss', text='1. 乙方应补足实际损失。'),
        dict(id='target', text='3.1 按合同约定处理。'),
    ]
    sources = Sources(blocks)
    issue = dict(event_id='e', rule_id='VL-01', execution_mode='liability_clause',
                 execution_state='completed', explanation='需区分适用情形。', evidence=sources.evidence(['b4','b1','b3']))
    citations = block_citations(build_clauses('v', blocks))
    targets, _ = configured_draft_targets([issue], sources, citations)
    for after, expected in [
        ('迟延按第10.1条处理，实际损失依附件 2 第1条处理。', True),
        ('按附件2第10.1条赔偿。', False),
        ('按附件3第1条处理。', False),
        ('按附件2第1条另付2元。', False),
        ('按附件2第1条处理，累计上限为合同价的【待确认上限比例】。', False),
        ('按已核实损失另付3.1元。', False),
    ]:
        raw = ProposalResults(proposals=[dict(event_ids=['e'], ref='b4', operation='replace',
            before_text='按合同约定处理。', after_text=after, rationale='明确引用。')])
        assert bool(validate_configured_drafts(raw, targets, sources, 'v', [issue])) == expected


def test_week_conversion_is_local_and_unagreed_caps_need_a_placeholder():
    from app.revision_proposals import validate_configured_drafts
    original = '乙方按合同总价的0.1%/周支付违约金，不满一周的按一周计算。'
    sources = Sources([dict(id='p1', text=original)])
    event = dict(event_id='e', evidence=sources.evidence(['b1']))
    targets = {'e':dict(evidence=[dict(ref='b1', quote=original)], calculations=[])}
    for extra, expected in [
        ('一周的违约金金额除以七日乘以实际逾期天数，累计上限为合同总价的【待确认比例】。', 'context_required'),
        ('一周的违约金除以7日计算日违约金，另有7日宽限期。', None),
        ('累计上限为合同总价的10%。', None),
    ]:
        raw = ProposalResults(proposals=[dict(event_ids=['e'], ref='b1', operation='replace',
            before_text='不满一周的按一周计算。', after_text=extra, rationale='明确折算与上限。')])
        edits = validate_configured_drafts(raw, targets, sources, 'v', [event])
        assert (edits[0]['state'] if edits else None) == expected
