from copy import deepcopy
import time

import pytest

from app import proposal_recheck_model as module
from app.llm import ExtractionError, Settings


@pytest.fixture
def payload():
    return {
        'previous_blocks': [{'id': 's1', 'text': '7.3 解除合同后不再支付费用。'},
                            {'id': 's2', 'text': '9.1 已提供的服务应结算。'}],
        'current_blocks': [{'id': 'c1', 'text': '7.3 解除合同后不再支付费用。'},
                           {'id': 'c2', 'text': '9.1 已提供的服务应结算，结算上限为实际价款。'}],
        'proposals': [{'proposal_id': 'p1', 'before_text': '不再支付费用',
                       'after_text': '未履行部分不再支付，已提供服务按【待确认】比例结算',
                       'state': 'context_required', 'message': '结算比例待确认',
                       'target_ref': 'c1', 'requirements': [], 'related_findings': []}],
        'context': {}, 'confirmed_case_guidance': [],
    }


def settings():
    return Settings('https://invalid.test', 'test-only', timeout=8)


def result(status='applicable', refs=None):
    return {'proposal_id': 'p1', 'status': status, 'reason': '原有待确认比例仍保留，结算要求未冲突。',
            'related_refs': refs if refs is not None else ['c2']}


def stub(monkeypatch, rows, observed=None):
    def call(s, model, prompt, schema, data, validate, deadline, trace):
        if observed is not None:
            observed.update(settings=s, model=model, prompt=prompt, payload=deepcopy(data), deadline=deadline)
        trace.append({'stage': schema.__name__, 'status': 'validated'})
        value = schema.model_validate({'results': rows})
        return value, validate(value)
    monkeypatch.setattr(module, 'extract_call', call)


def test_verified_applicability_keeps_full_context_and_does_not_mutate_draft(payload, monkeypatch):
    original=deepcopy(payload);observed={};s=settings()
    stub(monkeypatch,[result()],observed)
    before=time.monotonic();rows,trace=module.verify_applicability(s,'test-model',payload)
    assert rows==[result()]
    assert payload==original and observed['payload']==original
    assert trace[0]['transport_attempt']==1
    assert before < observed['deadline'] <= time.monotonic()+16
    assert observed['settings'].max_output_tokens==32768
    assert observed['settings'].stream_callback('delta', text='未核验输出') is None
    assert s.stream_callback is None and s.max_output_tokens==4096


def test_cross_clause_change_can_block_one_proposal_without_dropping_other_results(payload, monkeypatch):
    payload['proposals'].append({**payload['proposals'][0], 'proposal_id':'p2'})
    rows=[result('needs_revision',['c2']),{**result(),'proposal_id':'p2'}]
    stub(monkeypatch,rows)
    checked,_=module.verify_applicability(settings(),'test-model',payload)
    assert checked==rows


@pytest.mark.parametrize('rows',[
    [],
    [result(),result()],
    [{**result(),'proposal_id':'unknown'}],
    [result(),{**result(),'proposal_id':'extra'}],
    [result('needs_revision',[])],
    [result('needs_revision',['s2'])],
    [result('applicable',['c2','c2'])],
])
def test_incomplete_duplicate_or_unverifiable_results_are_never_accepted(payload,monkeypatch,rows):
    # The real extract_call converts schema errors into ExtractionError. Preserve
    # that boundary in this stub, while testing our per-request validation too.
    from pydantic import ValidationError
    stub(monkeypatch,rows)
    with pytest.raises((ExtractionError,ValidationError)):
        module.verify_applicability(settings(),'test-model',payload)


@pytest.mark.parametrize('fault',['duplicate_proposal','missing_target','duplicate_block','large_text','too_many'])
def test_invalid_or_oversized_input_fails_before_gateway(payload,monkeypatch,fault):
    if fault=='duplicate_proposal':payload['proposals']*=2
    if fault=='missing_target':payload['proposals'][0]['target_ref']='missing'
    if fault=='duplicate_block':payload['current_blocks']*=2
    if fault=='large_text':payload['current_blocks'][0]['text']='文'*80000
    if fault=='too_many':payload['proposals']=[{**payload['proposals'][0],'proposal_id':str(i)} for i in range(41)]
    def unexpected(*a,**k):pytest.fail('Gateway must not be called')
    monkeypatch.setattr(module,'extract_call',unexpected)
    with pytest.raises(ExtractionError):module.verify_applicability(settings(),'test-model',payload)


def test_gateway_failure_remains_failure_after_bounded_retry(payload,monkeypatch):
    calls=[]
    def failing(*args):
        calls.append(args[6]);raise ExtractionError('gateway_timeout','连接超时')
    monkeypatch.setattr(module,'extract_call',failing)
    monkeypatch.setattr('app.review_transport.time.sleep',lambda _:None)
    with pytest.raises(ExtractionError,match='连接超时') as error:
        module.verify_applicability(settings(),'test-model',payload)
    assert len(calls)==2 and calls[0]==calls[1]
    assert len(error.value.attempts)==2


def test_missing_configuration_never_returns_success(payload):
    with pytest.raises(ExtractionError) as error:
        module.verify_applicability(Settings('',''),'test-model',payload)
    assert error.value.code=='not_configured'
