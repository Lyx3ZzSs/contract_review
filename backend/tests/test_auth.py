"""Real RSA verification and cross-user authorization regressions (no live accounts)."""
import json
import time
from types import SimpleNamespace
from pathlib import Path
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from app.main import create_app
from app.auth import AUDIENCE, ISSUER

@pytest.fixture
def secured(tmp_path, monkeypatch):
    monkeypatch.setenv('RIXIN_AUTH_ENABLED', '1')
    app = create_app(tmp_path / 'secured.sqlite3')
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    app.state.token_verifier.jwks = SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key()))
    def headers(sub='alice', roles=('agent_user',), **overrides):
        claims = {'sub': sub, 'iss': ISSUER, 'aud': [AUDIENCE, 'account'], 'exp': time.time()+300,
                  'name': '测试用户', 'department_code': 'IT', 'department_name': '研发中心',
                  'resource_access': {AUDIENCE: {'roles': list(roles)}}}
        claims.update(overrides)
        return {'Authorization': 'Bearer '+jwt.encode(claims, key, algorithm='RS256', headers={'kid': 'test'})}
    return TestClient(app), headers, app, key

BODY = {'title': '合成权限测试合同', 'contract_type': '采购', 'our_party': '甲方'}

def test_auth_denies_missing_invalid_wrong_issuer_audience_and_expired(secured):
    c, h, app, key = secured
    assert c.get('/health').status_code == 200
    assert c.get('/api/v1/contracts').status_code == 401
    for headers in [{'Authorization': 'Bearer garbage'}, h(iss='https://wrong.invalid'), h(aud='other'), h(exp=time.time()-60), h(sub='')]:
        assert c.get('/api/v1/contracts', headers=headers).status_code == 401
    for missing in ('exp','iss','aud','sub'):
        payload = jwt.decode(h()['Authorization'][7:], options={'verify_signature':False})
        payload.pop(missing)
        assert c.get('/api/v1/contracts',headers={'Authorization':'Bearer '+jwt.encode(payload,key,algorithm='RS256')}).status_code == 401
    other = rsa.generate_private_key(public_exponent=65537,key_size=2048)
    payload = jwt.decode(h()['Authorization'][7:], options={'verify_signature':False})
    for token in (jwt.encode(payload,other,algorithm='RS256'), jwt.encode(payload,'x'*32,algorithm='HS256')):
        assert c.get('/api/v1/contracts', headers={'Authorization':'Bearer '+token}).status_code == 401
    assert c.get('/api/v1/contracts',params={'access_token':h()['Authorization'][7:]}).status_code == 401


def test_roles_profile_and_ownership(secured):
    c, h, app, _ = secured
    assert c.get('/api/v1/auth/me',headers=h(roles=())).json()['roles'] == []
    assert c.get('/api/v1/contracts',headers=h(roles=())).status_code == 403
    profile=c.get('/api/v1/auth/me',headers=h()).json()
    assert profile['sub']=='alice' and profile['department_code']=='IT'
    with app.state.store.connect() as db:
        assert db.execute('SELECT sub FROM auth_users').fetchone()[0]=='alice'
    response=c.post('/api/v1/contracts',json=BODY,headers=h())
    assert response.status_code==201, response.text
    cid=response.json()['id']
    assert response.json()['owner_sub']=='alice'
    assert c.get('/api/v1/contracts',headers=h('bob')).json()==[]
    assert c.get('/api/v1/contracts/'+cid,headers=h('bob')).status_code==404
    assert c.get('/api/v1/contracts/'+cid,headers=h('manager',('agent_manager',))).status_code==404
    assert c.get('/api/v1/contracts/'+cid,headers=h('admin',('agent_admin',))).status_code==200
    assert c.get('/api/v1/legal-cases',headers=h()).status_code==403
    assert c.get('/api/v1/legal-cases',headers=h('admin',('agent_admin',))).status_code==200
    # Anonymous legacy records are not silently assigned to the first login.
    with app.state.store.connect() as db:
        db.execute('INSERT INTO contracts VALUES(?,?,?)',('legacy',json.dumps({'id':'legacy',**BODY}),'2026-01-01'))
    assert c.get('/api/v1/contracts/legacy',headers=h()).status_code==404
    assert len(c.get('/api/v1/contracts',headers=h('admin',('agent_admin',))).json())==2


def test_nested_resources_download_and_body_references(secured):
    c,h,app,_=secured
    cid=c.post('/api/v1/contracts',json=BODY,headers=h()).json()['id']
    doc=Path(__file__).parent/'fixtures/review-room-contract.docx'
    version=c.post(f'/api/v1/contracts/{cid}/versions',files={'file':('test.docx',doc.read_bytes())},headers=h())
    assert version.status_code==201,version.text
    vid=version.json()['id']
    assert c.get(f'/api/v1/versions/{vid}/file').status_code==401
    assert c.get(f'/api/v1/versions/{vid}/file',headers=h('bob')).status_code==404
    assert c.get(f'/api/v1/versions/{vid}/file',headers=h()).status_code==200
    other=c.post('/api/v1/contracts',json=BODY,headers=h('bob')).json()['id']
    assert c.post(f'/api/v1/contracts/{other}/reviews',json={'document_version_id':vid,'idempotency_key':'attempt'},headers=h('bob')).status_code==404
    with app.state.store.connect() as db:
        payload={'id':'run-test','contract_id':cid,'document_version_id':vid,'status':'failed','created_at':'2026-01-01','findings':[]}
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)',('run-test',cid,vid,'idem','hash','failed',json.dumps(payload),'2026-01-01'))
    for route in ('runs/run-test','runs/run-test/execution-state','runs/run-test/execution-stream','review-records/run-test'):
        assert c.get('/api/v1/'+route,headers=h('bob')).status_code==404
    records=c.get('/api/v1/review-records',headers=h('bob')).json()
    assert records['items']==[] and records['counts']['all']==0
    assert c.get('/api/v1/review-records',headers=h()).json()['total']==1


def test_onlyoffice_exceptions_still_require_internal_signatures(secured,monkeypatch):
    c,h,app,_=secured
    monkeypatch.setenv('RIXIN_ONLYOFFICE_SECRET','test-onlyoffice-secret')
    assert c.get('/api/v1/editor-sessions/unknown/file?token=invalid').status_code==403
    assert c.post('/api/v1/onlyoffice/callback/unknown',json={'status':2,'token':'bad'}).status_code==403
    assert c.get('/api/v1/editor-sessions/unknown/heartbeat').status_code==401


def test_import_idempotency_and_previews_are_user_scoped(secured):
    c,h,app,_=secured
    content=(Path(__file__).parent/'fixtures/review-room-contract.docx').read_bytes()
    metadata={**BODY,'idempotency_key':'same-client-key','party_selection':{'manual_our_name':'合成采购公司','manual_counterparties':['合成服务公司']}}
    def upload(user, value):
        return c.post('/api/v1/contracts/import',headers=h(user),files={'file':('contract.docx',content)},data={'metadata':json.dumps(value)})
    alice=upload('alice',metadata);bob=upload('bob',metadata)
    assert alice.status_code==bob.status_code==201
    assert alice.json()['contract']['id']!=bob.json()['contract']['id']
    assert upload('alice',metadata).json()['contract']['id']==alice.json()['contract']['id']
    with app.state.store.connect() as db:
        db.execute('INSERT INTO party_previews VALUES(?,?,?)',('alice-preview',json.dumps({'owner_sub':'alice'}),time.time()+300))
    blocked={**metadata,'idempotency_key':'new-key','party_selection':{**metadata['party_selection'],'preview_id':'alice-preview'}}
    assert upload('bob',blocked).status_code==404


def test_signed_reviewer_owns_decision_and_snapshot(secured):
    client,headers,app,_=secured
    content=(Path(__file__).parent/'fixtures/review-room-contract.docx').read_bytes()
    for sub in ('first','second'):
        h=headers(sub)
        cid=client.post('/api/v1/contracts',json=BODY,headers=h).json()['id']
        vid=client.post(f'/api/v1/contracts/{cid}/versions',files={'file':('test.docx',content)},headers=h).json()['id']
        rid=client.post(f'/api/v1/contracts/{cid}/runs',json={'idempotency_key':'run','document_version_id':vid},headers=h).json()['id']
        finding=client.post(f'/api/v1/runs/{rid}/execute',headers=h).json()['findings'][0]['id']
        route=f'/api/v1/runs/{rid}/findings/{finding}/decisions'
        body={'action':'acknowledged','note':'人工确认','actor':'客户端旧显示名'}
        assert client.post(route,json=body,headers=headers('other')).status_code==404
        record=client.post(route,json=body,headers=h).json()
        assert (record['actor_sub'],record['actor'])==(sub,'测试用户')
        route=f'/api/v1/runs/{rid}/results'
        assert client.post(route,json={'expected_document_version_id':'outdated'},headers=h).status_code==409
        receipt=client.post(route,json={'expected_document_version_id':vid},headers=h).json()
        assert (receipt['reviewer_sub'],receipt['reviewer'])==(sub,'测试用户')
        assert receipt['decisions']==[record]
        assert client.post(route,json={'editor_session_id':'ended'},headers=h).json()==receipt


def test_oidc_deployment_and_discovery_transport(monkeypatch):
    from app.auth import TokenVerifier, validate_oidc_url
    monkeypatch.setenv('RIXIN_ENV','production')
    monkeypatch.setenv('RIXIN_OIDC_ISSUER',ISSUER)
    with pytest.raises(ValueError,match='HTTPS'):TokenVerifier()
    monkeypatch.setenv('RIXIN_OIDC_ISSUER','https://company.example/realm')
    verifier=TokenVerifier()
    validate_oidc_url(verifier.issuer+'/keys')
    with pytest.raises(ValueError):validate_oidc_url('http://company.example/keys')
    validate_oidc_url(ISSUER+'/keys',True)
    with pytest.raises(ValueError):validate_oidc_url('http://other.example/keys',True)
