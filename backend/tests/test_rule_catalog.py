import json
import shutil

"""Presentation isolation and truthful, read-only evaluation provenance."""
from fastapi.testclient import TestClient
from app.main import create_app
from app import rule_catalog
from test_business_catalog import create
from test_backend import docx


def test_editorial_changes_do_not_enter_execution_snapshot(tmp_path, monkeypatch):
    client = TestClient(create_app(tmp_path / 'review.db'))
    before = client.get('/api/v1/rules').json()
    monkeypatch.setitem(rule_catalog.TITLES, 'RL-04', ('文案修改', '只改展示'))
    after = client.get('/api/v1/rules').json()
    assert before['rules'] == after['rules']
    assert before['pack_sha256'] == after['pack_sha256']
    assert before['execution_policy'] == after['execution_policy']
    assert after['presentation']['items']['RL-04']['title'] == '文案修改'
    contract = create(client)
    client.post(f"/api/v1/contracts/{contract['id']}/versions", files={'file': ('review.docx', docx())})
    run = client.post(f"/api/v1/contracts/{contract['id']}/reviews", json={'idempotency_key': 'editorial'}).json()
    assert run['rule_snapshot']['rules'] == before['rules']
    assert 'presentation' not in run['rule_snapshot']


def test_historical_cases_are_unscored_and_not_fake_passes(tmp_path, monkeypatch):
    # Synthetic review records test provenance without publishing customer cases.
    corpus=tmp_path/'corpus';corpus.mkdir()
    for name in ['rules.json','execution-logic-confirmation.json']:
        shutil.copy2(rule_catalog.CORPUS/name,corpus/name)
    labels=[{'case_id':cid,'origin':'historical','reference':{
        'rules':['RL-04'],'title':'工程构造案例','evidence':[{'location':'p1','original':'附件A约定测试服务范围。','source_id':'S02'}],
        'reviewer_comment':'核对测试附件'},'proposed_expected_behavior':'核对材料范围',
        'label_status':'provisional','approved_for_scoring':False} for cid in ['C02','C16']]
    (corpus/'cases.labels.jsonl').write_text('\n'.join(json.dumps(v,ensure_ascii=False) for v in labels))
    monkeypatch.setattr(rule_catalog,'CORPUS',corpus)
    client = TestClient(create_app(tmp_path / 'review.db'))
    result = client.get('/api/v1/rules/RL-04/cases')
    assert result.status_code == 200
    data = result.json()
    historical = [c for c in data['cases'] if c['category'] == 'historical']
    assert {c['id'] for c in historical} == {'C02', 'C16'}
    assert all(c['label_status'] == 'provisional' and not c['approved_for_scoring'] and not c['trials'] for c in historical)
    assert historical[0]['excerpts'][0]['source_id'] == 'S02'
    assert historical[0]['reviewer_comment']
    assert client.get('/api/v1/contracts').json() == []


def test_all_repeats_and_failures_remain_visible(tmp_path):
    client = TestClient(create_app(tmp_path / 'review.db'))
    transfer = client.get('/api/v1/rules/RL-03/cases').json()
    d03 = next(c for c in transfer['cases'] if c['id'] == 'D03')
    assert len(d03['trials']) == 3
    assert all(t['passed'] is False for t in d03['trials'])
    assert transfer['summary']['differences'] == 3
    attachments = client.get('/api/v1/rules/RL-04/cases').json()
    a02 = next(c for c in attachments['cases'] if c['id'] == 'A02')
    assert len(a02['trials']) == 2
    failed = a02['trials'][1]
    assert failed['status'] == 'failed' and failed['passed'] is None
    assert failed['error_code'] == 'gateway_http_error'
    assert attachments['summary']['failed_requests'] == 1
    assert a02['category'] == 'attachment'
    assert a02['expected'] == '报价附件：计价用途'
    assert all(t['policy_version'] == 'redlines-v7' and t['prompt_sha256'] for c in attachments['cases'] for t in c['trials'])


def test_catalog_errors_are_not_empty_success(tmp_path, monkeypatch):
    client = TestClient(create_app(tmp_path / 'review.db'))
    assert client.get('/api/v1/rules/unknown/cases').status_code == 404
    monkeypatch.setattr(rule_catalog, 'EVALUATION', tmp_path)
    response = client.get('/api/v1/rules/RL-04/cases')
    assert response.status_code == 503
    assert '案例资料暂不可用' in response.json()['detail']


def test_every_rule_catalog_and_source_is_readable(tmp_path):
    client = TestClient(create_app(tmp_path / 'review.db'))
    pack = client.get('/api/v1/rules').json()
    assert set(pack['presentation']['items']) == {r['id'] for r in pack['rules']}
    assert all('path' not in s for s in pack['presentation']['sources'])
    for rule in pack['rules']:
        response = client.get(f"/api/v1/rules/{rule['id']}/cases")
        assert response.status_code == 200
        assert response.json()['cases']


def test_public_checkout_does_not_require_private_cases(tmp_path, monkeypatch):
    corpus=tmp_path/'corpus';corpus.mkdir()
    for name in ['rules.json','execution-logic-confirmation.json']:
        shutil.copy2(rule_catalog.CORPUS/name,corpus/name)
    monkeypatch.setattr(rule_catalog,'CORPUS',corpus)
    client=TestClient(create_app(tmp_path/'review.db'))
    response=client.get('/api/v1/rules')
    assert response.status_code==200 and response.json()['presentation']['sources']==[]
    response=client.get('/api/v1/rules/RL-04/cases')
    assert response.status_code==200
    assert response.json()['summary']['historical_cases_available'] is False
    assert response.json()['summary']['historical_cases']==0
    assert response.json()['summary']['engineering_cases']>0
    (corpus/'cases.labels.jsonl').write_text('invalid JSON')
    assert client.get('/api/v1/rules/RL-04/cases').status_code==503
