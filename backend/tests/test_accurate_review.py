import json
import pytest
from app.accurate_review import review_accurate
from app.rule_registry import resolve_rules
from app.llm import Settings,ExtractionError
from app import accurate_review as ar


def test_rules_extend_only_for_explicit_candidate():
    assert [r['id'] for r in resolve_rules('redlines-v7')]==['RL-01','RL-02','RL-03','RL-04','RL-05']
    rules=resolve_rules('review-liability-v1')
    assert len(rules)==7 and all(r['execution_mode']=='case_advisory' for r in rules[-2:])
    assert all(r.get('policy_threshold') is None for r in rules[-2:])


def test_module_failure_preserves_other_results_and_cannot_pass(monkeypatch):
    def fake(settings,model,prompt,schema,payload,validate,deadline,trace):
        if schema.__name__=='GroundedFacts':raise ExtractionError('invalid_structured_extraction','校验失败')
        raw=({'clauses':[]} if schema.__name__=='AssignmentFacts' else {'events':[]} if schema.__name__=='LiabilityFacts' else {'findings':[{'rule_id':r,'status':'no_flag_for_target_rule','explanation':'未触发','refs':[]} for r in ['RL-01','RL-04']]})
        value=schema.model_validate(raw)
        return value,validate(value)
    monkeypatch.setattr(ar,'extract_call',fake)
    result=review_accurate(Settings('http://test','x'),'deepseek-v4-flash',[{'id':'v:p1','text':'合同编号：'}],{'our_party':'乙方'},resolve_rules('review-liability-v1'))
    assert result['module_errors']
    assert next(r for r in result['rule_results'] if r['rule_id']=='RL-02')['execution_state']=='failed'
    assert next(r for r in result['rule_results'] if r['rule_id']=='RL-03')['execution_state']=='completed'
    assert len(result['rule_results'])==7


def test_issue_builder_supports_multiple_events():
    from app.review_issues import build_review_issues
    rules=[dict(rule_id=r['id'],status='no_flag_for_target_rule',explanation='未触发',evidence=[]) for r in resolve_rules('review-liability-v1')]
    issues=[dict(rule_id='CR-02',subject_key=k,status='insufficient_evidence',explanation='需复核',evidence=[]) for k in ['v:p1:event1','v:p2:event2']]
    result=build_review_issues('run',rules,[],expected_rule_ids=[r['rule_id'] for r in rules],additional_issues=issues)
    assert len([x for x in result['issues'] if x['rule_id']=='CR-02'])==2
    assert len({x['id'] for x in result['issues']})==len(result['issues'])


def test_success_without_liability_has_explicit_coverage(monkeypatch):
    def fake(settings,model,prompt,schema,payload,validate,deadline,trace):
        raw=({'attachments':[],'calculations':[],'missing_prices':[],'fields':[]} if schema.__name__=='GroundedFacts' else {'clauses':[]} if schema.__name__=='AssignmentFacts' else {'events':[]} if schema.__name__=='LiabilityFacts' else {'findings':[{'rule_id':r,'status':'no_flag_for_target_rule','explanation':'未触发','refs':[]} for r in ['RL-01','RL-04']]})
        value=schema.model_validate(raw);return value,validate(value)
    monkeypatch.setattr(ar,'extract_call',fake)
    result=review_accurate(Settings('http://test','x'),'deepseek-v4-flash',[{'id':'v:p1','text':'总价100元。'}],{'our_party':'乙方'},resolve_rules('review-liability-v1'))
    assert not result['module_errors']
    assert len(result['rule_results'])==7
    assert all(r['execution_state']=='completed' for r in result['rule_results'])
    assert not [i for i in result['issues'] if i['rule_id'].startswith('CR-')]


def test_attachment_rule_failure_remains_actionable_without_checks():
    from app.review_issues import build_review_issues
    findings=[dict(rule_id=r['id'],status='insufficient_evidence' if r['id']=='RL-04' else 'no_flag_for_target_rule',explanation='待核验',evidence=[],execution_state='failed' if r['id']=='RL-04' else 'completed') for r in resolve_rules('review-grounded-v1')]
    result=build_review_issues('r',findings,[],additional_issues=[])
    assert any(i['rule_id']=='RL-04' for i in result['issues'])


def test_configured_rules_group_missing_pricing_attachment_and_ignore_unproven_form_fields():
    from app.rule_registry import CONFIGURED_RULES_POLICY
    blocks = [{'id':'p1','text':'合同计费以《价格清单》为准，本次未提供《价格清单》。'},
              {'id':'p2','text':'10、数据精度指标：（待评估）'}, {'id':'p3','text':'支付给乙方订单金额的剩余50%'}]

    def fake(settings,model,prompt,schema,payload,validate,deadline,trace):
        responses = {
            'GroundedFacts': {'attachments':[{'name':'价格清单','references':['b1'],'technical_refs':[],'pricing_refs':['b1']}],
                              'calculations':[{'operation':'sum','operands':['50','50'],'stated_total':'100','refs':['b3'],
                                               'operand_tokens':['50%','50%'],'total_token':'','relation_quote':blocks[2]['text'],
                                               'relation_kind':'instalment_percentages'}],
                              'missing_prices':[{'kind':'pricing_attachment','refs':['b1'],'attachment_name':'价格清单'}],
                              'fields':[{'name':'数据精度指标','value_state':'placeholder','timing':'current_required',
                                         'refs':['b2'],'requirement_refs':['b2']}]},
            'AssignmentFacts': {'clauses':[]},
            'BasicResults': {'findings':[{'rule_id':rid,'status':'no_flag_for_target_rule','explanation':'核查完成','refs':[]}
                                         for rid in ('RL-01','RL-04')]},
            'AttachmentResults': {'checks':[{'name':'价格清单','state':'candidate','explanation':'需补齐《价格清单》。','basis_refs':['b1'],'content_refs':[]}]},
        }
        value = schema.model_validate(responses[schema.__name__])
        return value, validate(value)

    rules = [r for r in resolve_rules(CONFIGURED_RULES_POLICY) if r['id']!='VL-01']
    events=[]
    result = review_accurate(Settings('http://test','x'),'m',blocks,{'our_party':'乙方'},rules,
                             policy_version=CONFIGURED_RULES_POLICY,bundle={'id':'materials','materials':[]},model_call=fake,
                             execution_callback=lambda kind,**data:events.append((kind,data)))
    pending = [i for i in result['issues'] if i['status'] in ('flag','insufficient_evidence')]
    assert not result['module_errors']
    assert len(pending)==1 and pending[0]['rule_id']=='RL-04'
    assert '计价依据' in pending[0]['explanation']
    facts_at=next(i for i,(kind,data) in enumerate(events) if kind=='task_completed' and data['task_id']=='base:facts')
    attachments_at=next(i for i,(kind,data) in enumerate(events) if kind=='task_started' and data['task_id']=='base:attachments')
    assert facts_at < attachments_at
    observations=events[facts_at][1]['rule_observations']
    assert '1 处空白或占位，其中 0 处' in observations['RL-05']
    assert '1 项正文附件引用' in observations['RL-04']
    assert '可复算关系' in observations['RL-02']
    assert any(kind=='task_started' and 'RL-03' in data.get('rule_scope',{}) for kind,data in events)
    sections=events[facts_at][1]['sections']
    assert [('附件引用','正文引用《价格清单》。'),('关键字段','数据精度指标 · 有占位内容')]==[(s['title'],s['text']) for s in sections]
    assert [s['evidence'][0]['quote'] for s in sections]==[blocks[0]['text'],blocks[1]['text']]
    assert any(kind=='issue_upserted' and data['issue']['rule_id']=='RL-01' and data['issue']['status']=='no_flag_for_target_rule'
               for kind,data in events)


def test_server_indexes_preserve_blank_field_and_responsibility_candidates(monkeypatch):
    def fake(settings,model,prompt,schema,payload,validate,deadline,trace):
        raw=({'attachments':[],'calculations':[],'missing_prices':[],'fields':[]} if schema.__name__=='GroundedFacts' else {'clauses':[]} if schema.__name__=='AssignmentFacts' else {'events':[]} if schema.__name__=='LiabilityFacts' else {'findings':[{'rule_id':r,'status':'no_flag_for_target_rule','explanation':'未触发','refs':[]} for r in ['RL-01','RL-04']]})
        value=schema.model_validate(raw);return value,validate(value)
    monkeypatch.setattr(ar,'extract_call',fake)
    result=review_accurate(Settings('http://test','x'),'deepseek-v4-flash',[{'id':'v:p1','text':'合同编号：'},{'id':'v:p2','text':'7.5乙方每次违约扣款5000元，次数无上限。'}],{'our_party':'乙方'},resolve_rules('review-liability-v1'))
    assert not result['module_errors']
    assert any(i['rule_id']=='CR-01' for i in result['issues'])
    field=next(r for r in result['rule_results'] if r['rule_id']=='RL-05')
    assert field['status']=='no_flag_for_target_rule'
    assert field['field_checks'][0]['name']=='合同编号'
    assert not [i for i in result['issues'] if i['rule_id']=='RL-05' and i['status'] in ('flag','insufficient_evidence')]


def test_contract_identifier_is_not_a_signature_field(monkeypatch):
    def fake(settings,model,prompt,schema,payload,validate,deadline,trace):
        raw=({'attachments':[],'calculations':[],'missing_prices':[],'fields':[{'name':'合同编号','value_state':'blank','timing':'signature_block','refs':['b1'],'requirement_refs':[]}]} if schema.__name__=='GroundedFacts' else {'clauses':[]} if schema.__name__=='AssignmentFacts' else {'events':[]} if schema.__name__=='LiabilityFacts' else {'findings':[{'rule_id':r,'status':'no_flag_for_target_rule','explanation':'未触发','refs':[]} for r in ['RL-01','RL-04']]})
        value=schema.model_validate(raw);return value,validate(value)
    monkeypatch.setattr(ar,'extract_call',fake)
    result=review_accurate(Settings('http://test','x'),'m',[{'id':'v:p1','text':'合同编号：'}],{'our_party':'乙方'},resolve_rules('review-liability-v1'))
    field=next(r for r in result['rule_results'] if r['rule_id']=='RL-05')
    assert field['field_checks'][0]['timing']=='unknown'
    assert field['status']=='no_flag_for_target_rule'


@pytest.mark.parametrize('failure',[False,True])
def test_liability_batches_preserve_coverage_and_partial_failure(monkeypatch,failure):
    from app.liability_review import liability_batches
    monkeypatch.setattr(ar,'liability_batches',lambda payload:liability_batches(payload,limit=1400))
    seen=[]
    def fake(settings,model,prompt,schema,payload,validate,deadline,trace):
        if schema.__name__=='LiabilityFacts':
            seen.extend(b['id'] for b in payload['blocks'])
            if failure and 'b2' in seen:
                raise ExtractionError('gateway_timeout','测试批次超时')
            raw={'events':[{'refs':[r],'liable_party':'乙方'} for r in payload['candidate_refs']]}
        else:
            raw=({'attachments':[],'calculations':[],'missing_prices':[],'fields':[]} if schema.__name__=='GroundedFacts' else {'clauses':[]} if schema.__name__=='AssignmentFacts' else {'findings':[{'rule_id':r,'status':'no_flag_for_target_rule','explanation':'未触发','refs':[]} for r in ['RL-01','RL-04']]})
        value=schema.model_validate(raw);return value,validate(value)
    monkeypatch.setattr(ar,'extract_call',fake)
    blocks=[{'id':f'v:p{i}','text':f'{i}.1乙方每次违约扣款5000元，次数无上限。'+('普通约定。'*150)} for i in range(1,4)]
    result=review_accurate(Settings('http://test','x'),'m',blocks,{'our_party':'乙方'},resolve_rules('review-liability-v1'))
    cr=next(r for r in result['rule_results'] if r['rule_id']=='CR-01')
    if failure:
        assert cr['execution_state']=='failed'
        assert result['module_errors'][0]['module']=='liability'
        assert result['diagnostics']['liability_batches'][-1]['state']=='failed'
        assert next(r for r in result['rule_results'] if r['rule_id']=='RL-05')['execution_state']=='completed'
    else:
        assert not result['module_errors']
        assert seen==['b1','b2','b3']
        assert len([i for i in result['issues'] if i['rule_id']=='CR-01'])==3
        assert all(b['state']=='completed' for b in result['diagnostics']['liability_batches'])
