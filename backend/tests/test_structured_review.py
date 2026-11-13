import json,time
import httpx
import pytest
from app.structured_review import (ContractFacts,Sources,normalize_facts,extract_call,FACT_PROMPT,
    review_structured,grounded_role,PRICE)
from app.llm import Settings,ExtractionError
from app.worker import tick
from app.store import Store
from test_backend import setup


def facts(**changes):
    return {'attachments':[],'calculations':[],'missing_prices':[],'fields':[],**changes}

def attachment(name,tech=None,price=None,refs=None):
    return {'name':name,'references':refs or ['b1'],'technical_refs':tech or [],'pricing_refs':price or []}

def other():
    return {'findings':[{'rule_id':rid,'status':'insufficient_evidence','explanation':'需核实','refs':['b1']} for rid in ('RL-01','RL-03','RL-04')]}

def responses(monkeypatch,values):
    requests=[]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):
            requests.append(kwargs['json']);value=values[len(requests)-1]
            if isinstance(value,Exception):raise value
            if isinstance(value,httpx.Response):return value
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)}}]})
    monkeypatch.setattr(httpx,'Client',Client)
    return requests


@pytest.mark.parametrize('text,name,tech,price,expected',[
 ('接口规范以《技术附件》为准。','技术附件',['b1'],[],'technical'),
 ('费用按《报价表》所列单价计算。','报价表',[],['b1'],'pricing'),
 ('技术参数和报价均详见《技术服务附件》。','技术服务附件',['b1'],['b1'],'mixed'),
 ('双方授权范围以《授权书》为准。','授权书',[],[],'other'),
 ('其他条件详见附件A。','附件A',[],[],'unknown'),
])
def test_grounded_attachment_types(text,name,tech,price,expected):
    source=Sources([{'id':'real-block','text':text}])
    result,_,_=normalize_facts(ContractFacts(**facts(attachments=[attachment(name,tech,price)])),source)
    assert result[0]['kind']==expected
    assert result[0]['reference_evidence'][0]['quote']==text


def test_price_word_from_another_attachment_does_not_leak():
    text='技术要求详见《技术附件》，价格详见《报价附件》。'
    assert not grounded_role('技术附件',text,PRICE)
    source=Sources([{'id':'p','text':text}])
    with pytest.raises(ExtractionError):normalize_facts(ContractFacts(**facts(attachments=[attachment('技术附件',['b1'],['b1'])])),source)


def test_missing_technical_attachment_cannot_be_price_basis():
    source=Sources([{'id':'p','text':'详细技术要求以《技术服务附件》为准。'}])
    data=facts(attachments=[attachment('技术服务附件',['b1'])],missing_prices=[{'kind':'pricing_attachment','attachment_name':'技术服务附件','refs':['b1']}])
    with pytest.raises(ExtractionError):normalize_facts(ContractFacts(**data),source)


def test_unknown_attachment_does_not_prove_pricing_dependency():
    source=Sources([{'id':'p','text':'金额待核对，其他条件详见附件A。'}])
    data=facts(attachments=[attachment('附件A')],missing_prices=[{'kind':'pricing_attachment','attachment_name':'附件A','refs':['b1']}])
    with pytest.raises(ExtractionError):normalize_facts(ContractFacts(**data),source)


def test_real_price_attachment_and_inline_unknown_tax_are_retained():
    source=Sources([{'id':'p','text':'服务费以《报价附件》的计费基数为准，附件尚未提供。'},{'id':'q','text':'按收益的5%计费，含税口径尚未确定。'}])
    data=facts(attachments=[attachment('报价附件',price=['b1'])],missing_prices=[{'kind':'pricing_attachment','attachment_name':'报价附件','refs':['b1']},{'kind':'tax','attachment_name':None,'refs':['b2']}])
    _,amounts,_=normalize_facts(ContractFacts(**data),source)
    assert len(amounts)==2 and all(a.issue=='missing_basis' for a in amounts)


def test_exact_evidence_rebuilt_with_unicode_offsets():
    source=Sources([{'id':'version:p1','text':'🙂 接口格式详见技术附件。'}])
    e=source.evidence(['b1'])[0]
    assert e['quote']=='🙂 接口格式详见技术附件。' and e['end']==len(e['quote'])
    assert e['block_id']=='version:p1'
    with pytest.raises(ExtractionError):source.evidence(['invented'])


def test_bounded_retry_reextracts_without_repairing_or_hiding_failure(monkeypatch):
    requests=responses(monkeypatch,['{bad json',facts(),other()])
    fs=review_structured(Settings('http://test','secret'),'deepseek-v4-flash',[{'id':'p','text':'固定价格100元。'}],{},[])
    trace=next(f for f in fs if f['rule_id']=='RL-04')['extraction_diagnostics']['attempts']
    assert [a['status'] for a in trace]==['rejected','validated','validated']
    assert len(requests)==3 and all(r['response_format']=={'type':'json_object'} and r['temperature']==0 for r in requests)
    assert '{bad json' not in json.dumps(requests[1])


def test_bad_reference_fails_after_one_retry(monkeypatch):
    invalid=facts(fields=[{'name':'日期','value_state':'blank','timing':'unknown','refs':['bad'],'requirement_refs':[]}])
    requests=responses(monkeypatch,[invalid,invalid]);trace=[]
    source=Sources([{'id':'p','text':'日期____'}])
    with pytest.raises(ExtractionError) as caught:
        extract_call(Settings('http://test','secret'),'m',FACT_PROMPT,ContractFacts,{},lambda x:normalize_facts(x,source),time.monotonic()+10,trace)
    assert len(requests)==2 and caught.value.diagnostics[0]['reason']=='unknown_paragraph'
    assert 'secret' not in str(caught.value)


def test_timeout_is_not_retried(monkeypatch):
    requests=responses(monkeypatch,[httpx.ReadTimeout('secret')])
    with pytest.raises(ExtractionError) as caught:review_structured(Settings('http://test','secret'),'m',[{'id':'p','text':'正文'}],{},[])
    assert len(requests)==1 and caught.value.code=='gateway_timeout' and 'secret' not in str(caught.value)


def test_worker_persists_attachment_inventory_and_attempts(setup,monkeypatch):
    c,cid,v,_,path=setup;monkeypatch.setenv('RIXIN_REVIEW_POLICY','redlines-v6')
    run=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'v6'}).json()
    responses(monkeypatch,[facts(attachments=[attachment('附件A')]),other()])
    assert tick(Store(path),Settings('http://test','fake'))
    result=c.get(f"/api/v1/runs/{run['id']}").json()
    assert result['status']=='needs_input' and len(result['findings'])==5
    f=next(x for x in result['findings'] if x['rule_id']=='RL-04')
    assert f['attachment_references'][0]['kind']=='unknown'
    assert len(f['extraction_diagnostics']['attempts'])==2
    assert f['evidence'][0]['block_id']==v['blocks'][0]['id']


def test_negative_pricing_statement_is_not_a_price_dependency():
    text='《技术附件》仅定义接口，不涉及价格。'
    assert not grounded_role('技术附件',text,PRICE)
    assert not grounded_role('技术附件','《技术附件》不包含计费约定。',PRICE)


def test_reference_index_fills_model_omissions_without_inventing_sources():
    from app.reference_index import index_references
    from app.structured_review import TECH,normalize_indexed_facts
    source=Sources([{'id':'p','text':'技术指标与各项服务单价以《技术服务附件》为准，本次未提供。'}])
    seeds,plans=index_references(source,grounded_role,TECH,PRICE)
    normalized,(attachments,amounts,_),audit=normalize_indexed_facts(ContractFacts(**facts()),source,seeds,plans)
    assert attachments[0]['kind']=='mixed' and len(amounts)==1
    assert audit['model_facts']['attachments']==[] and len(normalized.attachments)==1
    assert amounts[0].evidence[0].block_id=='p'


def test_attachment_presence_is_not_copied_from_a_different_file():
    from app.reference_index import explicitly_unavailable
    text='技术要求详见《技术附件》，技术附件未提供，价格详见《报价附件》，报价附件已提供。'
    assert not explicitly_unavailable('报价附件',text)
    assert explicitly_unavailable('技术附件',text)
    assert not explicitly_unavailable('技术附件','技术要求详见《技术附件》，本次未提供运行数据。')


def test_misleading_filename_does_not_override_actual_purpose():
    from app.reference_index import index_references
    from app.structured_review import TECH
    source=Sources([{'id':'p','text':'附件《费用接口说明》仅定义接口数据格式，不涉及计费和价格。'}])
    seeds,_=index_references(source,grounded_role,TECH,PRICE)
    assert seeds[0]['name']=='费用接口说明' and seeds[0]['technical_refs']==['b1'] and seeds[0]['pricing_refs']==[]


def test_chinese_instalments_are_grounded_and_not_multiplied():
    from app.reference_index import index_references
    from app.structured_review import TECH,normalize_indexed_facts
    source=Sources([{'id':'p','text':'含税年度费用八万元；首期一成，尾期九成。'}])
    seeds,plans=index_references(source,grounded_role,TECH,PRICE)
    # A semicolon before the payment plan is still within the same paragraph.
    assert plans[0]['operands']==['10','90']
    raw=ContractFacts(**facts(calculations=[{'operation':'product','operands':['1','9'],'stated_total':'100','refs':['b1']}]))
    _,(_,amounts,_),audit=normalize_indexed_facts(raw,source,seeds,plans)
    from app.amount_review import classify
    status,_,computed=classify(amounts)
    assert status=='no_flag_for_target_rule' and computed[0]['computed']=='100'
    assert audit['model_facts']['calculations'][0]['operation']=='product'


@pytest.mark.parametrize('text',[
 '合同总价100元，首付90%，剩余款的100%在验收后支付。',
 '合同总价100元，首期一成，尾期九成，另有违约金2%。',
 '含税合同总价100元，首期按未税价一成，尾期九成。',
 '合同总价100元，首期一成半，尾期八成半。',
])
def test_ambiguous_payment_basis_not_automatically_normalized(text):
    from app.reference_index import index_references
    from app.structured_review import TECH
    assert index_references(Sources([{'id':'p','text':text}]),grounded_role,TECH,PRICE)[1]==[]


def test_gateway_error_is_not_retried_and_preserves_safe_trace(setup,monkeypatch):
    c,cid,_,_,path=setup;monkeypatch.setenv('RIXIN_REVIEW_POLICY','redlines-v7')
    run=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'http-failure'}).json()
    requests=responses(monkeypatch,[httpx.Response(502,text='fake-secret')])
    assert tick(Store(path),Settings('http://test','fake-secret'))
    result=c.get(f"/api/v1/runs/{run['id']}").json()
    assert result['status']=='failed' and result['findings']==[] and len(requests)==1
    assert result['error']['attempts'][0]['http_status']==502
    assert 'fake-secret' not in json.dumps(result)
