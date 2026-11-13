import json
import httpx
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app import llm
from test_backend import docx

BLOCKS=[{'id':'p1','text':'  合同金额【待填写】  '}]


def output():
    return {'fields':[{'name':'合同金额','blank':True,'required_now':True,'evidence':[{'block_id':'p1','start':0,'end':1,'quote':'合同金额【待填写】'}]}]}


def test_offsets_recomputed_and_model_cannot_confirm_policy():
    result=llm.validate_output(json.dumps(output(),ensure_ascii=False),BLOCKS)
    assert result.fields[0].required_now is None
    assert result.fields[0].evidence[0].start==2
    assert result.fields[0].evidence[0].end==11


@pytest.mark.parametrize('blocks',[[],[{'id':'p1','text':'合同金额【待填写】合同金额【待填写】'}]])
def test_invalid_or_ambiguous_evidence(blocks):
    with pytest.raises(llm.ExtractionError,match='引用'):
        llm.validate_output(json.dumps(output()),blocks)


def test_untrusted_structure_and_credential_repr():
    with pytest.raises(llm.ExtractionError):
        llm.validate_output('{"origin":"manual_verified","verified_by":"AI"}',BLOCKS)
    assert 'test-secret' not in repr(llm.Settings('http://test','test-secret'))


@pytest.fixture
def api(tmp_path,monkeypatch):
    monkeypatch.setenv('RIXIN_LLM_API_KEY','test-secret')
    monkeypatch.setenv('RIXIN_LLM_BASE_URL','http://test/v1')
    c=TestClient(create_app(tmp_path/'db'))
    cid=c.post('/api/v1/contracts',json={'title':'synthetic','contract_type':'测试','our_party':'乙方','stage':'pre_sign'}).json()['id']
    v=c.post(f'/api/v1/contracts/{cid}/versions',files={'file':('test.docx',docx())}).json()
    return c,cid,v


def test_extraction_verification_link_and_idempotency(api,monkeypatch):
    c,cid,v=api
    calls=[]
    def fake(settings,model,blocks,context):
        calls.append(model)
        return {'facts':{'terms':[],'amounts':[],'transfers':[],'attachments':[],'fields':[]},'usage':{},'elapsed_seconds':0.1}
    monkeypatch.setattr(llm,'extract',fake)
    url=f"/api/v1/versions/{v['id']}/extractions"
    a=c.post(url,json={'idempotency_key':'a'});assert a.status_code==201,a.text
    value=a.json();assert value['origin']=='model_extracted' and value['status']=='needs_verification'
    assert c.post(url,json={'idempotency_key':'a'}).json()==value and len(calls)==1
    assert c.post(url,json={'idempotency_key':'a','model':'glm-5.3-flash'}).status_code==409
    request={'document_version_id':v['id'],'idempotency_key':'run','extraction_id':value['id']}
    assert c.post(f'/api/v1/contracts/{cid}/runs',json=request).status_code==422
    request['facts']={'verified_by':'测试核实人',**value['facts']}
    assert c.post(f'/api/v1/contracts/{cid}/runs',json=request).status_code==201


def test_gateway_failure_is_not_empty_success(api,monkeypatch):
    c,_,v=api
    def fail(*args):
        raise llm.ExtractionError('gateway_timeout','模型调用超时，未采纳结果。')
    monkeypatch.setattr(llm,'extract',fail)
    value=c.post(f"/api/v1/versions/{v['id']}/extractions",json={'idempotency_key':'a'}).json()
    assert value['status']=='failed' and value['facts'] is None
    assert value['error']['code']=='gateway_timeout'
    assert 'test-secret' not in json.dumps(value)


def test_gateway_http_error_redacts_body(monkeypatch):
    class FakeClient:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):return httpx.Response(401,text='test-secret')
    monkeypatch.setattr(httpx,'Client',FakeClient)
    with pytest.raises(llm.ExtractionError) as caught:
        llm.extract(llm.Settings('http://test','test-secret'),'deepseek-v4-flash',BLOCKS,{})
    assert 'test-secret' not in str(caught.value) and caught.value.code=='gateway_http_error'
