from app.llm import Settings
from app.rule_registry import resolve_rules
from app.revision_proposals import ProposalResults
from app.review_events import EventResults


def test_proposal_stage_does_not_inherit_spent_extraction_budget(monkeypatch):
    import app.event_review_pipeline as pipeline
    clock=[100.0]
    monkeypatch.setattr(pipeline.time,'monotonic',lambda:clock[0])
    text='乙方延误服务支付违约金，并赔偿损失。'
    def baseline(*args,**kwargs):
        return {'rule_results':[{'rule_id':f'RL-0{i}','status':'no_flag_for_target_rule','explanation':'已检查','evidence':[]} for i in range(1,6)]}
    def extraction(settings,model,prompt,schema,payload,validate,deadline,trace):
        if schema is EventResults:
            clock[0]=151.0 # Real round: 51 seconds before drafting starts.
            raw=EventResults(events=[{'ref':'b1','quote':text,'rule_id':'CR-02','mechanisms':['possible_cumulative_liability'],'title':'责任','explanation':'核对额外赔偿'}])
        else:
            assert deadline-clock[0]>=settings.timeout
            raw=ProposalResults(proposals=[])
        return raw,validate(raw)
    monkeypatch.setattr(pipeline,'review_accurate',baseline)
    monkeypatch.setattr(pipeline,'extract_call',extraction)
    pipeline.review_events_pipeline(Settings('http://test','unused',timeout=90),'deepseek-v4-flash',[{'id':'p1','text':text}],{'our_party':'乙方'},resolve_rules('review-events-v1'))


def test_drafting_batches_keep_each_event_whole_and_merge_all_edits(monkeypatch):
    import app.event_review_pipeline as pipeline
    blocks=[{'id':f'p{i}','text':f'第{i}项乙方延误服务支付违约金，并赔偿损失。'} for i in range(5)]
    seen=[]
    def baseline(*args,**kwargs):
        return {'rule_results':[{'rule_id':f'RL-0{i}','status':'no_flag_for_target_rule','explanation':'已检查','evidence':[]} for i in range(1,6)]}
    def extraction(settings,model,prompt,schema,payload,validate,deadline,trace):
        if schema is EventResults:
            raw=EventResults(events=[{'ref':f'b{i+1}','quote':b['text'],'rule_id':'CR-02','mechanisms':['possible_cumulative_liability'],'title':'责任','explanation':'核对额外赔偿'} for i,b in enumerate(blocks)])
        else:
            assert len(payload['events'])<=2
            seen.extend(e['event_id'] for e in payload['events'])
            raw=ProposalResults(proposals=[{'event_ids':[e['event_id']],'ref':e['ref'],'operation':'delete','before_text':'，并赔偿损失','after_text':'','rationale':'删除额外赔偿'} for e in payload['events']])
        return raw,validate(raw)
    monkeypatch.setattr(pipeline,'review_accurate',baseline)
    monkeypatch.setattr(pipeline,'extract_call',extraction)
    result=pipeline.review_events_pipeline(Settings('http://test','unused'),'deepseek-v4-flash',blocks,{'our_party':'乙方'},resolve_rules('review-events-v1'))
    assert len(seen)==len(set(seen))==5
    assert len(result['revision_proposals'])==5
    assert not result['module_errors']
