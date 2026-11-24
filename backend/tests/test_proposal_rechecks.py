import json
import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Event
from xml.sax.saxutils import escape

import pytest
from test_proposal_operations import proposal, rewrite_docx, output
from test_onlyoffice import editor, save, callback
from test_backend import docx
from app.parser import parse_docx, namespace_parsed
from app.llm import ExtractionError


def document(paragraphs):
    body=''.join('<w:p><w:r><w:t>'+escape(t)+'</w:t></w:r></w:p>' for t in paragraphs)
    return rewrite_docx(docx(), **{'word/document.xml':lambda x:x[:x.index('<w:body>')]+'<w:body>'+body+'</w:body></w:document>'})


@pytest.fixture
def case(proposal,monkeypatch):
    (c,cid,v,s,app),p=proposal
    from app import onlyoffice
    monkeypatch.setattr(onlyoffice,'send_command',lambda *_:{'error':0})
    content=document(['旧前置','第一版','第二条'])
    parsed=parse_docx(content);namespace_parsed(parsed,v['id'])
    with app.state.store.connect() as db:
        db.execute('UPDATE versions SET content=?,parsed=?,sha256=? WHERE id=?',(content,json.dumps(parsed),sha256(content).hexdigest(),v['id']))
        run=json.loads(db.execute('SELECT payload FROM runs WHERE id="r1"').fetchone()[0])
        run['context_snapshot']=json.loads(db.execute('SELECT payload FROM contracts WHERE id=?',(cid,)).fetchone()[0])
        run['revision_proposals'][0]['anchor']['block_id']=parsed['blocks'][1]['id']
        second={**p,'id':'p2','event_ids':['e2'],'before_text':'第二条','after_text':'第二条修改',
                'anchor':{'block_id':parsed['blocks'][2]['id'],'start':0,'end':3,'quote':'第二条'}}
        run['revision_proposals'].append(second)
        db.execute('UPDATE runs SET payload=? WHERE id="r1"',(json.dumps(run),))
    calls=[]
    def model(settings,name,payload):
        calls.append(payload)
        return [{'proposal_id':p['proposal_id'],'status':'applicable','reason':'当前仍适用','related_refs':[]} for p in payload['proposals']],[]
    monkeypatch.setattr('app.proposal_rechecks.verify_applicability',model)
    return c,cid,v,s,app,calls


def changed(case,monkeypatch,paragraphs,key='manual'):
    c,cid,v,s,app,_=case
    r=save(c,s,key);assert r.status_code==202,r.text
    assert callback(c,s,r.json(),document(paragraphs),monkeypatch).json()=={'error':0}
    head=c.get('/api/v1/contracts/'+cid).json()['current_document_version_id']
    s['head_version_id']=head
    return head


def availability(case):
    return case[0].get('/api/v1/runs/r1/proposal-availability').json()


def recheck(case,version=None,retry=False):
    return case[0].post('/api/v1/runs/r1/proposal-rechecks',json={'expected_version_id':version or case[3]['head_version_id'],'retry':retry})


@pytest.mark.parametrize('paragraphs,index',[
    (['新增','旧前置','第一版','第二条'],2),(['第一版','第二条'],0),
])
def test_relocation_and_recheck_do_not_mutate_review(case,monkeypatch,paragraphs,index):
    c,cid,v,s,app,calls=case
    with app.state.store.connect() as db:original=db.execute('SELECT payload FROM runs WHERE id="r1"').fetchone()[0]
    head=changed(case,monkeypatch,paragraphs)
    a=availability(case)
    assert a['recheck']['status']=='required'
    assert a['proposals']['p1']['modes']==['COMMENT']
    target=a['proposals']['p1']['location']['target']
    assert target['blockId']==c.get('/api/v1/versions/'+head).json()['blocks'][index]['id']
    assert target['documentVersionId']==head
    assert recheck(case,v['id']).status_code==409
    assert calls==[]
    assert recheck(case).json()['status']=='completed'
    assert len(calls)==1
    assert availability(case)['proposals']['p1']['modes']==['ALL','COMMENT','MODIFY']
    assert recheck(case).json()['status']=='completed' and len(calls)==1
    with app.state.store.connect() as db:assert db.execute('SELECT payload FROM runs WHERE id="r1"').fetchone()[0]==original


def test_only_applicable_candidate_is_unlocked(case,monkeypatch):
    changed(case,monkeypatch,['新增','旧前置','第一版','第二条'])
    def model(*args):
        return [{'proposal_id':'p1','status':'applicable','reason':'仍适用','related_refs':[]},
                {'proposal_id':'p2','status':'needs_revision','reason':'关联条件变化','related_refs':['c1']}],[]
    monkeypatch.setattr('app.proposal_rechecks.verify_applicability',model)
    assert recheck(case).json()['status']=='completed'
    a=availability(case)['proposals']
    assert 'MODIFY' in a['p1']['modes'] and a['p2']['modes']==['COMMENT']
    assert '关联条件变化' in a['p2']['reasons']['MODIFY']


def test_changed_or_duplicate_target_is_not_sent_as_safe_candidate(case,monkeypatch):
    changed(case,monkeypatch,['旧前置','第一版已更改','第二条','第二条'])
    assert recheck(case).json()['status']=='completed'
    a=availability(case)['proposals']
    assert a['p1']['modes']==[] and a['p1']['location']['status']=='target_changed'
    assert a['p2']['modes']==[] and a['p2']['location']['status']=='ambiguous_anchor'
    assert case[-1]==[]


def test_new_manual_version_expires_completed_receipt(case,monkeypatch):
    changed(case,monkeypatch,['新增','旧前置','第一版','第二条'])
    assert recheck(case).json()['status']=='completed'
    changed(case,monkeypatch,['新条件','旧前置','第一版','第二条'],'second-manual')
    assert availability(case)['recheck']['status']=='required'
    assert availability(case)['proposals']['p1']['modes']==['COMMENT']


def test_failure_requires_explicit_retry_and_never_unlocks(case,monkeypatch):
    changed(case,monkeypatch,['新增','旧前置','第一版','第二条'])
    count=[]
    def failing(*args):
        count.append(1)
        raise ExtractionError('gateway_timeout','模型超时')
    monkeypatch.setattr('app.proposal_rechecks.verify_applicability',failing)
    assert recheck(case).json()['status']=='failed'
    assert recheck(case).json()['status']=='failed' and len(count)==1
    assert availability(case)['proposals']['p1']['modes']==['COMMENT']
    assert recheck(case,retry=True).json()['status']=='failed' and len(count)==2


@pytest.mark.parametrize('change',['context','materials'])
def test_old_version_material_or_position_change_blocks_recheck(case,monkeypatch,change):
    c,cid,v,s,app,calls=case
    changed(case,monkeypatch,['新增','旧前置','第一版','第二条'])
    with app.state.store.connect() as db:
        if change=='context':
            value=json.loads(db.execute('SELECT payload FROM contracts WHERE id=?',(cid,)).fetchone()[0])
            value['our_party']='甲方';value.pop('our_party_code',None);value.pop('our_party_label',None)
            db.execute('UPDATE contracts SET payload=? WHERE id=?',(json.dumps(value),cid))
        else:
            from app.materials import save_bundle
            save_bundle(db,cid,v['id'],[],assertions=[{'text':'新增商业前提'}])
    assert recheck(case).json()['status']=='blocked'
    assert calls==[] and availability(case)['proposals']['p1']['modes']==[]


def test_running_deduplicates_and_old_attempt_cannot_overwrite_retry(case,monkeypatch):
    changed(case,monkeypatch,['新增','旧前置','第一版','第二条'])
    entered,release=Event(),Event();calls=[]
    def model(*args):
        calls.append(1);first=len(calls)==1
        if first:entered.set();assert release.wait(5)
        return [{'proposal_id':p['proposal_id'],'status':'needs_revision' if first else 'applicable',
                 'reason':'旧结果' if first else '新结果','related_refs':['c1'] if first else []} for p in args[2]['proposals']],[]
    monkeypatch.setattr('app.proposal_rechecks.verify_applicability',model)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first=pool.submit(recheck,case)
        try:
            assert entered.wait(5)
            assert availability(case)['recheck']['status']=='running'
            assert recheck(case,retry=True).json()['status']=='running' and len(calls)==1
            with case[4].state.store.connect() as db:
                row=db.execute('SELECT id,payload FROM proposal_rechecks').fetchone();payload=json.loads(row['payload']);payload['lease_until']=time.time()-1
                db.execute('UPDATE proposal_rechecks SET payload=? WHERE id=?',(json.dumps(payload),row['id']))
            assert recheck(case,retry=True).json()['status']=='completed' and len(calls)==2
        finally:release.set()
        assert first.result().json()['status']=='completed'
    assert availability(case)['proposals']['p1']['recheck']['reason']=='新结果'


@pytest.mark.parametrize('mode',['COMMENT','MODIFY'])
def test_confirmed_operation_preserves_validated_base_without_another_model_call(case,monkeypatch,mode):
    c,cid,v,s,app,calls=case
    head=changed(case,monkeypatch,['新增','旧前置','第一版','第二条'])
    assert recheck(case).json()['status']=='completed'
    response=c.post('/api/v1/runs/r1/proposals/p1/operations',json={'session_id':s['id'],'expected_version_id':head,'mode':mode,'idempotency_key':'comment'})
    assert response.status_code==200,response.text
    op=response.json()
    content=output(op,mode)
    content=rewrite_docx(content,**{'word/document.xml':lambda x:x.replace('<w:body>','<w:body><w:p><w:r><w:t>新增</w:t></w:r></w:p><w:p><w:r><w:t>旧前置</w:t></w:r></w:p>').replace('</w:body>','<w:p><w:r><w:t>第二条</w:t></w:r></w:p></w:body>')})
    r=save(c,s,'comment-save').json();callback(c,s,r,content,monkeypatch)
    response=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id'],'save_request_id':r['id']})
    assert response.status_code==200,response.text
    s['head_version_id']=response.json()['after_version_id']
    assert recheck(case).json()['status']=='completed' and len(calls)==1
    assert 'MODIFY' in availability(case)['proposals']['p1' if mode=='COMMENT' else 'p2']['modes']
