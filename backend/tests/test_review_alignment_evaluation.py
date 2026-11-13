from evaluation.run_review_alignment import score_targets


def test_clause_or_keywords_without_evidence_cannot_pass():
    case={'id':'x','blocks':[{'id':'p1','text':'7.4 违约金并赔偿额外损失'}]}
    labels=[{'target_id':'W02','clause_number':'7.4','original_mechanism_terms':['违约金','损失'],'approved_for_scoring':False}]
    assert not score_targets(case,labels,[{'clause_number':'7.4','mechanism':'违约金与损失叠加'}])[0]['candidate_match']
    issue={'clause_number':'7.4','mechanism':'违约金与损失叠加','evidence':[{'block_id':'p1','quote':'违约金并赔偿额外损失'}]}
    row=score_targets(case,labels,[issue])[0]
    assert row['candidate_match']
    assert row['human_semantic_review'] == 'pending'
    assert row['approved_accuracy_eligible'] is False


def test_fabricated_and_deleted_quotes_fail():
    case={'id':'x','view':'accepted_revisions','blocks':[{'id':'p1','text':'7.4 仅支付违约金'}]}
    label={'target_id':'W02','clause_number':'7.4','original_mechanism_terms':['违约金','损失'],'approved_for_scoring':False}
    assert not score_targets(case,[label],[{'clause_number':'7.4','mechanism':'违约金损失','evidence':[{'block_id':'p1','quote':'额外损失'}]}])[0]['candidate_match']


def test_reviewed_flags_deleted_quotes_without_requiring_zero_issues():
    from evaluation.run_review_alignment import score_reviewed
    original={'blocks':[{'id':'p1','text':'7.4 违约金并赔偿额外损失'}]}
    reviewed={'blocks':[{'id':'p1','text':'7.4 仅支付违约金'}]}
    labels=[{'target_id':'W02','clause_number':'7.4','reviewed_expectation':'删除额外损失'}]
    rows=score_reviewed(original,reviewed,labels,[{'evidence':[{'block_id':'p1','quote':'赔偿额外损失'}]}])
    assert rows[0]['deleted_quote_issue_indices'] == [0]
    assert score_reviewed(original,reviewed,labels,[{'evidence':[{'block_id':'p1','quote':'违约金'}]}])[0]['deleted_quote_issue_indices'] == []


def test_mechanism_alignment_requires_each_supported_component():
    case={'id':'x','blocks':[{'id':'p1','text':'9.3 甲方不予支付当季及所有未付服务费，乙方支付20%违约金且赔偿全部损失。'}]}
    label={'target_id':'x','clause_number':'9.3','mechanisms':[{'reason':'performed_fee_exposure','source_pattern':'不予支付','explanation_pattern':'已履约'},{'reason':'possible_cumulative_liability','source_pattern':'违约金.*损失','explanation_pattern':'违约金.*损失'}]}
    base={'evidence':[{'block_id':'p1','quote':case['blocks'][0]['text']}]}
    a=base|{'review_reason':'performed_fee_exposure','explanation':'已履约费用保护'}
    b=base|{'review_reason':'possible_cumulative_liability','explanation':'违约金与损失关系'}
    assert not score_targets(case,[label],[a])[0]['candidate_match']
    assert score_targets(case,[label],[a,b])[0]['candidate_match']
