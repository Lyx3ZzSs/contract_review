import io
import json
from pathlib import Path
from zipfile import ZipFile
from xml.sax.saxutils import escape
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.models import Facts
from app.engine import check


def docx(text='服务期12个月；金额400元；附件A；合同金额【待填写】'):
    stream = io.BytesIO()
    with ZipFile(stream, 'w') as z:
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>' + escape(text) + '</w:t></w:r></w:p></w:body></w:document>')
    return stream.getvalue()


@pytest.fixture
def setup(tmp_path):
    path = tmp_path/'review.db'
    app = create_app(path)
    client = TestClient(app)
    cid = client.post('/api/v1/contracts', json={'title':'验证合同','contract_type':'数据服务','our_party':'乙方','stage':'pre_sign'}).json()['id']
    file = docx()
    response = client.post(f'/api/v1/contracts/{cid}/versions', files={'file':('contract.docx',file)})
    assert response.status_code == 201, response.text
    version = response.json()
    return client, cid, version, file, path


def start(setup, key='one', facts=None):
    client,cid,version,*_ = setup
    return client.post(f'/api/v1/contracts/{cid}/runs', json={'document_version_id':version['id'],'idempotency_key':key,'facts':facts})


def test_persistence_and_bytes(setup):
    c,cid,v,data,path = setup
    assert c.get(f"/api/v1/versions/{v['id']}/file").content == data
    again = TestClient(create_app(path))
    assert again.get(f'/api/v1/contracts/{cid}').json()['current_document_version_id'] == v['id']


def test_no_model_is_not_no_risk(setup):
    c,*_ = setup
    run = start(setup).json()
    result = c.post(f"/api/v1/runs/{run['id']}/execute").json()
    assert result['status'] == 'needs_input'
    assert len(result['findings']) == 5
    assert all(f['status']=='insufficient_evidence' for f in result['findings'])
    assert c.post(f"/api/v1/runs/{run['id']}/execute").json() == result


def test_idempotency_concurrent_and_conflict(setup):
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _:start(setup).json()['id'], range(2)))
    assert len(set(ids)) == 1
    assert start(setup, facts={'verified_by':'测试人'}).status_code == 409


def test_stale_save_and_run(setup):
    c,cid,v,*_ = setup
    run = start(setup).json()
    assert c.post(f'/api/v1/contracts/{cid}/versions', files={'file':('new.docx',docx())}).status_code == 409
    assert c.post(f'/api/v1/contracts/{cid}/versions', data={'expected_version_id':v['id']}, files={'file':('new.docx',docx('新正文'))}).status_code == 201
    assert c.post(f"/api/v1/runs/{run['id']}/execute").status_code == 409
    assert c.get(f"/api/v1/runs/{run['id']}").json()['stale']
    assert start(setup, key='new').status_code == 409


def test_cross_contract_document_rejected(setup):
    c,_,v,*_ = setup
    cid = c.post('/api/v1/contracts', json={'title':'另一个','contract_type':'软件','our_party':'甲方'}).json()['id']
    assert c.post(f'/api/v1/contracts/{cid}/runs', json={'document_version_id':v['id'],'idempotency_key':'x'}).status_code == 422


def test_evidence_mismatch_rejected(setup):
    facts={'verified_by':'测试','fields':[{'name':'金额','blank':True,'required_now':True,'evidence':[{'block_id':'wrong','start':0,'end':2,'quote':'金额'}]}]}
    assert start(setup,facts=facts).status_code == 422


def test_actual_fact_and_immutable_result(setup):
    c,cid,v,data,_ = setup
    b=v['blocks'][0]
    evidence={'block_id':b['id'],'start':0,'end':len(b['text']),'quote':b['text']}
    facts={'verified_by':'测试','fields':[{'name':'金额','blank':True,'required_now':True,'evidence':[evidence]}]}
    run=start(setup,facts=facts).json()
    result=c.post(f"/api/v1/runs/{run['id']}/execute").json()
    assert next(f for f in result['findings'] if f['rule_id']=='RL-05')['status']=='flag'
    complete={'opinion':'人工核对完成','reservations':'其他事项待补资料','reviewer':'测试'}
    assert c.post(f"/api/v1/runs/{run['id']}/results",json=complete).status_code==409
    for f in result['findings']:
        assert c.post(f"/api/v1/runs/{run['id']}/findings/{f['id']}/decisions",json={'action':'needs_business_confirmation','note':'待业务补证','actor':'测试'}).status_code==201
    assert c.post(f"/api/v1/runs/{run['id']}/results",json=complete).status_code==409
    for f in result['findings']:
        assert c.post(f"/api/v1/runs/{run['id']}/findings/{f['id']}/decisions",json={'action':'acknowledged','note':'补证已核对','actor':'测试'}).status_code==201
    final=c.post(f"/api/v1/runs/{run['id']}/results",json=complete)
    assert final.status_code==201,final.text
    rid=final.json()['id']
    assert c.post(f"/api/v1/runs/{run['id']}/results",json=complete).status_code==409
    assert c.post(f'/api/v1/contracts/{cid}/versions',data={'expected_version_id':v['id']},files={'file':('new.docx',docx('new'))}).status_code==201
    assert c.get(f'/api/v1/results/{rid}').json()==final.json()
    assert c.get(f"/api/v1/versions/{v['id']}/file").content==data


def test_failed_execution_is_persisted(setup,monkeypatch):
    import app.main as main
    c,*_=setup
    run=start(setup).json()
    def broken(*args):
        raise RuntimeError('test failure')
    monkeypatch.setattr(main,'check',broken)
    value=c.post(f"/api/v1/runs/{run['id']}/execute").json()
    assert value['status']=='failed' and value['error']['code']=='execution_error'
    assert c.get(f"/api/v1/runs/{run['id']}").json()['status']=='failed'


def test_bad_file(setup):
    c,cid,*_=setup
    assert c.post(f'/api/v1/contracts/{cid}/versions',files={'file':('x.doc',b'bad')}).status_code==415
    assert c.post(f'/api/v1/contracts/{cid}/versions',files={'file':('x.docx',b'bad')}).status_code==422


def test_parser_keeps_original_bytes_but_excludes_deleted_text():
    from app.parser import parse_docx
    b=io.BytesIO()
    with ZipFile(b,'w') as z:
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:del><w:r><w:delText>旧条款</w:delText></w:r></w:del><w:ins><w:r><w:t>新条款</w:t></w:r></w:ins></w:p></w:body></w:document>')
    value=parse_docx(b.getvalue())
    assert value['blocks'][0]['text']=='新条款' and value['tracked_changes_present']


# Human-normalized inputs for the existing T01-T15 draft scenarios.
# This tests rule computation, NOT natural-language extraction or model accuracy.
SCENARIOS=json.loads((Path(__file__).parent/'fixtures/redline-scenarios.json').read_text())


def normalized(index, ev):
    term=lambda kind,n:dict(subject='同一场站',term_type=kind,start_event='2026-01-01',duration_months=n,comparison_confirmed=True,evidence=[ev])
    amount=lambda parts,total,confirmed=True:dict(components=parts,stated=total,currency='CNY',unit='元',basis='含税',same_basis_confirmed=confirmed,tolerance='0',evidence=[ev])
    transfer=lambda party,consent:dict(party=party,consent=consent,exceptions_resolved=True,evidence=[ev])
    attach=lambda state,complete=True:dict(name='附件A',state=state,bundle_complete=complete,required_now=True,evidence=[ev])
    field=lambda req:dict(name='合同金额',blank=True,required_now=req,evidence=[ev])
    data=[{'terms':[term('服务',12),term('服务',24)]},
          {'terms':[term('服务',12),term('质保',24)]},
          {'terms':[term('服务',12)]},
          {'amounts':[amount(['100','100','100'],'400')]},
          {'amounts':[amount(['60000','48000','12000'],'120000')]},
          {'amounts':[amount(['100'],'106',False)]},
          {'transfers':[transfer('customer','not_required')]},
          {'transfers':[transfer('both','required')]},
          {'transfers':[transfer('our_party','required')]},
          {'attachments':[attach('missing')]},
          {'attachments':[attach('provided')]},
          {'attachments':[attach('unreadable')]},
          {'fields':[field(True)]},
          {'fields':[field(False)]},
          {'fields':[field(None)]}][index]
    return Facts(verified_by='测试构造事实，非法务裁定',**data)


@pytest.mark.parametrize('index',range(15),ids=[s['id'] for s in SCENARIOS])
def test_draft_scenario_behavior(index):
    s=SCENARIOS[index]
    ev={'block_id':'test','start':0,'end':len(s['scenario']),'quote':s['scenario']}
    results=[r for r in check(normalized(index,ev),'pre_sign') if r['rule_id']==s['rule_id']]
    statuses={r['status'] for r in results}
    if s['proposed_expected_class']=='应提示':
        assert 'flag' in statuses
    elif s['proposed_expected_class']=='证据不足':
        assert statuses=={'insufficient_evidence'}
    else:
        assert 'flag' not in statuses


def test_unconfirmed_tolerance_never_defaults_to_zero():
    ev={'block_id':'test','start':0,'end':1,'quote':'价'}
    facts=Facts(verified_by='测试',amounts=[dict(components=['0.1','0.2'],stated='0.31',currency='CNY',unit='元',basis='含税',same_basis_confirmed=True,evidence=[ev])])
    r=next(r for r in check(facts,'pre_sign') if r['rule_id']=='RL-02')
    assert r['status']=='insufficient_evidence'
    assert r['calculation']['computed']=='0.3'


def test_evidence_preserves_whitespace_and_unicode(setup):
    c,cid,v,*_=setup
    raw='  😀金额【待填写】  '
    doc=c.post(f'/api/v1/contracts/{cid}/versions',data={'expected_version_id':v['id']},files={'file':('spaces.docx',docx(raw))}).json()
    assert doc['blocks'][0]['text']==raw
    b=doc['blocks'][0]
    facts={'verified_by':'测试','fields':[{'name':'金额','blank':True,'required_now':True,'evidence':[{'block_id':b['id'],'start':0,'end':len(raw),'quote':raw}]}]}
    result=c.post(f'/api/v1/contracts/{cid}/runs',json={'document_version_id':doc['id'],'idempotency_key':'spaces','facts':facts})
    assert result.status_code==201,result.text
    checked=c.post('/api/v1/runs/'+result.json()['id']+'/execute').json()
    assert next(f for f in checked['findings'] if f['rule_id']=='RL-05')['evidence'][0]['quote']==raw
