from evaluation.run_edit_alignment import score_edit_alignment

SOURCES=[{'id':'p1','text':'延误赔偿甲方损失；解约赔偿甲方损失。'}]
GOLD=[{'kind':'edit','target_id':'E1','family_id':'S04','event':'延误','operation':'delete','before_text':'赔偿甲方损失','after_text':'','anchor':{'block_id':'p1','start':2,'end':8}}, {'kind':'edit','target_id':'E2','family_id':'S04','event':'解约','operation':'delete','before_text':'赔偿甲方损失','after_text':'','anchor':{'block_id':'p1','start':11,'end':17}}]
def proposal(g):
    return {**g,'id':g['target_id'],'matched_target_ids':[g['target_id']],'rationale':'不接受额外赔偿','event_review':'confirmed','reason_review':'confirmed','semantic_review':'confirmed','policy_basis_state':'supported'}
def test_swallowed_events_and_keyword_claim_cannot_pass():
    a=proposal(GOLD[0]); a['matched_target_ids']=['E1','E2']
    r=score_edit_alignment(GOLD,[a],SOURCES)
    assert r['edit_range_matches']==1
    assert r['state']!='complete'
def test_overbroad_delete_rejected():
    a=proposal(GOLD[0]);a['anchor']={'block_id':'p1','start':0,'end':18};a['before_text']=SOURCES[0]['text'][:18]
    assert score_edit_alignment(GOLD,[a],SOURCES)['edit_range_matches']==0
def test_same_family_retrieval_is_blocked():
    assert score_edit_alignment(GOLD,{'findings':[],'retrieved_cases':[{'family_id':'S04'}]},SOURCES)['state']=='blocked'
def test_missing_semantic_review_is_partial_even_with_exact_text():
    a=proposal(GOLD[0]);a.pop('semantic_review')
    assert score_edit_alignment(GOLD[:1],[a],SOURCES)['state']=='partial'
def test_complete_requires_verified_exact_range_and_human_review():
    assert score_edit_alignment(GOLD,[proposal(g) for g in GOLD],SOURCES)['state']=='complete'
def test_gold_or_comments_in_sources_is_blocked():
    assert score_edit_alignment(GOLD,[],{'blocks':SOURCES,'reviewer_comments':['answer']})['state']=='blocked'
