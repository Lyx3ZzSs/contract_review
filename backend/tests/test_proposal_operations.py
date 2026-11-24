import json
from io import BytesIO
from zipfile import ZipFile, ZipInfo
from xml.sax.saxutils import escape
import pytest
from test_onlyoffice import editor, save, callback
from test_backend import docx

@pytest.fixture
def proposal(editor):
    c,cid,v,s,app=editor
    p={'id':'p1','state':'draft','operation':'replace','document_version_id':v['id'],'before_text':'第一版','after_text':'修改版','anchor':{'block_id':v['blocks'][0]['id'],'start':0,'end':3,'quote':'第一版'},'rationale':'确认交付条件','event_ids':['e'],'basis_refs':[]}
    run={'id':'r1','contract_id':cid,'document_version_id':v['id'],'status':'completed','revision_proposals':[p]}
    with app.state.store.connect() as db:db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)',('r1',cid,v['id'],'r1','hash','completed',json.dumps(run),'2026-01-01'))
    return editor,p

def prepare(c,s,v,mode='ALL',key='one'):
    return c.post('/api/v1/runs/r1/proposals/p1/operations',json={'session_id':s['id'],'expected_version_id':v['id'],'mode':mode,'idempotency_key':key})


def test_other_runs_pending_operation_is_visible_for_recovery(proposal):
    (c,cid,v,s,app),p=proposal
    op=prepare(c,s,v).json()
    with app.state.store.connect() as db:
        run=dict(db.execute('SELECT * FROM runs WHERE id="r1"').fetchone())
        value=json.loads(run['payload']);value['id']='r2'
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)',('r2',cid,v['id'],'r2',run['request_hash'],'completed',json.dumps(value),run['created_at']))
    availability=c.get('/api/v1/runs/r2/proposal-availability').json()
    assert availability['eligible']==[]
    assert availability['blocking_operation']['id']==op['id']
    assert availability['blocking_operation']['run_id']=='r1'
    assert 'request' not in availability['blocking_operation']

def output(op,mode='ALL',wrong=False):
    w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    deleted='' if mode=='COMMENT' else '<w:del w:id="1"><w:r><w:delText>第一版</w:delText></w:r></w:del>'
    content='<w:r><w:t>第一版</w:t></w:r>' if mode=='COMMENT' else '<w:ins w:id="2"><w:r><w:t>'+('错误版' if wrong else '修改版')+'</w:t></w:r></w:ins>'
    if mode!='MODIFY':content='<w:commentRangeStart w:id="0"/>'+content+'<w:commentRangeEnd w:id="0"/>'
    content=deleted+'<w:bookmarkStart w:id="1" w:name="'+op['bookmark']+'"/>'+content+'<w:bookmarkEnd w:id="1"/>'
    stream=BytesIO()
    with ZipFile(stream,'w') as z:
        z.writestr(ZipInfo('word/document.xml'),f'<w:document xmlns:w="{w}"><w:body><w:p>{content}</w:p></w:body></w:document>')
        if mode!='MODIFY':
            paragraphs=''.join('<w:p><w:r><w:t>'+escape(line)+'</w:t></w:r></w:p>' for line in op['comment'].split('\n'))
            z.writestr(ZipInfo('word/comments.xml'),f'<w:comments xmlns:w="{w}"><w:comment w:id="0">{paragraphs}</w:comment></w:comments>')
    return stream.getvalue()


def test_clause_finding_decisions_and_comments_are_independent_of_replacement_proposals(proposal, monkeypatch):
    (c,cid,v,s,app),p = proposal
    issue = dict(id='i1',rule_id='VL-01',status='insufficient_evidence',execution_mode='liability_clause',
                 event_anchor=p['anchor'],evidence=[p['anchor']],explanation='核对本条责任',
                 presentation={'next_step':'核对计费方式。'})
    other_anchor = {**p['anchor'],'start':1,'quote':'一版'}
    other = {**issue,'id':'i2','event_anchor':other_anchor,'evidence':[other_anchor],
             'explanation':'核对另一条责任'}
    with app.state.store.connect() as db:
        value=json.loads(db.execute('SELECT payload FROM runs WHERE id="r1"').fetchone()[0])
        value.update(issues=[issue,other],findings=[issue,other],revision_proposals=[])
        db.execute('UPDATE runs SET payload=? WHERE id="r1"',(json.dumps(value),))
    selected = c.post('/api/v1/runs/r1/issues/i1/decisions',json={'action':'acknowledged','note':'已核对本项'})
    assert selected.status_code==201
    with app.state.store.connect() as db:
        assert [row[0] for row in db.execute('SELECT finding_id FROM decisions WHERE run_id="r1"')]==['i1']

    def apply(mode):
        return c.post('/api/v1/runs/r1/proposals/i1/operations',json={'session_id':s['id'],
            'expected_version_id':v['id'],'idempotency_key':mode,'mode':mode})

    before = c.get('/api/v1/runs/r1/proposal-availability').json()['proposals']
    assert before['i1']['modes']==before['i2']['modes']==['COMMENT']
    assert before['i1']['manual_revision_reason']==''
    assert apply('MODIFY').status_code==409
    res = apply('COMMENT')
    assert res.status_code==200,res.text
    op=res.json()
    assert op['target']['quote']=='第一版' and op['expected_blocks']==['第一版']
    assert op['comment']=='核对本条责任 核对计费方式。'
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    receipt=save(c,s).json()
    callback(c,s,receipt,output(op,'COMMENT'),monkeypatch)
    done=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id'],'save_request_id':receipt['id']})
    assert done.status_code==200,done.text
    assert done.json()['state']=='applied'
    remaining=c.get('/api/v1/runs/r1/proposal-availability').json()['proposals']
    assert remaining['i1']['completed']=={'comment':True,'revision':False}
    assert remaining['i2']['modes']==['COMMENT']
    assert remaining['i2']['location']['target']['quote']=='一版'

def test_manually_confirmed_clause_replacement_uses_the_verified_write_path(proposal, monkeypatch):
    (c,_,v,s,app),p=proposal
    issue=dict(id='i1',execution_mode='liability_clause',event_anchor=p['anchor'],
               evidence=[p['anchor']],explanation='核对交付条件')
    with app.state.store.connect() as db:
        value=json.loads(db.execute('SELECT payload FROM runs WHERE id="r1"').fetchone()[0])
        value.update(issues=[issue],findings=[issue],revision_proposals=[])
        db.execute('UPDATE runs SET payload=? WHERE id="r1"',(json.dumps(value),))
    path='/api/v1/runs/r1/proposals/i1/operations'
    request={'session_id':s['id'],'expected_version_id':v['id'],'mode':'MODIFY','idempotency_key':'manual'}
    assert c.post(path,json=request).status_code==409
    assert c.post(path,json={**request,'manual_replacement':'第一版'}).status_code==422
    accepted={**request,'manual_replacement':'修改版'}
    assert c.post(path,json={**accepted,'mode':'ALL'}).status_code==409
    res=c.post(path,json=accepted)
    assert res.status_code==200,res.text
    op=res.json()
    assert op['target']['quote']=='第一版' and op['expected_blocks']==['修改版']
    assert op['after_text']=='修改版' and op['mode']=='MODIFY'
    assert c.post(path,json=accepted).json()['id']==op['id']
    assert c.post(path,json={**request,'manual_replacement':'另一版本'}).status_code==409

    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    receipt=save(c,s).json()
    callback(c,s,receipt,output(op,'MODIFY'),monkeypatch)
    done=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id'],'save_request_id':receipt['id']})
    assert done.status_code==200,done.text
    assert done.json()['state']=='applied'
    after=c.get('/api/v1/runs/r1/proposal-availability').json()['proposals']['i1']
    assert after['completed']=={'comment':False,'revision':True}
    assert after['modes']==['COMMENT']
    assert after['location']['target']['quote']=='修改版'


@pytest.mark.parametrize('mode',['ALL','COMMENT','MODIFY'])
def test_saved_list_target_uses_source_offsets_after_hidden_prefix_tabs(mode):
    from app.parser import parse_docx
    from app.proposal_operations import verify_saved
    from fastapi import HTTPException
    def prefixed(data,inside_bookmark=False):
        result=BytesIO()
        with ZipFile(BytesIO(data)) as src, ZipFile(result,'w') as dst:
            for name in src.namelist():
                value=src.read(name)
                if name=='word/document.xml':
                    xml=value.decode()
                    marker='<w:bookmarkStart w:id="1" w:name="'+op['bookmark']+'"/>' if inside_bookmark else '<w:p>'
                    xml=xml.replace(marker,marker+'<w:r><w:tab/><w:tab/></w:r>',1)
                    value=xml.encode()
                dst.writestr(name,value)
        return result.getvalue()
    op={'mode':mode,'bookmark':'rx_'+'a'*32,'comment':'确认验收程序','after_text':'修改版',
        'target':{'blockId':'v:p1','blocks':[{'id':'v:p1','text':'\t\t第一版'}],
                  'paragraph':'\t\t第一版','quote':'第一版','start':2,'end':5},
        'expected_blocks':['\t\t'+('第一版' if mode=='COMMENT' else '修改版')]}
    before={'content':prefixed(docx('第一版'))}
    saved=prefixed(output(op,mode))
    assert verify_saved(before,{'content':saved,'parsed':json.dumps(parse_docx(saved))},op)['bookmark']==op['bookmark']
    # Native offset 0 is not the saved DOCX offset 2. Even with identical full
    # proposed text, a bookmark that swallows the tabs cannot confirm the write.
    misplaced=prefixed(output(op,mode),inside_bookmark=True)
    with pytest.raises(HTTPException,match='文档标记'):
        verify_saved(before,{'content':misplaced,'parsed':json.dumps(parse_docx(misplaced))},op)

@pytest.mark.parametrize('mode',['ALL','COMMENT','MODIFY'])
@pytest.mark.parametrize('state',['draft','context_required'])
def test_confirm_requires_saved_docx_and_undo_restores_exact_bytes(proposal,monkeypatch,mode,state):
    (c,cid,v,s,app),p=proposal
    with app.state.store.connect() as db:
        value=json.loads(db.execute('SELECT payload FROM runs WHERE id="r1"').fetchone()[0])
        value['revision_proposals'][0].update(state=state,message='责任上限待协商')
        db.execute('UPDATE runs SET payload=? WHERE id="r1"',(json.dumps(value),))
    assert c.get('/api/v1/runs/r1/proposal-availability').json()['proposals']['p1']['modes']==['ALL','COMMENT','MODIFY']
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    result=prepare(c,s,v,mode);assert result.status_code==200,result.text
    op=result.json()
    if state=='context_required':assert '责任上限待协商' in op['comment']
    assert prepare(c,s,v,mode).json()['id']==op['id']
    assert prepare(c,s,v,mode,key='duplicate').status_code==409
    assert c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id'],'save_request_id':'none'}).status_code==409
    r=save(c,s).json();callback(c,s,r,output(op,mode),monkeypatch)
    done=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id'],'save_request_id':r['id']})
    assert done.status_code==200,done.text
    assert done.json()['state']=='applied'
    with app.state.store.connect() as db:
        assert json.loads(db.execute('SELECT payload FROM runs WHERE id="r1"').fetchone()[0])['revision_proposals'][0]['state']==state
    assert c.get('/api/v1/runs/r1/proposal-operations').json()[0]['can_undo']
    undone=c.post('/api/v1/proposal-operations/'+op['id']+'/undo',json={'session_id':s['id'],'expected_version_id':done.json()['after_version_id']})
    assert undone.status_code==200,undone.text
    blob=c.get('/api/v1/versions/'+undone.json()['reverted_version_id']+'/file').content
    assert blob==docx('第一版')
    # Closed document keys cannot overwrite the restoration with a late callback.
    callback(c,s,{**r,'id':'late'},output(op,mode),monkeypatch)
    assert c.get('/api/v1/contracts/'+cid).json()['current_document_version_id']==undone.json()['reverted_version_id']

def test_wrong_saved_text_never_marks_applied(proposal,monkeypatch):
    (c,cid,v,s,app),p=proposal
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    op=prepare(c,s,v).json();r=save(c,s).json();callback(c,s,r,output(op,wrong=True),monkeypatch)
    assert c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id'],'save_request_id':r['id']}).status_code==409
    assert c.get('/api/v1/runs/r1/proposal-operations').json()[0]['state']=='prepared'

def test_missing_native_marks_never_marks_applied(proposal,monkeypatch):
    (c,cid,v,s,app),p=proposal
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    op=prepare(c,s,v).json();r=save(c,s).json();callback(c,s,r,docx('修改版'),monkeypatch)
    assert c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id'],'save_request_id':r['id']}).status_code==409

def test_manual_edit_blocks_apply_and_undo(proposal,monkeypatch):
    (c,cid,v,s,app),p=proposal
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    op=prepare(c,s,v).json();r=save(c,s).json();callback(c,s,r,output(op),monkeypatch)
    done=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id'],'save_request_id':r['id']}).json()
    s['head_version_id']=done['after_version_id'];r=save(c,s,'manual').json();callback(c,s,r,docx('人工修改'),monkeypatch)
    head=c.get('/api/v1/contracts/'+cid).json()['current_document_version_id']
    assert c.post('/api/v1/proposal-operations/'+op['id']+'/undo',json={'session_id':s['id'],'expected_version_id':head}).status_code==409
    with app.state.store.connect() as db:db.execute('UPDATE proposal_operations SET payload=? WHERE id=?',(json.dumps({**op,'state':'cancelled'}),op['id']))
    assert prepare(c,s,{'id':head},key='again').status_code==409

@pytest.mark.parametrize('change',[{'state':'conflict'},{'operation':'insert','before_text':'','anchor':{'block_id':'wrong','quote':'错误地址','start':0,'end':4}},{'document_version_id':'other'},{'anchor':{'block_id':'wrong','start':0,'end':3,'quote':'第一版'}}])
def test_unverified_or_mismatched_proposals_are_rejected(proposal,change):
    (c,cid,v,s,app),p=proposal
    with app.state.store.connect() as db:
        value=json.loads(db.execute('SELECT payload FROM runs WHERE id="r1"').fetchone()[0]);value['revision_proposals'][0].update(change);db.execute('UPDATE runs SET payload=? WHERE id="r1"',(json.dumps(value),))
    assert prepare(c,s,v).status_code==409
    assert c.get('/api/v1/runs/r1/proposal-operations').json()==[]

def test_finished_review_required_and_readonly_session_rejected(proposal):
    (c,cid,v,s,app),p=proposal
    with app.state.store.connect() as db:db.execute('UPDATE runs SET status="running" WHERE id="r1"')
    assert prepare(c,s,v).status_code==409
    with app.state.store.connect() as db:
        db.execute('UPDATE runs SET status="completed" WHERE id="r1"');db.execute('UPDATE editor_sessions SET state="view" WHERE id=?',(s['id'],))
    assert prepare(c,s,v).status_code==409

def test_partial_saved_operation_can_restore_without_marking_success(proposal,monkeypatch):
    (c,cid,v,s,app),p=proposal
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    op=prepare(c,s,v).json();r=save(c,s).json();callback(c,s,r,output(op,mode='MODIFY'),monkeypatch)
    response=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id']});assert response.status_code==409
    head=c.get('/api/v1/contracts/'+cid).json()['current_document_version_id']
    undo=c.post('/api/v1/proposal-operations/'+op['id']+'/undo',json={'session_id':s['id'],'expected_version_id':head});assert undo.status_code==200,undo.text
    assert c.get('/api/v1/versions/'+undo.json()['reverted_version_id']+'/file').content==docx('第一版')
    assert c.get('/api/v1/runs/r1/proposal-availability').json()['eligible']==['p1']

def test_lost_confirmation_response_can_be_recovered_from_save_receipt(proposal,monkeypatch):
    (c,cid,v,s,app),p=proposal
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    op=prepare(c,s,v).json();r=save(c,s).json();callback(c,s,r,output(op),monkeypatch)
    done=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id'],'save_request_id':'initial'})
    assert done.status_code==200,done.text
    assert done.json()['state']=='applied'
    assert c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id'],'save_request_id':r['id']}).json()==done.json()

@pytest.mark.parametrize('state,errors',[
    ('conflict',[]),
    ('context_required',[{'module':'revision-verification','code':'gateway_timeout'}]),
])
def test_unverified_text_can_be_commented_but_not_applied(proposal,state,errors):
    (c,cid,v,s,app),p=proposal
    with app.state.store.connect() as db:
        value=json.loads(db.execute('SELECT payload FROM runs WHERE id="r1"').fetchone()[0])
        value['revision_proposals'][0].update(state=state,message='修改需核对')
        value['module_errors']=errors
        db.execute('UPDATE runs SET payload=? WHERE id="r1"',(json.dumps(value),))
    availability=c.get('/api/v1/runs/r1/proposal-availability').json()['proposals']['p1']
    assert availability['modes']==['COMMENT']
    for mode in ['ALL','MODIFY']:
        response=prepare(c,s,v,mode)
        assert response.status_code==409
        assert response.json()['detail']==availability['reasons'][mode]
    assert prepare(c,s,v,'COMMENT').status_code==200

@pytest.mark.parametrize('change',[
    {'state':'invalid'},
    {'anchor':{'block_id':'wrong','start':0,'end':3,'quote':'第一版'}},
    {'anchor':{'block_id':None,'start':0,'end':3,'quote':'第一版'}},
    {'before_text':'其他文本'},
    {'document_version_id':'wrong'},
])
def test_availability_matches_write_rejection_for_all_modes(proposal,change):
    (c,cid,v,s,app),p=proposal
    with app.state.store.connect() as db:
        value=json.loads(db.execute('SELECT payload FROM runs WHERE id="r1"').fetchone()[0])
        value['revision_proposals'][0].update(change)
        db.execute('UPDATE runs SET payload=? WHERE id="r1"',(json.dumps(value),))
    availability=c.get('/api/v1/runs/r1/proposal-availability').json()
    assert availability['eligible']==[]
    assert availability['proposals']['p1']['modes']==[]
    for mode in ['ALL','COMMENT','MODIFY']:assert prepare(c,s,v,mode).status_code==409


def test_placeholder_draft_is_actionable_without_becoming_confirmed_policy(proposal):
    (c,cid,v,s,app),p=proposal
    with app.state.store.connect() as db:
        value=json.loads(db.execute('SELECT payload FROM runs WHERE id="r1"').fetchone()[0])
        value['revision_proposals'][0].update(state='context_required',after_text='期限【待确认】年',message='期限需双方协商')
        db.execute('UPDATE runs SET payload=? WHERE id="r1"',(json.dumps(value),))
    assert c.get('/api/v1/runs/r1/proposal-availability').json()['proposals']['p1']['modes']==['ALL','COMMENT','MODIFY']
    response=prepare(c,s,v,'ALL');assert response.status_code==200
    assert response.json()['after_text']=='期限【待确认】年'
    assert '期限需双方协商' in response.json()['comment']


def rewrite_docx(data, **parts):
    """Alter one OOXML part while retaining the rest of the package."""
    result=BytesIO()
    with ZipFile(BytesIO(data)) as source, ZipFile(result,'w') as dest:
        for name in source.namelist():
            value=source.read(name).decode()
            dest.writestr(name,parts.get(name,lambda text:text)(value))
    return result.getvalue()


def confirm_saved(c,s,op,data,monkeypatch,key):
    receipt=save(c,s,key)
    assert receipt.status_code==202,receipt.text
    callback(c,s,receipt.json(),data,monkeypatch)
    response=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id'],'save_request_id':receipt.json()['id']})
    assert response.status_code==200,response.text
    s['head_version_id']=response.json()['after_version_id']
    return response.json()


@pytest.mark.parametrize('first,second',[('COMMENT','MODIFY'),('COMMENT','ALL'),('MODIFY','COMMENT'),('MODIFY','ALL')])
def test_sequential_actions_only_complete_missing_components(proposal,monkeypatch,first,second):
    (c,cid,v,s,app),p=proposal
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    first_op=prepare(c,s,v,first).json()
    first_bytes=output(first_op,first)
    first_done=confirm_saved(c,s,first_op,first_bytes,monkeypatch,'first-save')
    state=c.get('/api/v1/runs/r1/proposal-availability').json()['proposals']['p1']
    assert state['completed']=={'comment':first=='COMMENT','revision':first=='MODIFY'}
    assert first not in state['modes']
    assert second in state['modes']
    response=prepare(c,s,{'id':s['head_version_id']},second,'second')
    assert response.status_code==200,response.text
    second_op=response.json()
    assert second_op['requested_mode']==second
    assert second_op['mode']==('ALL' if first=='COMMENT' else 'COMMENT')
    assert second_op['continuation']['bookmark']==first_op['bookmark']
    if first=='MODIFY':
        assert second_op['target']['quote']=='修改版'
    # Both sequences result in one revision and one comment. For MODIFY→COMMENT,
    # the earlier tracked edit and bookmark remain; only the new comment is added.
    second_bytes=output(second_op,'ALL')
    if first=='MODIFY':
        second_bytes=rewrite_docx(second_bytes,**{'word/document.xml':lambda x:x.replace('<w:ins w:id="2">','<w:bookmarkStart w:id="8" w:name="'+first_op['bookmark']+'"/><w:ins w:id="2">').replace('</w:ins>','</w:ins><w:bookmarkEnd w:id="8"/>')})
    second_done=confirm_saved(c,s,second_op,second_bytes,monkeypatch,'second-save')
    state=c.get('/api/v1/runs/r1/proposal-availability').json()['proposals']['p1']
    assert state['completed']=={'comment':True,'revision':True}
    assert state['modes']==[]
    assert prepare(c,s,{'id':s['head_version_id']},'ALL','third').status_code==409
    from defusedxml import ElementTree as ET
    from app.parser import W
    with ZipFile(BytesIO(second_bytes)) as z:
        assert len(list(ET.fromstring(z.read('word/document.xml')).iter(W+'ins')))==1
        assert len(list(ET.fromstring(z.read('word/comments.xml')).iter(W+'comment')))==1
    # Undo only the second step: the earlier action remains in both bytes and UI.
    undo=c.post('/api/v1/proposal-operations/'+second_op['id']+'/undo',json={'session_id':s['id'],'expected_version_id':second_done['after_version_id']})
    assert undo.status_code==200,undo.text
    assert c.get('/api/v1/versions/'+undo.json()['reverted_version_id']+'/file').content==first_bytes
    state=c.get('/api/v1/runs/r1/proposal-availability').json()['proposals']['p1']
    assert state['completed']=={'comment':first=='COMMENT','revision':first=='MODIFY'}
    operations=c.get('/api/v1/runs/r1/proposal-operations').json()
    assert next(o for o in operations if o['id']==first_op['id'])['can_undo'] is True


def test_new_writable_session_recovers_saved_operation(proposal,monkeypatch):
    (c,cid,v,s,app),p=proposal
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    op=prepare(c,s,v).json()
    r=save(c,s).json();callback(c,s,r,output(op),monkeypatch)
    head=c.get('/api/v1/contracts/'+cid).json()['current_document_version_id']
    assert c.post('/api/v1/editor-sessions/'+s['id']+'/close',json={'document_version_id':head}).status_code==200
    new=c.post(f'/api/v1/contracts/{cid}/editor-sessions',json={'expected_version_id':head,'client_instance_id':'reopen','idempotency_key':'reopen'}).json()
    assert new['state']=='open'
    response=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':new['id']})
    assert response.status_code==200,response.text
    assert response.json()['state']=='applied'
    assert response.json()['after_version_id']==head
    assert len(c.get('/api/v1/contracts/'+cid).json()['versions'])==2


@pytest.mark.parametrize('tamper', ['bookmark_elsewhere','comment_elsewhere','wrong_deleted_text','unrelated_revision'])
def test_saved_proof_must_belong_to_this_target(proposal,monkeypatch,tamper):
    (c,cid,v,s,app),p=proposal
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    op=prepare(c,s,v).json()
    data=output(op)
    def corrupt(xml):
        if tamper=='bookmark_elsewhere':
            marker='<w:bookmarkStart w:id="1" w:name="'+op['bookmark']+'"/>'
            return xml.replace(marker,'').replace('<w:bookmarkEnd w:id="1"/>','').replace('<w:body>','<w:body>'+marker+'<w:bookmarkEnd w:id="1"/>')
        if tamper=='comment_elsewhere':
            return xml.replace('<w:commentRangeStart w:id="0"/>','').replace('<w:commentRangeEnd w:id="0"/>','').replace('<w:body>','<w:body><w:commentRangeStart w:id="0"/><w:commentRangeEnd w:id="0"/>')
        if tamper=='wrong_deleted_text':return xml.replace('<w:delText>第一版</w:delText>','<w:delText>无关旧文</w:delText>')
        return xml.replace('<w:ins w:id="2"><w:r><w:t>修改版</w:t></w:r></w:ins>','<w:r><w:t>修改版</w:t></w:r>').replace('<w:body>','<w:body><w:ins w:id="2"><w:r><w:t></w:t></w:r></w:ins>')
    data=rewrite_docx(data,**{'word/document.xml':corrupt})
    r=save(c,s).json();callback(c,s,r,data,monkeypatch)
    response=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id'],'save_request_id':r['id']})
    assert response.status_code==409,response.text
    persisted=c.get('/api/v1/runs/r1/proposal-operations').json()[0]
    assert persisted['state']=='prepared'
    assert persisted['phase']=='saved_unverified'
    assert persisted['verification_error']


def test_viewer_cannot_recover_another_open_writers_operation(proposal,monkeypatch):
    (c,cid,v,s,app),p=proposal
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    op=prepare(c,s,v).json()
    r=save(c,s).json();callback(c,s,r,output(op),monkeypatch)
    head=c.get('/api/v1/contracts/'+cid).json()['current_document_version_id']
    viewer=c.post(f'/api/v1/contracts/{cid}/editor-sessions',json={'expected_version_id':head,'client_instance_id':'viewer','idempotency_key':'viewer'}).json()
    assert viewer['state']=='view'
    response=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':viewer['id']})
    assert response.status_code==409
    assert c.get('/api/v1/runs/r1/proposal-operations').json()[0]['state']=='prepared'


def reopen_session(c,cid,s,head):
    assert c.post('/api/v1/editor-sessions/'+s['id']+'/close',json={'document_version_id':head}).status_code==200
    response=c.post(f'/api/v1/contracts/{cid}/editor-sessions',json={'expected_version_id':head,'client_instance_id':'recovery','idempotency_key':'recovery'})
    assert response.status_code==201,response.text
    return response.json()


def test_closed_session_without_write_releases_pending_operation(proposal):
    (c,cid,v,s,app),p=proposal
    op=prepare(c,s,v).json()
    new=reopen_session(c,cid,s,v['id'])
    response=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':new['id']})
    assert response.status_code==200,response.text
    assert response.json()['state']=='cancelled'
    assert prepare(c,new,v,key='retry').status_code==200


def test_prepare_alone_cannot_prove_no_write_in_live_editor(proposal):
    (c,cid,v,s,app),p=proposal
    op=prepare(c,s,v).json()
    response=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id']})
    assert response.status_code==409
    assert c.get('/api/v1/runs/r1/proposal-operations').json()[0]['state']=='prepared'
    cancelled=c.post('/api/v1/proposal-operations/'+op['id']+'/cancel',json={})
    assert cancelled.status_code==422


def test_post_prepare_unchanged_saved_bytes_can_cancel(proposal,monkeypatch):
    (c,cid,v,s,app),p=proposal
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    op=prepare(c,s,v).json()
    receipt=save(c,s).json();callback(c,s,receipt,docx('第一版'),monkeypatch)
    response=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':s['id'],'save_request_id':receipt['id']})
    assert response.status_code==200,response.text
    assert response.json()['state']=='cancelled'


def test_foreign_contract_session_cannot_confirm_operation(proposal,monkeypatch):
    (c,cid,v,s,app),p=proposal
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    op=prepare(c,s,v).json()
    receipt=save(c,s).json();callback(c,s,receipt,output(op),monkeypatch)
    foreign=c.post('/api/v1/contracts',json={'title':'另一合同','contract_type':'数据服务','our_party':'乙方','stage':'pre_sign','data_purpose':'test'}).json()['id']
    version=c.post(f'/api/v1/contracts/{foreign}/versions',files={'file':('other.docx',docx('其他合同'))}).json()
    other=c.post(f'/api/v1/contracts/{foreign}/editor-sessions',json={'expected_version_id':version['id'],'client_instance_id':'other','idempotency_key':'other'}).json()
    response=c.post('/api/v1/proposal-operations/'+op['id']+'/confirm',json={'session_id':other['id']})
    assert response.status_code==409
    assert c.get('/api/v1/runs/r1/proposal-operations').json()[0]['state']=='prepared'
    cancelled=c.post('/api/v1/proposal-operations/'+op['id']+'/cancel',json={'session_id':other['id'],'expected_version_id':v['id'],'editor_result':'absent'})
    assert cancelled.status_code==409


def test_existing_comment_cannot_masquerade_as_new_comment(proposal):
    (c,cid,v,s,app),p=proposal
    op=prepare(c,s,v,'COMMENT').json()
    from app.proposal_document import verify_document
    from fastapi import HTTPException
    # Same comment and range already existed before; adding only the operation
    # bookmark does not prove AddComment executed.
    after=output(op,'COMMENT')
    before=rewrite_docx(after,**{'word/document.xml':lambda xml:xml.replace('<w:bookmarkStart w:id="1" w:name="'+op['bookmark']+'"/>','').replace('<w:bookmarkEnd w:id="1"/>','')})
    with pytest.raises(HTTPException,match='新增批注未完整保存'):
        verify_document(before,after,op)


def with_existing_comment(data, ident, comment='原有批注', author='同事'):
    """Synthetic old comment on a different paragraph; IDs may change on save."""
    paragraph=f'<w:p><w:commentRangeStart w:id="{ident}"/><w:r><w:t>其他条款</w:t></w:r><w:commentRangeEnd w:id="{ident}"/></w:p>'
    node=f'<w:comment w:id="{ident}" w:author="{author}"><w:p><w:r><w:t>{escape(comment)}</w:t></w:r></w:p></w:comment>'
    result=BytesIO()
    with ZipFile(BytesIO(data)) as source, ZipFile(result,'w') as dest:
        for name in source.namelist():
            value=source.read(name).decode()
            if name=='word/document.xml':value=value.replace('</w:body>',paragraph+'</w:body>')
            if name=='word/comments.xml':value=value.replace('</w:comments>',node+'</w:comments>')
            dest.writestr(name,value)
        if 'word/comments.xml' not in source.namelist():
            dest.writestr('word/comments.xml','<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'+node+'</w:comments>')
    return result.getvalue()


@pytest.mark.parametrize('mode',['ALL','COMMENT'])
def test_new_comment_may_reuse_old_id_after_save(proposal,mode):
    from app.proposal_document import verify_document
    (c,cid,v,s,app),p=proposal
    op=prepare(c,s,v,mode).json()
    # Real failure pattern: old 0 becomes 1; newly inserted comment becomes 0.
    before=with_existing_comment(docx('第一版'),'0')
    after=with_existing_comment(output(op,mode),'1')
    assert verify_document(before,after,op)['comment_id']=='0'


@pytest.mark.parametrize('tamper',['drop_old','change_old_text','change_old_author','truncate_new','wrong_range','duplicate_target'])
def test_renumbered_comment_still_requires_complete_unique_saved_proof(proposal,tamper):
    from app.proposal_document import verify_document
    from fastapi import HTTPException
    (c,cid,v,s,app),p=proposal
    op=prepare(c,s,v).json()
    before=with_existing_comment(docx('第一版'),'0')
    after=with_existing_comment(output(op),'1')
    if tamper=='drop_old':after=output(op)
    elif tamper=='change_old_text':after=with_existing_comment(output(op),'1',comment='被修改的批注')
    elif tamper=='change_old_author':after=with_existing_comment(output(op),'1',author='另一作者')
    elif tamper=='truncate_new':
        after=rewrite_docx(after,**{'word/comments.xml':lambda xml:xml.replace(escape(op['comment']),escape(op['comment'][:-1]))})
    elif tamper=='wrong_range':
        after=rewrite_docx(after,**{'word/document.xml':lambda xml:xml.replace('<w:commentRangeEnd w:id="0"/>','').replace('<w:commentRangeStart w:id="0"/>','<w:commentRangeStart w:id="0"/><w:commentRangeEnd w:id="0"/>')})
    else:
        after=rewrite_docx(after,**{
            'word/document.xml':lambda xml:xml.replace('<w:commentRangeStart w:id="0"/>','<w:commentRangeStart w:id="0"/><w:commentRangeStart w:id="2"/>').replace('<w:commentRangeEnd w:id="0"/>','<w:commentRangeEnd w:id="0"/><w:commentRangeEnd w:id="2"/>'),
            'word/comments.xml':lambda xml:xml.replace('</w:comments>','<w:comment w:id="2"><w:p><w:r><w:t>'+escape(op['comment'])+'</w:t></w:r></w:p></w:comment></w:comments>'),
        })
    with pytest.raises(HTTPException) as failure:
        verify_document(before,after,op)
    assert failure.value.status_code==409


@pytest.mark.parametrize('editor_result',['absent','rejected'])
def test_explicit_editor_no_write_receipt_releases_pending_operation(proposal,editor_result):
    (c,cid,v,s,app),p=proposal
    op=prepare(c,s,v).json()
    url='/api/v1/proposal-operations/'+op['id']+'/cancel'
    payload={'session_id':s['id'],'expected_version_id':v['id'],'editor_result':editor_result}
    assert c.post(url,json={**payload,'expected_version_id':'stale'}).status_code==409
    assert c.post(url,json={**payload,'editor_result':'uncertain'}).status_code==422
    response=c.post(url,json=payload)
    assert response.status_code==200,response.text
    assert response.json()['state']=='cancelled'
    assert prepare(c,s,v,key='retry').status_code==200


@pytest.mark.parametrize('position',['end','middle'])
def test_deletion_serialization_must_border_the_replacement(proposal,position):
    (c,cid,v,s,app),p=proposal
    from app.proposal_document import verify_document
    from fastapi import HTTPException
    op=prepare(c,s,v,'MODIFY').json()
    deleted='<w:del w:id="1"><w:r><w:delText>第一版</w:delText></w:r></w:del>'
    def move_deleted(xml):
        xml=xml.replace(deleted,'')
        if position=='end':return xml.replace('</w:ins>','</w:ins>'+deleted)
        return xml.replace('<w:r><w:t>修改版</w:t></w:r>','<w:r><w:t>修</w:t></w:r>'+deleted+'<w:r><w:t>改版</w:t></w:r>')
    after=rewrite_docx(output(op,'MODIFY'),**{'word/document.xml':move_deleted})
    if position=='end':
        assert verify_document(docx('第一版'),after,op)['bookmark']==op['bookmark']
    else:
        with pytest.raises(HTTPException,match='新增修订与本次替换不一致'):
            verify_document(docx('第一版'),after,op)


@pytest.mark.parametrize('tamper',['drop_other','change_author'])
def test_comment_migration_preserves_other_comments_and_attribution(proposal,tamper):
    (c,cid,v,s,app),p=proposal
    from app.proposal_document import verify_document
    from fastapi import HTTPException
    op=prepare(c,s,v).json()
    op['continuation']={'mode':'COMMENT','comment_id':'0'}
    other='<w:comment w:id="9" w:author="同事"><w:p><w:r><w:t>其他审阅意见</w:t></w:r></w:p></w:comment>'
    def with_authors(xml):
        return xml.replace('<w:comment w:id="0">','<w:comment w:id="0" w:author="法务审阅员">').replace('</w:comments>',other+'</w:comments>')
    before=rewrite_docx(output(op,'COMMENT'),**{'word/comments.xml':with_authors})
    after=rewrite_docx(output(op),**{'word/comments.xml':with_authors})
    assert verify_document(before,after,op)['comment_id']=='0'
    change=(lambda xml:xml.replace(other,'')) if tamper=='drop_other' else (lambda xml:xml.replace('w:author="法务审阅员"','w:author="另一作者"'))
    corrupt=rewrite_docx(after,**{'word/comments.xml':change})
    with pytest.raises(HTTPException,match='原有批注内容或作者发生变化'):
        verify_document(before,corrupt,op)


@pytest.mark.parametrize('change',['renumber','drop_empty','split_runs','deleted_text','author','position'])
def test_comment_save_distinguishes_revision_normalization_from_semantic_change(proposal,change):
    (c,cid,v,s,app),p=proposal
    from app.proposal_document import verify_document
    from fastapi import HTTPException
    op=prepare(c,s,v,'COMMENT').json()
    op['target']['quote']='修改版'
    op['target']['paragraph']='修改版'
    op['target']['blocks'][0]['text']='修改版'
    before=output(op,'MODIFY')
    after=output(op,'ALL')
    if change=='renumber':
        after=rewrite_docx(after,**{'word/document.xml':lambda x:x.replace('<w:del w:id="1">','<w:del w:id="71">').replace('<w:ins w:id="2">','<w:ins w:id="72">')})
    elif change=='drop_empty':
        before=rewrite_docx(before,**{'word/document.xml':lambda x:x.replace('<w:p>','<w:p><w:ins w:id="80"><w:r><w:t></w:t></w:r></w:ins><w:del w:id="81"><w:r><w:delText></w:delText></w:r></w:del>')})
    elif change=='split_runs':
        after=rewrite_docx(after,**{'word/document.xml':lambda x:x.replace('<w:ins w:id="2"><w:r><w:t>修改版</w:t></w:r></w:ins>','<w:ins w:id="72"><w:r><w:t>修</w:t></w:r></w:ins><w:ins w:id="73"><w:r><w:t>改版</w:t></w:r></w:ins>').replace('<w:del w:id="1"><w:r><w:delText>第一版</w:delText></w:r></w:del>','<w:del w:id="74"><w:r><w:delText>第</w:delText></w:r></w:del><w:del w:id="75"><w:r><w:delText>一版</w:delText></w:r></w:del>')})
    elif change=='deleted_text':
        after=rewrite_docx(after,**{'word/document.xml':lambda x:x.replace('第一版','其他版')})
    elif change=='author':
        after=rewrite_docx(after,**{'word/document.xml':lambda x:x.replace('<w:ins w:id="2">','<w:ins w:id="2" w:author="另一作者">')})
    else:
        deleted='<w:del w:id="1"><w:r><w:delText>第一版</w:delText></w:r></w:del>'
        after=rewrite_docx(after,**{'word/document.xml':lambda x:x.replace(deleted,'').replace('</w:ins>','</w:ins>'+deleted)})
    if change in ('renumber','drop_empty','split_runs'):
        assert verify_document(before,after,op)['comment_id']=='0'
    else:
        with pytest.raises(HTTPException,match='添加批注时原有修订发生变化'):
            verify_document(before,after,op)


@pytest.mark.parametrize('new_session',[False,True])
def test_query_saved_result_can_explicitly_forbid_cancellation(proposal,monkeypatch,new_session):
    (c,cid,v,s,app),p=proposal
    from app import onlyoffice as oo
    monkeypatch.setattr(oo,'send_command',lambda *_:{'error':0})
    op=prepare(c,s,v).json()
    receipt=save(c,s).json();callback(c,s,receipt,docx('第一版'),monkeypatch)
    if new_session:s=reopen_session(c,cid,s,v['id'])
    url='/api/v1/proposal-operations/'+op['id']+'/confirm'
    response=c.post(url,json={'session_id':s['id'],'allow_cancel':False})
    assert response.status_code==409
    assert c.get('/api/v1/runs/r1/proposal-operations').json()[0]['state']=='prepared'
    response=c.post(url,json={'session_id':s['id'],'allow_cancel':True})
    assert response.status_code==200,response.text
    assert response.json()['state']=='cancelled'

@pytest.mark.parametrize('shape', ['legacy', 'insert', 'plain_insert'])
def test_prepare_append_keeps_original_and_adds_separate_blocks(proposal, shape):
    (client, _, version, session, app), _ = proposal
    with app.state.store.connect() as db:
        run = json.loads(db.execute('SELECT payload FROM runs WHERE id="r1"').fetchone()[0])
        draft = run['revision_proposals'][0]
        if shape in ('insert', 'plain_insert'):
            draft.update(operation='insert', before_text='')
        draft['after_text'] = draft['before_text'] + '\n\n\t  4.7 双向保密【待确认】\n4.8 例外'
        if shape == 'plain_insert':
            draft['after_text'] = draft['after_text'].lstrip()
        db.execute('UPDATE runs SET payload=? WHERE id="r1"', (json.dumps(run),))
    result = prepare(client, session, version)
    assert result.status_code == 200, result.text
    op = result.json()
    assert op['target']['quote'] == '第一版'
    assert op['append_paragraphs'] == ['4.7 双向保密【待确认】','4.8 例外']
    assert op['expected_blocks'] == ['第一版', *op['append_paragraphs']]


def test_append_inside_clause_is_not_offered_as_a_paragraph_insertion(proposal):
    (client, _, version, session, app), _ = proposal
    with app.state.store.connect() as db:
        run = json.loads(db.execute('SELECT payload FROM runs WHERE id="r1"').fetchone()[0])
        draft = run['revision_proposals'][0]
        draft.update(before_text='第一', after_text='第一\n4.7 双向保密')
        draft['anchor'].update(end=2, quote='第一')
        db.execute('UPDATE runs SET payload=? WHERE id="r1"', (json.dumps(run),))
    options = client.get('/api/v1/runs/r1/proposal-availability').json()['proposals']['p1']
    assert options['modes'] == ['COMMENT']
    response = prepare(client, session, version)
    assert response.status_code == 409 and '同段正文' in response.json()['detail']

@pytest.mark.parametrize('tracked_break,tracked_text,accepted', [(True,True,True),(False,True,False),(True,False,False)])
def test_confirm_append_checks_new_text_and_paragraph_break(tracked_break, tracked_text, accepted):
    from app.proposal_document import verify_document
    from fastapi import HTTPException
    prefix = '<w:pPr><w:rPr><w:ins w:id="1"/></w:rPr></w:pPr>' if tracked_break else ''
    body = '<w:r><w:t>新增保密条款</w:t></w:r>'
    if tracked_text:
        body = '<w:ins w:id="2">'+body+'</w:ins>'
    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p>'
           +prefix+'<w:bookmarkStart w:id="0" w:name="test_anchor"/><w:r><w:t>第一版</w:t></w:r>'
           +'<w:bookmarkEnd w:id="0"/></w:p><w:p>'+body+'</w:p></w:body></w:document>')
    blob = BytesIO()
    with ZipFile(blob, 'w') as z:
        z.writestr('word/document.xml', xml)
    op = {'bookmark':'test_anchor','target':{'start':0,'quote':'第一版','blockId':'v:p1','blocks':[{'id':'v:p1'}]},
          'mode':'MODIFY','append_paragraphs':['新增保密条款']}
    if accepted:
        assert verify_document(docx('第一版'),blob.getvalue(),op)['bookmark']=='test_anchor'
    else:
        with pytest.raises(HTTPException):
            verify_document(docx('第一版'),blob.getvalue(),op)


@pytest.mark.parametrize('image', [False, True])
def test_table_target_keeps_location_and_checks_write_modes(proposal, image):
    (client, _, version, session, app), _ = proposal
    with app.state.store.connect() as db:
        parsed = json.loads(db.execute('SELECT parsed FROM versions WHERE id=?', (version['id'],)).fetchone()[0])
        block = parsed['blocks'][0]
        block['table_location'] = {'table': 1, 'row': 2, 'cell': 3}
        parsed['image_block_ids'] = [block['id']] if image else []
        db.execute('UPDATE versions SET parsed=? WHERE id=?', (json.dumps(parsed), version['id']))
    item = client.get('/api/v1/runs/r1/proposal-availability').json()['proposals']['p1']
    assert item['location']['target']['blockId'] == block['id']
    assert item['modes'] == ([] if image else ['ALL','COMMENT','MODIFY'])
    response = prepare(client,session,version)
    if image:
        assert response.status_code == 409 and '含图片' in response.json()['detail']
    else:
        assert response.status_code == 200
        assert response.json()['target']['table_location'] == block['table_location']


def test_table_confirmation_rejects_changed_merge_even_with_same_text():
    from app.proposal_document import verify_document
    from fastapi import HTTPException

    def table_doc(span):
        stream = BytesIO()
        with ZipFile(stream, 'w') as archive:
            archive.writestr('word/document.xml',
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:body><w:tbl><w:tr><w:tc><w:tcPr><w:gridSpan w:val="'+span+'"/></w:tcPr>'
                '<w:p><w:r><w:t>原文</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
        return stream.getvalue()
    op = {'target': {'table_location': {'table': 1, 'row': 1, 'cell': 1}}}
    with pytest.raises(HTTPException, match='合并结构'):
        verify_document(table_doc('1'), table_doc('2'), op)
