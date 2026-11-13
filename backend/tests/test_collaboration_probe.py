from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from probes.onlyoffice_collaboration import create_probe
from test_backend import docx
from app import onlyoffice as oo


@pytest.fixture
def probe(tmp_path, monkeypatch):
    monkeypatch.setenv('RIXIN_ONLYOFFICE_SECRET', 'isolated-probe-test')
    monkeypatch.delenv('RIXIN_ONLYOFFICE_SECRET_FILE', raising=False)
    fixture = tmp_path / 'source.docx'
    fixture.write_bytes(docx('仅隔离测试'))
    output = tmp_path / 'output'
    app = create_probe(output, output / 'probe.sqlite3', fixture, 18085)
    return TestClient(app), output, fixture


def test_probe_refuses_existing_database(probe):
    _, output, fixture = probe
    original = (output / 'probe.sqlite3').read_bytes()
    with pytest.raises(ValueError, match='new, explicitly isolated'):
        create_probe(output, output / 'probe.sqlite3', fixture, 18085)
    assert (output / 'probe.sqlite3').read_bytes() == original


def test_probe_uses_shared_key_and_distinct_identity(probe):
    c, _, _ = probe
    lead = c.get('/config/alice?role=lead').json()
    collaborator = c.get('/config/bob?role=collaborator').json()
    assert lead['document']['key'] == collaborator['document']['key']
    assert lead['editorConfig']['callbackUrl'] == collaborator['editorConfig']['callbackUrl']
    assert lead['editorConfig']['user']['id'] != collaborator['editorConfig']['user']['id']
    assert collaborator['document']['permissions']['edit'] is False
    assert collaborator['document']['permissions']['reviewGroups'] == []
    assert oo.verify(lead['token'])['document'] == lead['document']


def test_probe_rejects_forged_callbacks_and_file_tokens(probe):
    c, _, fixture = probe
    config = c.get('/config/alice').json()
    url = urlsplit(config['document']['url'])
    assert c.get(url.path + '?' + url.query).content == fixture.read_bytes()
    assert c.get('/file?token=invalid').status_code == 403
    assert c.post('/callback', json={'key':config['document']['key'],'status':2}).status_code == 403
    body = {'key':config['document']['key'],'status':1,'users':['alice']}
    assert c.post('/callback', json=body, headers={'Authorization':'Bearer ' + oo.sign(body)}).json() == {'error':0}
    assert c.get('/evidence').json()['events'][0]['payload']['users'] == ['alice']


def test_probe_persists_export_without_tokens(probe, monkeypatch):
    c, output, fixture = probe
    config = c.get('/config/alice').json()
    body = {'key':config['document']['key'],'status':6,'url':'http://127.0.0.1:18083/signed-file','userdata':'save-1'}
    monkeypatch.setattr(oo, 'download_document', lambda _: fixture.read_bytes())
    assert c.post('/callback', json=body, headers={'Authorization':'Bearer '+oo.sign(body)}).json() == {'error':0}
    assert (output/'snapshot-1.docx').read_bytes() == fixture.read_bytes()
    c.get('/evidence')
    text = (output/'events.json').read_text()
    assert 'signed-file' not in text and 'token' not in text


def test_probe_rejects_unlisted_users_roles_and_commands(probe):
    c, output, _ = probe
    assert c.get('/?user=unlisted').status_code == 400
    assert c.get('/config/alice?role=admin').status_code == 400
    assert c.post('/command/deleteForgotten').status_code == 400
    html = (output/'browser.html').read_text()
    assert 'http://127.0.0.1:18085/config/' in html
    assert 'JWT_SECRET' not in html
