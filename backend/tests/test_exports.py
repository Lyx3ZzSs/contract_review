"""Synthetic contracts: immutable export snapshots and actual changes."""
from io import BytesIO
import json
import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from fastapi.testclient import TestClient
from app.main import create_app
from app.store import Store
from app.export_content import clean, changes


def word(value='7.3 乙方应退还全部费用。', bookmark=None, comment=None, bold=False):
    doc=Document();p=doc.add_paragraph()
    if bookmark:
        start=OxmlElement('w:bookmarkStart');start.set(qn('w:id'),'42');start.set(qn('w:name'),bookmark);p._p.append(start)
    r=p.add_run(value);r.bold=bold
    if bookmark:
        end=OxmlElement('w:bookmarkEnd');end.set(qn('w:id'),'42');p._p.append(end)
    if comment:doc.add_comment(r,comment,author='测试审阅人',initials='T')
    out=BytesIO();doc.save(out);return out.getvalue()


@pytest.fixture
def env(tmp_path):
    store=Store(tmp_path/'exports.db');c=TestClient(create_app(store.path))
    cid=c.post('/api/v1/contracts',json={'title':'导出验证合同','contract_type':'服务','our_party':'乙方','stage':'pre_sign','data_purpose':'test'}).json()['id']
    raw=word();v=c.post(f'/api/v1/contracts/{cid}/versions',files={'file':('验证合同.docx',raw)}).json()
    e={'block_id':v['blocks'][0]['id'],'start':0,'end':len(v['blocks'][0]['text']),'quote':v['blocks'][0]['text']}
    issues=[{'id':'risk1','rule_id':'CR-06','event_id':'event1','title':'退款范围不清','review_category':'transaction','status':'flag','evidence':[e],'explanation':'line001 的退款范围需核对。','review_state':'reviewed','card_content':{'version':'review-card-v1','risk_paragraphs':[{'text':'退款范围需明确。','evidence':[e]}],'modification_plan':'限定退款范围。'}}]
    p={'id':'p1','event_ids':['event1'],'anchor':e,'operation':'replace','document_version_id':v['id'],'before_text':e['quote'],'after_text':'7.3 乙方退还未履行期间费用。','rationale':'限定退款范围','state':'context_required','message':'期限待确认。','basis_refs':[]}
    run={'id':'r1','contract_id':cid,'document_version_id':v['id'],'status':'needs_input','result_schema_version':'interactive-review-v3','issues':issues,'findings':issues,'revision_proposals':[p], 'analysis_artifacts':{'transaction-1':{'sections':[{'title':'交易概况','text':'乙方提供服务，甲方付款。'}]}}}
    with store.connect() as db:db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)',('r1',cid,v['id'],'run','hash','needs_input',json.dumps(run,ensure_ascii=False),'2026-01-01T00:00:00Z'))
    return c,store,cid,v,raw,run


def upload(env,data):
    c,store,cid,*_=env;vid=c.get(f'/api/v1/contracts/{cid}').json()['current_document_version_id']
    r=c.post(f'/api/v1/contracts/{cid}/versions',data={'expected_version_id':vid},files={'file':('验证合同.docx',data)})
    assert r.status_code==201,r.text
    return r.json()


def prepare(env,kind='opinions',vid=None,key='export'):
    c,_,cid,v,*_=env
    return c.post(f'/api/v1/contracts/{cid}/exports',json={'kind':kind,'document_version_id':vid or v['id'],'run_id':'r1','idempotency_key':key})


def snapshot(env,eid):
    with env[1].connect() as db:return json.loads(db.execute('SELECT snapshot FROM document_exports WHERE id=?',(eid,)).fetchone()[0])


def test_current_contract_preserves_bytes_and_filename(env):
    c,_,_,v,raw,_=env;r=prepare(env,'contract');assert r.status_code==201,r.text
    result=r.json();file=c.get(result['download_url']);assert file.content==raw
    assert "filename*=UTF-8''" in file.headers['content-disposition']
    assert result['filename'].startswith('导出验证合同_当前合同_')
    assert prepare(env,'contract').json()['id']==result['id']
    assert prepare(env,'opinions').status_code==409


def test_snapshot_survives_future_edits_decisions_and_retry(env,monkeypatch):
    c,store,cid,v,_,run=env;r=prepare(env).json();frozen=snapshot(env,r['id'])
    upload(env,word('7.3 甲方同意结算全部费用。'))
    with store.connect() as db:db.execute('INSERT INTO decisions(run_id,finding_id,payload,created_at) VALUES(?,?,?,?)',('r1','risk1',json.dumps({'finding_id':'risk1','action':'ignored'}),'now'))
    import app.export_docx as renderer
    original=renderer.generate
    monkeypatch.setattr(renderer,'generate',lambda _:(_ for _ in ()).throw(RuntimeError('temporary')))
    assert c.post(f"/api/v1/exports/{r['id']}/generate").status_code==500
    assert c.get(f"/api/v1/exports/{r['id']}").json()['state']=='failed'
    monkeypatch.setattr(renderer,'generate',original)
    ready=c.post(f"/api/v1/exports/{r['id']}/generate").json();assert ready['state']=='ready'
    assert snapshot(env,r['id'])==frozen
    data=c.get(ready['download_url']).content;text='\n'.join(p.text for p in Document(BytesIO(data)).paragraphs)
    assert '交易概况' in text and '待处理' in text and '期限待确认' in text
    assert '已忽略' not in text and 'line001' not in text
    assert c.post(f"/api/v1/exports/{r['id']}/generate").json()==ready
    assert c.get(ready['download_url']).content==data
    with store.connect() as db:assert db.execute("SELECT status FROM runs WHERE id='r1'").fetchone()[0]=='needs_input'


def test_actual_delta_and_undo(env):
    c,store,cid,v,raw,run=env;assert prepare(env,'changes').status_code==409
    new=upload(env,word('7.3 乙方退还未履行期间费用。'));r=prepare(env,'changes',new['id']).json()
    assert snapshot(env,r['id'])['changes']['modifications'][0]['after']=='7.3 乙方退还未履行期间费用。'
    restored=upload(env,raw);assert prepare(env,'changes',restored['id'],key='undo').status_code==409


def test_comments_only_and_removed_comments(env):
    c,store,cid,v,_,_=env;new=upload(env,word(comment='请确认退款范围。'))
    r=prepare(env,'changes',new['id']).json();delta=snapshot(env,r['id'])['changes']
    assert delta['modifications']==[] and len(delta['comments'])==1
    with store.connect() as db:
        base=dict(db.execute('SELECT * FROM versions WHERE id=?',(new['id'],)).fetchone());original=dict(db.execute('SELECT * FROM versions WHERE id=?',(v['id'],)).fetchone())
    assert len(changes(base,original,[],{})['removed_comments'])==1
    result=c.post(f"/api/v1/exports/{r['id']}/generate");assert result.status_code==200,result.text
    text='\n'.join(p.text for p in Document(BytesIO(c.get(result.json()['download_url']).content)).paragraphs)
    assert '新增或调整批注' in text and '请确认退款范围' in text


def test_format_only_change(env):
    new=upload(env,word(bold=True));r=prepare(env,'changes',new['id']);assert r.status_code==201,r.text
    delta=snapshot(env,r.json()['id'])['changes'];assert not delta['modifications'] and delta['other_changes']


def test_origin_requires_current_bookmark_and_matching_content(env):
    c,store,cid,v,_,run=env;text=run['revision_proposals'][0]['after_text'];new=upload(env,word(text,bookmark='rx_test'))
    op={'id':'op','run_id':'r1','proposal_id':'p1','state':'applied','mode':'MODIFY','bookmark':'rx_test','after_text':text,'expected_blocks':[text]}
    with store.connect() as db:db.execute('INSERT INTO proposal_operations VALUES(?,?,?,?,?,?)',('op',cid,'r1','p1',json.dumps(op),'now'))
    r=prepare(env,'changes',new['id']).json();s=snapshot(env,r['id'])
    assert s['changes']['modifications'][0]['source']=='采用审查建议'
    assert s['report']['revisions'][0]['state']=='正文修订已保存'
    manual=upload(env,word('7.3 乙方退还未履行期间费用，退款时间待确认。',bookmark='rx_test'))
    m=prepare(env,'changes',manual['id'],key='manual').json();s=snapshot(env,m['id'])
    assert s['changes']['modifications'][0]['source']=='采用审查建议并有后续修改'
    assert s['report']['revisions'][0]['state']=='原修改已有变化 待核对'
    unmarked=upload(env,word(text));u=prepare(env,'changes',unmarked['id'],key='unmarked').json()
    assert snapshot(env,u['id'])['changes']['modifications'][0]['source']=='文档修改 来源未关联'


def test_pending_run_only_blocks_full_report(env):
    c,store,cid,v,*_=env
    with store.connect() as db:db.execute("UPDATE runs SET status='running' WHERE id='r1'")
    opts=c.get(f"/api/v1/contracts/{cid}/export-options",params={'document_version_id':v['id'],'run_id':'r1'}).json()
    assert not opts['opinions_available'] and not opts['changes_available']
    assert prepare(env).status_code==409 and prepare(env,'contract').status_code==201


def test_cross_contract_rejected(env):
    c,_,cid,v,*_=env;other=c.post('/api/v1/contracts',json={'title':'另一合同','contract_type':'服务','our_party':'乙方','stage':'pre_sign'}).json()['id']
    r=c.post(f'/api/v1/contracts/{other}/exports',json={'kind':'contract','document_version_id':v['id'],'idempotency_key':'other'})
    assert r.status_code==409
    assert c.get(f'/api/v1/contracts/{other}/export-options',params={'document_version_id':v['id']}).status_code==409


def test_clean_preserves_placeholders():
    assert clean('**期限**<br>【待确认】日；见 `line001`。',{'line001':'第 7.3 条'})=='期限\n【待确认】日；见 第 7.3 条。'
    assert clean('金额 <100 元且利率 >2%。')=='金额 <100 元且利率 >2%。'


def test_comment_application_needs_same_saved_anchor(env):
    c,store,cid,v,_,run=env
    op={'id':'comment-op','run_id':'r1','proposal_id':'p1','state':'applied','mode':'COMMENT','bookmark':'rx_comment','comment':'请核对。'}
    with store.connect() as db:db.execute('INSERT INTO proposal_operations VALUES(?,?,?,?,?,?)',('comment-op',cid,'r1','p1',json.dumps(op),'now'))
    new=upload(env,word(comment='请核对。'))
    r=prepare(env,'opinions',new['id']).json()
    assert snapshot(env,r['id'])['report']['revisions'][0]['state']=='当前未确认应用'
    marked=upload(env,word(bookmark='rx_comment',comment='请核对。'))
    r=prepare(env,'opinions',marked['id'],key='marked').json()
    assert snapshot(env,r['id'])['report']['revisions'][0]['state']=='批注已保存'


def test_shared_revision_once_retracted_excluded(env):
    c,store,cid,v,_,run=env;other={**run['issues'][0],'id':'risk2','event_id':'event2','title':'另一风险'}
    run['issues']+=[other,{**other,'id':'retracted','review_state':'retracted'}];run['revision_proposals'][0]['event_ids']+=['event2']
    with store.connect() as db:db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(run),'r1'))
    r=prepare(env).json();report=snapshot(env,r['id'])['report']
    assert len(report['risks'])==2 and len(report['revisions'])==1 and report['revisions'][0]['risks']==[1,2]
