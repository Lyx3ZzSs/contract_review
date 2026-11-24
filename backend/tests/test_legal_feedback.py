import json
import sqlite3
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.store import Store, SCHEMA


@pytest.fixture
def feedback(tmp_path):
    from app.legal_feedback import register
    store = Store(tmp_path / 'test.db')
    with store.connect() as db:
        db.execute("INSERT INTO contracts VALUES('c','{}','t')")
        db.execute("INSERT INTO versions VALUES('v','c',1,'hash','x',X'00',?,'t')", (json.dumps({'blocks':[{'id':'p','text':'赔偿全部损失'}]}),))
        db.execute("INSERT INTO runs VALUES('r','c','v','idem','hash','completed',?,'t')", (json.dumps({'id':'r','findings':[{'id':'i'}], 'revision_proposals':[{'proposal_id':'prop'}]}),))
    app = FastAPI()
    register(app, store)
    return TestClient(app), store


def body(**kw):
    return dict(idempotency_key='key', issue_id='i', verdict='agree', actor='填写人', document_version_id='v', **kw)


def test_feedback_idempotency_and_decisions_separate(feedback):
    client, store = feedback
    one = client.post('/api/v1/runs/r/legal-feedback', json=body())
    assert one.status_code == 201
    assert client.post('/api/v1/runs/r/legal-feedback', json=body()).json() == one.json()
    assert client.post('/api/v1/runs/r/legal-feedback', json=body(reason='different')).status_code == 409
    assert len(client.get('/api/v1/runs/r/legal-feedback').json()['items']) == 1
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM decisions').fetchone()[0] == 0
    assert one.json()['state'] == 'candidate'
    assert one.json()['actor_authentication'] == 'self_reported'


@pytest.mark.parametrize('updates', [
    {'issue_id':'foreign'}, {'document_version_id':'other'}, {'proposal_id':'foreign'},
    {'verdict':'false_positive'}, {'verdict':'business_acceptance'},
    {'verdict':'modify_suggestion'}, {'verdict':'missed_issue','issue_id':None,'reason':'漏审'},
    {'event_anchor':{'block_id':'p','start':0,'end':2,'quote':'伪造'}},
])
def test_feedback_rejects_unverifiable_inputs(feedback, updates):
    client, _ = feedback
    payload = body(); payload.update(updates)
    assert client.post('/api/v1/runs/r/legal-feedback', json=payload).status_code == 422


def test_old_version_history_and_missed_anchor(feedback):
    client, store = feedback
    with store.connect() as db:
        db.execute("INSERT INTO versions VALUES('new','c',2,'newhash','x',X'00','{}','later')")
    payload = body(); payload.update(verdict='missed_issue',issue_id=None,reason='漏审赔偿',event_anchor={'block_id':'p','start':0,'end':6,'quote':'赔偿全部损失'})
    result = client.post('/api/v1/runs/r/legal-feedback',json=payload)
    assert result.status_code == 201
    assert result.json()['document_version_id'] == 'v'
    assert result.json()['applies_to_new_versions'] is False


def test_migration_preserves_legacy_data(tmp_path):
    path = tmp_path/'legacy.db'
    db = sqlite3.connect(path); db.executescript(SCHEMA)
    db.execute("INSERT INTO contracts VALUES('c','{\"legacy\":true}','t')")
    db.execute('PRAGMA user_version=7'); db.commit(); db.close()
    Store(path); Store(path)
    db = sqlite3.connect(path)
    assert db.execute('SELECT payload FROM contracts').fetchone()[0] == '{"legacy":true}'
    assert db.execute('PRAGMA user_version').fetchone()[0] == 12
    db.close()


def test_empty_correction_is_valid_deletion_and_business_acceptance_is_distinct(feedback):
    client,store=feedback
    payload=body();payload.update(verdict='modify_suggestion',corrected_text='')
    assert client.post('/api/v1/runs/r/legal-feedback',json=payload).json()['corrected_text']==''
    payload.update(idempotency_key='accept',verdict='business_acceptance',reason='商务承受该风险')
    result=client.post('/api/v1/runs/r/legal-feedback',json=payload)
    assert result.status_code==201
    assert result.json()['verdict']=='business_acceptance'
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM legal_cases').fetchone()[0]==0


def test_correction_preserves_exact_whitespace(feedback):
    client,_=feedback
    payload=body();payload.update(verdict='modify_suggestion',corrected_text='  新正文\n')
    assert client.post('/api/v1/runs/r/legal-feedback',json=payload).json()['corrected_text']=='  新正文\n'
