"""Legacy DOC conversion stays stable across preview, import, retry and versions."""
import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import subprocess
from zipfile import ZipFile
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from app.main import create_app
from app import document_import as importer
from app.parser import parse_docx
from app.store import Store
from test_backend import docx

FIXTURE = Path(__file__).parent/'fixtures/legacy-word.doc'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv('RIXIN_LLM_API_KEY','')
    app=create_app(tmp_path/'doc.sqlite3')
    return TestClient(app), app.state.store


def test_real_doc_preview_import_retry_and_version_upload(client, monkeypatch):
    try: importer.converter_path()
    except HTTPException: pytest.skip('LibreOffice required for real DOC conversion')
    c,store=client
    original=FIXTURE.read_bytes()
    preview=c.post('/api/v1/party-previews',files={'file':('测试合同.DOC',original)})
    assert preview.status_code==200,preview.text
    p=preview.json()
    assert p['filename']=='测试合同.docx' and p['status']=='ready'
    assert [v['name'] for v in p['parties']]==['北京采购有限公司','上海服务有限公司']
    # Subsequent stages must use the persisted bytes, not invoke a second conversion.
    monkeypatch.setattr(importer,'convert_doc',lambda _:pytest.fail('repeated conversion'))
    body={'title':'DOC 导入工程测试','contract_type':'数据服务','our_party':'乙方','stage':'pre_sign','data_purpose':'test',
          'idempotency_key':'doc-retry','start_review':True,'party_selection':{'preview_id':p['id'],'our_index':1,'counterparty_indices':[0]}}
    result=c.post('/api/v1/contracts/import',data={'metadata':json.dumps(body)},files={'file':('测试合同.DOC',original)})
    assert result.status_code==201,result.text
    imported=result.json();v=imported['version']
    assert imported['run']['document_version_id']==v['id']
    assert imported['run']['status']=='queued'
    assert c.get('/api/v1/versions/'+v['id']).status_code==200
    assert v['filename']=='测试合同.docx' and v['sha256']==p['file_sha256']
    again=c.post('/api/v1/contracts/import',data={'metadata':json.dumps(body)},files={'file':('测试合同.DOC',original)})
    assert again.json()==imported
    data=c.get('/api/v1/versions/'+v['id']+'/file').content
    assert data.startswith(b'PK') and sha256(data).hexdigest()==p['file_sha256']
    parsed=parse_docx(data)
    assert any(b.get('table_location') and '10000' in b['text'] for b in parsed['blocks'])
    text='\n'.join(b['text'] for b in parsed['blocks'])
    assert '六十日' in text and '三十日' not in text
    assert parsed['tracked_changes_present']
    with ZipFile(BytesIO(data)) as z:
        assert '请核对付款期限' in z.read('word/comments.xml').decode()
    with store.connect() as db:
        cached=db.execute('SELECT * FROM document_conversions').fetchone()
        assert cached['original']==original and cached['normalized']==data
        stored=json.loads(db.execute('SELECT parsed FROM versions WHERE id=?',(v['id'],)).fetchone()[0])
        assert stored['source_document']['sha256']==sha256(original).hexdigest()
    cid=c.post('/api/v1/contracts',json={'title':'版本上传测试','contract_type':'数据服务','our_party':'乙方','stage':'pre_sign'}).json()['id']
    uploaded=c.post(f'/api/v1/contracts/{cid}/versions',files={'file':('另一个文件名.doc',original)})
    assert uploaded.status_code==201,uploaded.text
    assert uploaded.json()['sha256']==v['sha256'] and uploaded.json()['filename']=='另一个文件名.docx'


def test_unavailable_converter_is_explicit_and_docx_still_works(client,monkeypatch):
    c,store=client
    def unavailable(): raise HTTPException(503,'DOC 转换服务未配置')
    monkeypatch.setattr(importer,'converter_path',unavailable)
    response=c.post('/api/v1/party-previews',files={'file':('合同.doc',FIXTURE.read_bytes())})
    assert response.status_code==503
    good=docx('甲方：北京采购有限公司\n乙方：上海服务有限公司')
    assert c.post('/api/v1/party-previews',files={'file':('合同.docx',good)}).status_code==200
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM document_conversions').fetchone()[0]==0


@pytest.mark.parametrize('name,content,code',[('x.doc',b'not a Word file',422),('x.pdf',b'%PDF',415),('x.docx',b'bad zip',422),('x.doc',b'x'*(20*1024*1024+1),413)])
def test_invalid_upload_cannot_create_contract(client,name,content,code):
    c,_=client
    metadata={'title':'错误文件','contract_type':'数据服务','our_party':'乙方','stage':'pre_sign','party_selection':{'manual_our_name':'我方公司','manual_counterparties':['相对方公司']}}
    r=c.post('/api/v1/contracts/import',data={'metadata':json.dumps(metadata)},files={'file':(name,content)})
    assert r.status_code==code
    assert c.get('/api/v1/contracts?data_purpose=all').json()==[]


def test_conversion_timeout_kills_process_and_leaves_no_cache(tmp_path,monkeypatch):
    store=Store(tmp_path/'timeout.db')
    monkeypatch.setattr(importer,'converter_path',lambda:'/test/soffice')
    killed=[]
    monkeypatch.setattr(importer.os,'killpg',lambda pid,sig:killed.append(pid))
    class Process:
        pid=12345
        def wait(self,timeout=None):
            if timeout is not None: raise subprocess.TimeoutExpired('soffice',timeout)
            return 0
        def kill(self): killed.append(self.pid)
    monkeypatch.setattr(importer.subprocess,'Popen',lambda *a,**k:Process())
    with pytest.raises(HTTPException) as exc:
        importer.normalize_document(store,'合同.doc',FIXTURE.read_bytes())
    assert exc.value.status_code==422 and '超时' in exc.value.detail and killed==[12345]
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM document_conversions').fetchone()[0]==0
