"""Business catalog isolation and server-owned policy visibility."""
import json
from fastapi.testclient import TestClient
from app.main import create_app
from app.store import Store
from app.review_policy import PROMPTS, prompt_hash
from test_backend import docx


def create(client, **fields):
    response = client.post('/api/v1/contracts', json={
        'title': '合同', 'contract_type': '数据服务', 'our_party': '乙方', **fields})
    assert response.status_code == 201
    return response.json()


def test_catalog_excludes_test_data_without_deleting_it(tmp_path):
    client = TestClient(create_app(tmp_path / 'review.db'))
    assert client.get('/api/v1/contracts').json() == []
    # A title mentioning tests must not cause a genuine business record to vanish.
    business = create(client, title='测试服务采购合同')
    test = create(client, title='构造验收合同', data_purpose='test')
    assert [r['id'] for r in client.get('/api/v1/contracts').json()] == [business['id']]
    assert [r['id'] for r in client.get('/api/v1/contracts?data_purpose=test').json()] == [test['id']]
    assert len(client.get('/api/v1/contracts?data_purpose=all').json()) == 2
    assert client.get('/api/v1/contracts/' + test['id']).status_code == 200
    assert client.get('/api/v1/contracts?data_purpose=invalid').status_code == 422


def test_legacy_migration_only_marks_known_acceptance_ids(tmp_path):
    path = tmp_path / 'review.db'
    store = Store(path)
    known = '0932e3ea-fae0-4afc-8df0-ba254cd3a574'
    for cid in (known, 'real-business'):
        with store.connect() as db:
            db.execute('INSERT INTO contracts VALUES(?,?,?)',
                       (cid, json.dumps({'id': cid, 'title': '后端接入验收合同'}), '2026-11-10'))
    Store(path)
    Store(path)  # Idempotent restart.
    client = TestClient(create_app(path))
    assert [r['id'] for r in client.get('/api/v1/contracts').json()] == ['real-business']
    assert client.get('/api/v1/contracts?data_purpose=test').json()[0]['id'] == known


def test_displayed_policy_matches_queued_snapshot(tmp_path, monkeypatch):
    monkeypatch.setenv('RIXIN_REVIEW_POLICY', 'redlines-v6')
    client = TestClient(create_app(tmp_path / 'review.db'))
    pack = client.get('/api/v1/rules').json()
    assert [r['id'] for r in pack['rules']] == [f'RL-0{i}' for i in range(1, 6)]
    policy = pack['execution_policy']
    assert policy['version'] == 'redlines-v6'
    assert policy['instructions'] == PROMPTS['redlines-v6']
    assert policy['prompt_sha256'] == prompt_hash('redlines-v6')
    assert policy['production_approved'] is False
    contract = create(client)
    client.post(f"/api/v1/contracts/{contract['id']}/versions", files={'file': ('review.docx', docx())})
    response = client.post(f"/api/v1/contracts/{contract['id']}/reviews", json={'idempotency_key': 'policy-check'})
    assert response.status_code == 202, response.text
    run = response.json()
    assert run['review_prompt_version'] == policy['version']
    assert run['review_prompt_sha256'] == policy['prompt_sha256']
    assert run['rule_snapshot']['rules'] == pack['rules']
    assert run['rule_snapshot']['pack_sha256'] == pack['pack_sha256']
    monkeypatch.setenv('RIXIN_REVIEW_POLICY', 'invalid')
    assert client.get('/api/v1/rules').status_code == 503
    assert client.get('/api/v1/runs/' + run['id']).json()['review_prompt_version'] == 'redlines-v6'
