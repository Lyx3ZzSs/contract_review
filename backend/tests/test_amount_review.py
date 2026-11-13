import pytest
from pydantic import ValidationError
from app.amount_review import AmountObservation,classify
from app.llm import Settings,ExtractionError
from app.review_jobs import review
from test_review_output import output,respond,RULES

E=[{'block_id':'p1','start':0,'end':1,'quote':'总价100元，先付30%，尾款70%按资金计划安排。'}]
BLOCKS=[{'id':'p1','text':E[0]['quote']}]

def observation(**kwargs):
    return AmountObservation(evidence=E,**kwargs)


def test_percentage_sum_is_decimal_not_model_verdict():
    status,_,rows=classify([observation(issue='calculation',operation='sum',operands=['30','70'],stated_total='100',basis='consistent')])
    assert status=='no_flag_for_target_rule' and rows[0]['difference']=='0'
    _,_,rows=classify([observation(issue='calculation',operation='sum',operands=['0.1','0.2'],stated_total='0.3',basis='consistent')])
    assert rows[0]['difference']=='0.0'


def test_nonzero_difference_does_not_invent_tolerance():
    status,_,rows=classify([observation(issue='calculation',operation='product',operands=['100','3'],stated_total='400',basis='consistent')])
    assert status=='insufficient_evidence' and rows[0]['difference']=='-100' and rows[0]['tolerance'] is None


def test_timing_and_missing_basis_have_different_statuses():
    assert classify([observation(issue='payment_timing')])[0]=='no_flag_for_target_rule'
    assert classify([observation(issue='missing_basis')])[0]=='insufficient_evidence'


@pytest.mark.parametrize('value',['NaN','Infinity','1e999999','not-a-number'])
def test_bad_numbers_rejected(value):
    with pytest.raises(ValidationError):observation(issue='calculation',operation='sum',operands=[value,'1'],stated_total='1',basis='consistent')


def test_live_output_gate_preserves_proposed_status_and_audit(monkeypatch):
    data=output()
    for f in data['findings']:f['evidence']=E
    data['findings'][-1].update(status='no_flag_for_target_rule',field_checks=[])
    data['findings'][1].update(status='flag',suggested_text='错误建议',amount_checks=[observation(issue='calculation',operation='sum',operands=['30','70'],stated_total='100',basis='consistent').model_dump()])
    respond(monkeypatch,data)
    f=review(Settings('http://test','fake'),'deepseek-v4-flash',BLOCKS,{},RULES,prompt_version='redlines-v4')[1]
    assert f['status']=='no_flag_for_target_rule' and f['model_proposed_status']=='flag'
    assert f['computed_calculations'][0]['computed']=='100'
    assert f['suggested_text'] is None
    data['findings'][1]['amount_checks'][0]['evidence']=[{**E[0],'quote':'虚构数字'}]
    respond(monkeypatch,data)
    with pytest.raises(ExtractionError):review(Settings('http://test','fake'),'deepseek-v4-flash',BLOCKS,{},RULES,prompt_version='redlines-v4')


def test_only_absence_observation_may_omit_evidence():
    assert classify([AmountObservation(issue='no_comparison',evidence=[])])[0]=='no_flag_for_target_rule'
    for issue in ('missing_basis','payment_timing'):
        with pytest.raises(ValidationError):AmountObservation(issue=issue,evidence=[])
