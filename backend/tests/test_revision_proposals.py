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
