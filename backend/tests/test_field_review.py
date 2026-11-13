import json
import pytest
from app.field_review import FieldObservation,classify
from app.review_jobs import review
from app.llm import Settings,ExtractionError
from test_review_output import output,respond,RULES

TEXT='起草阶段的验收单在交付后填写，投运日期____。签署前须填合同金额，金额【待填写】。付款时间按资金计划安排。'
BLOCKS=[{'id':'p1','text':TEXT}]

def evidence(quote):return {'block_id':'p1','start':0,'end':1,'quote':quote}

def observation(state,timing,required=False):
    return {'name':'测试字段','value_state':state,'timing':timing,'evidence':[evidence('投运日期____')],
            'requirement_evidence':[evidence('签署前须填合同金额')] if required else []}


@pytest.mark.parametrize('state,timing,required,expected',[
 ('filled','current_required',True,'no_flag_for_target_rule'),
 ('blank','future_template',False,'no_flag_for_target_rule'),
 ('blank','signature_block',False,'no_flag_for_target_rule'),
 ('placeholder','current_required',True,'flag'),
 ('placeholder','current_required',False,'insufficient_evidence'),
 ('blank','unknown',False,'insufficient_evidence'),
 ('unavailable','unknown',False,'insufficient_evidence'),
])
def test_observation_classification(state,timing,required,expected):
    assert classify([FieldObservation(**observation(state,timing,required))])[0]==expected


@pytest.mark.parametrize('name',['合同编号','合同号'])
@pytest.mark.parametrize('timing',['unknown','current_required'])
def test_blank_administrative_identifier_without_requirement_is_not_a_todo(name,timing):
    item=FieldObservation(name=name,value_state='blank',timing=timing,evidence=[evidence(name+'：____')])
    assert classify([item])[0]=='no_flag_for_target_rule'


def test_identifier_requirement_and_substantive_missing_field_remain_actionable():
    identifier=FieldObservation(name='合同编号',value_state='blank',timing='current_required',evidence=[evidence('合同编号：____')],requirement_evidence=[evidence('签署前必须填写合同编号')])
    amount=FieldObservation(**(observation('placeholder','unknown')|{'name':'合同金额'}))
    unreadable=FieldObservation(**(observation('unavailable','unknown')|{'name':'合同编号'}))
    assert classify([identifier])[0]=='flag'
    assert classify([amount])[0]=='insufficient_evidence'
    assert classify([unreadable])[0]=='insufficient_evidence'
    assert classify([FieldObservation(**(observation('blank','unknown')|{'name':'合同编号'})),amount])[0]=='insufficient_evidence'


def payload(obs):
    data=output()
    for f in data['findings']:f['evidence']=[evidence('投运日期____')]
    f=data['findings'][-1];f.update(status='flag',explanation='模型错误地判风险',field_checks=[obs],suggested_text='不应写入的建议')
    return data


def test_stage_gate_keeps_model_audit_and_removes_bad_suggestion(monkeypatch):
    respond(monkeypatch,payload(observation('blank','future_template')))
    f=review(Settings('http://test','fake'),'deepseek-v4-flash',BLOCKS,{},RULES,prompt_version='redlines-v3')[-1]
    assert f['status']=='no_flag_for_target_rule' and f['model_proposed_status']=='flag'
    assert f['model_explanation']=='模型错误地判风险'
    assert f['suggested_text'] is None and '当前不自动认定' in f['explanation']
    assert f['field_checks'][0]['evidence'][0]['start']==TEXT.index('投运日期____')


def test_false_field_observation_quote_is_rejected(monkeypatch):
    obs=observation('placeholder','current_required',True);obs['requirement_evidence'][0]['quote']='虚构当前要求'
    respond(monkeypatch,payload(obs))
    with pytest.raises(ExtractionError):review(Settings('http://test','fake'),'deepseek-v4-flash',BLOCKS,{},RULES,prompt_version='redlines-v3')


def test_missing_field_observations_cannot_be_success(monkeypatch):
    data=payload(observation('blank','future_template'));del data['findings'][-1]['field_checks']
    respond(monkeypatch,data)
    with pytest.raises(ExtractionError):review(Settings('http://test','fake'),'deepseek-v4-flash',BLOCKS,{},RULES,prompt_version='redlines-v3')
