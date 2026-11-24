from test_backend import setup, docx
from app.store import Store


def upload(c, cid, data=None, name='技术协议.docx', key='m1'):
    return c.post(f'/api/v1/contracts/{cid}/materials', files={'file':(name, data or docx('技术协议：接口采用 HTTPS，传输周期为15分钟。'))}, data={'idempotency_key':key})


def test_material_version_idempotency_and_content_conflict(setup):
    c,cid,*_=setup
    first=upload(c,cid)
    assert first.status_code==201, first.text
    assert first.json()['parse_status']=='parsed'
    assert first.json()['blocks'][0]['text'].startswith('技术协议')
    assert upload(c,cid).json()==first.json()
    assert upload(c,cid,docx('不同版本')).status_code==409
    second=upload(c,cid,docx('技术协议第二版'),key='m2').json()
    assert second['id']!=first.json()['id']
    assert len(c.get(f'/api/v1/contracts/{cid}/materials').json())==2


def test_unreadable_material_is_visible_and_never_empty_success(setup):
    c,cid,*_=setup
    bad=upload(c,cid,b'broken',key='bad').json()
    assert bad['parse_status']=='failed' and bad['blocks']==[]
    image=upload(c,cid,b'\x89PNG\r\n\x1a\ncontent',name='附件.png',key='png').json()
    assert image['parse_status']=='unsupported' and image['blocks']==[]
    assert image['limitations']
    assert c.get(f'/api/v1/contracts/{cid}/materials').status_code==200


def test_material_namespace_and_cross_contract_download(setup):
    c,cid,v,*_=setup
    m=upload(c,cid).json()
    assert m['blocks'][0]['id'].startswith(m['id']+':')
    other=c.post('/api/v1/contracts',json={'title':'另一个','contract_type':'服务','our_party':'甲方'}).json()['id']
    assert c.get(f"/api/v1/contracts/{other}/materials/{m['id']}/file").status_code==404
    assert c.get(f"/api/v1/contracts/{cid}/materials/{m['id']}/file").status_code==200


def test_store_upgrade_preserves_payload_and_is_repeatable(setup):
    c,cid,_,_,path=setup
    with Store(path).connect() as db:
        original=db.execute('SELECT payload FROM contracts WHERE id=?',(cid,)).fetchone()[0]
        db.execute('PRAGMA user_version=5')
    for _ in range(2):
        with Store(path).connect() as db:
            assert db.execute('PRAGMA user_version').fetchone()[0]>=6
            assert db.execute('SELECT payload FROM contracts WHERE id=?',(cid,)).fetchone()[0]==original


def test_rejected_upload_limits_do_not_create_material_records(setup,monkeypatch):
    from app import materials
    c,cid,*_=setup
    monkeypatch.setattr(materials,'MAX_FILE',64)
    assert upload(c,cid,b'x'*65).status_code==413
    monkeypatch.setattr(materials,'MAX_FILE',20*1024*1024)
    def too_large(data):
        raise ValueError('DOCX解压内容超过限制')
    monkeypatch.setattr(materials,'parse_docx',too_large)
    assert upload(c,cid,b'compressed-document').status_code==413
    assert c.get(f'/api/v1/contracts/{cid}/materials').json()==[]


def test_material_bundle_file_count_rejection_preserves_active_snapshot(setup):
    import pytest
    from fastapi import HTTPException
    from app.materials import save_bundle,current_bundle
    c,cid,v,_,path=setup
    ids=[upload(c,cid,key=f'm{i}').json()['id'] for i in range(21)]
    with Store(path).connect() as db:
        original=save_bundle(db,cid,v['id'],ids[:20])
    with pytest.raises(HTTPException) as error:
        with Store(path).connect() as db:
            save_bundle(db,cid,v['id'],ids)
    assert error.value.status_code==413
    with Store(path).connect() as db:
        assert current_bundle(db,cid)==original


def test_contract_type_change_does_not_stale_review_but_party_change_does(setup):
    import json
    from app.materials import is_stale
    c,cid,version,_,path=setup
    with Store(path).connect() as db:
        contract=json.loads(db.execute('SELECT payload FROM contracts WHERE id=?',(cid,)).fetchone()[0])
        version_id=db.execute('SELECT id FROM versions WHERE contract_id=? ORDER BY revision DESC LIMIT 1',(cid,)).fetchone()[0]
        for policy in ('redlines-v7','review-events-v2'):
            saved={'contract_id':cid,'document_version_id':version_id,'review_prompt_version':policy,
                   'context_snapshot':{k:contract[k] for k in ('contract_type','our_party','stage')}}
            changed={**contract,'contract_type':'其他'}
            db.execute('UPDATE contracts SET payload=? WHERE id=?',(json.dumps(changed),cid))
            assert not is_stale(db,saved)
            changed['our_party']='甲方' if contract['our_party']!='甲方' else '乙方'
            db.execute('UPDATE contracts SET payload=? WHERE id=?',(json.dumps(changed),cid))
            assert is_stale(db,saved)
