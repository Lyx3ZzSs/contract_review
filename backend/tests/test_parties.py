"""Detect wrong signatories, invented evidence, stale uploads and orphan imports."""
import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from test_backend import docx

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('RIXIN_LLM_API_KEY', '')
    return TestClient(create_app(tmp_path/'parties.db'))

def preview(c, text):
    response=c.post('/api/v1/party-previews', files={'file':('contract.docx',docx(text))})
    assert response.status_code==200, response.text
    return response.json()


def test_preview_finds_roles_but_not_mentioned_companies(client):
    p=preview(client,'甲方：北京采购有限公司\n乙方：上海服务有限公司\n联系人：张三\n收款单位：广州银行有限公司\n本项目合作伙伴为杭州其他有限公司。')
    assert [(v['role'],v['name']) for v in p['parties']]==[('甲方','北京采购有限公司'),('乙方','上海服务有限公司')]
    assert all(v['evidence'] and v['source']=='explicit' for v in p['parties'])
    assert client.get('/api/v1/contracts').json()==[]


def test_conflicts_and_empty_results_never_auto_resolve(client):
    p=preview(client,'甲方：北京采购有限公司\n乙方：上海服务有限公司\n甲方（盖章）：天津采购有限公司')
    assert p['status']=='conflict'
    assert len(p['parties'])==3
    p=preview(client,'本项目由北京采购有限公司提供支持。联系人：王五。')
    assert p['parties']==[] and p['status']!='ready'


def selection(p):
    return {'preview_id':p['id'],'our_index':1,'counterparty_indices':[0], 'manual_our_name':None,'manual_counterparties':None}


def import_contract(c, text, chosen):
    return c.post('/api/v1/contracts/import',files={'file':('contract.docx',docx(text))},data={'metadata':json.dumps({'title':'主体验证合同','contract_type':'服务','our_party':'中立审查','data_purpose':'test','party_selection':chosen})})


def test_import_persists_confirmed_parties_and_binds_file(client):
    text='甲方：北京采购有限公司\n乙方：上海服务有限公司'
    p=preview(client,text)
    r=import_contract(client,text,selection(p))
    assert r.status_code==201,r.text
    result=r.json(); details=result['contract']['party_details']
    assert details['our_name']=='上海服务有限公司'
    assert details['counterparties']==['北京采购有限公司']
    assert details['source']=='extracted' and details['confirmed_at']
    assert details['document_version_id']==result['version']['id']
    saved=client.get('/api/v1/contracts/'+result['contract']['id']).json()
    assert saved['party_details']==details
    changed=client.post('/api/v1/contracts/'+result['contract']['id']+'/versions',files={'file':('changed.docx',docx(text+'\n新条款'))},data={'expected_version_id':result['version']['id']})
    assert changed.status_code==201
    assert client.get('/api/v1/contracts/'+result['contract']['id']).json()['party_details']['needs_reconfirmation'] is True


def test_mismatched_or_invalid_selection_cannot_create_contract(client):
    text='甲方：北京采购有限公司\n乙方：上海服务有限公司';p=preview(client,text)
    assert import_contract(client,text+'changed',selection(p)).status_code==409
    bad={**selection(p),'counterparty_indices':[1]}
    assert import_contract(client,text,bad).status_code==422
    assert client.get('/api/v1/contracts?data_purpose=all').json()==[]


def test_manual_and_multilateral_selection(client):
    text='甲方：北京采购有限公司\n乙方：上海服务有限公司\n丙方：杭州技术有限公司';p=preview(client,text)
    chosen={**selection(p),'counterparty_indices':[0,2]}
    assert import_contract(client,text,chosen).json()['contract']['party_details']['counterparties']==['北京采购有限公司','杭州技术有限公司']
    manual={'preview_id':None,'our_index':None,'counterparty_indices':[], 'manual_our_name':'我方公司','manual_counterparties':['人工核对公司']}
    r=import_contract(client,'合同正文',manual)
    assert r.status_code==201,r.text
    assert r.json()['contract']['party_details']['source']=='manual'

@pytest.mark.parametrize('bad', [False, True])
def test_llm_fallback_validates_name_and_role_evidence(tmp_path, monkeypatch, bad):
    import httpx
    monkeypatch.setenv('RIXIN_LLM_API_KEY','test-only-key')
    monkeypatch.setenv('RIXIN_LLM_BASE_URL','http://gateway.test/v1')
    text='本合同采购方为北京采购有限公司，服务方为上海服务有限公司。'
    payload={'parties':[{'name':'不存在有限公司' if bad else '北京采购有限公司','role':'采购方','refs':['p1']}, {'name':'上海服务有限公司','role':'服务方','refs':['p1']}]}
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(payload,ensure_ascii=False)}}]}))
    real_client=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kwargs:real_client(transport=transport,**kwargs))
    c=TestClient(create_app(tmp_path/'llm.db'))
    p=preview(c,text)
    if bad:
        assert p['status']=='failed' and p['parties']==[]
    else:
        assert p['status']=='ready'
        assert p['parties'][0]['name']=='北京采购有限公司'
        assert p['parties'][0]['source']=='llm'


def test_expired_preview_and_opposite_review_role_rejected(client):
    p=preview(client,'甲方：北京采购有限公司\n乙方：上海服务有限公司')
    metadata={'title':'合同','contract_type':'服务','our_party':'甲方 · 采购方','party_selection':selection(p)}
    response=client.post('/api/v1/contracts/import',files={'file':('x.docx',docx('甲方：北京采购有限公司\n乙方：上海服务有限公司'))},data={'metadata':json.dumps(metadata)})
    assert response.status_code==422
    with client.app.state.store.connect() as db:db.execute('UPDATE party_previews SET expires_at=0')
    assert import_contract(client,'甲方：北京采购有限公司\n乙方：上海服务有限公司',selection(p)).status_code==409
    assert client.get('/api/v1/contracts?data_purpose=all').json()==[]


def test_table_cells_and_role_only_labels(client):
    from zipfile import ZipFile
    from io import BytesIO
    buffer=BytesIO()
    with ZipFile(buffer,'w') as z:
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:tbl><w:tr><w:tc><w:p><w:r><w:t>甲方</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>北京采购有限公司</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>乙方：</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>上海服务有限公司</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
    p=client.post('/api/v1/party-previews',files={'file':('table.docx',buffer.getvalue())}).json()
    assert [v['name'] for v in p['parties']]==['北京采购有限公司','上海服务有限公司']
    assert p['parties'][0]['evidence'][1]['quote']=='北京采购有限公司'


def test_names_before_alias_notes_and_side_by_side_signatures(client):
    p=preview(client,'甲方：示例甲方测试服务有限公司     （以下简称“甲方”）\n乙方：国能日新科技股份有限公司\n甲方：示例甲方测试服务有限公司      乙方：国能日新科技股份有限公司')
    assert [(v['role'],v['name']) for v in p['parties']]==[('甲方','示例甲方测试服务有限公司'),('乙方','国能日新科技股份有限公司')]
    p=preview(client,'甲方：上海采购有限公司      乙方：北京服务有限公司')
    assert len(p['parties'])==2


def test_placeholders_and_repeated_signatures_keep_valid_candidates(client):
    p=preview(client,'甲方：____有限公司\n乙方：上海服务有限公司')
    assert [(v['role'],v['name']) for v in p['parties']]==[('乙方','上海服务有限公司')]
    text='甲方：北京采购有限公司\n乙方：上海服务有限公司\n'*11
    p=preview(client,text)
    assert len(p['parties'])==2 and p['status']=='ready'


def test_same_paragraph_does_not_prove_bank_is_buyer():
    from app.parties import validate_candidates
    blocks=[{'id':'p1','text':'采购方为北京采购有限公司。服务方为上海服务有限公司。收款银行为中国工商银行。'}]
    wrong={'parties':[{'name':'中国工商银行','role':'采购方','refs':['p1']}]}
    with pytest.raises(ValueError):validate_candidates(wrong,blocks,'llm')
    right={'parties':[{'name':'北京采购有限公司','role':'采购方','refs':['p1']}]}
    assert validate_candidates(right,blocks,'llm')[0]['name']=='北京采购有限公司'


def test_model_cannot_join_nonadjacent_evidence_or_promote_bank_role():
    from app.parties import validate_candidates
    blocks=[{'id':'p1','text':'甲方：'},{'id':'p2','text':'北京采购有限公司'},{'id':'p4','text':'收款银行：'},{'id':'p5','text':'中国工商银行'}]
    for name,role,refs in [('中国工商银行','甲方',['p1','p5']),('中国工商银行','收款银行',['p4','p5'])]:
        with pytest.raises(ValueError):validate_candidates({'parties':[{'name':name,'role':role,'refs':refs}]},blocks,'llm')
    assert validate_candidates({'parties':[{'name':'北京采购有限公司','role':'甲方','refs':['p1','p2']}]},blocks,'llm')[0]['name']=='北京采购有限公司'
