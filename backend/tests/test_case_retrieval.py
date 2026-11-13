import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.store import Store


@pytest.fixture
def casebook(tmp_path):
    from app.legal_casebook import Casebook, register
    store = Store(tmp_path/'cases.db')
    with store.connect() as db:
        for family in ['family-a','good','wrong-event','wrong-stage','wrong-business','exceptions','confirmed']:
            db.execute('INSERT INTO contracts VALUES(?,?,?)',(family,'{}','t'))
            db.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?,?)',('v-'+family,family,1,'a'*64,'x',b'0',json.dumps({'blocks':[{'id':'p','text':'违约赔偿全部损失'}]}),'t'))
    app = FastAPI(); register(app,store)
    return Casebook(store), TestClient(app)


def candidate(family='family-a'):
    return dict(family_id=family, source_version_id='v-'+family, source_hash='a'*64, original_span='违约赔偿全部损失', final_opinion='限定赔偿', final_edit='限定累计赔偿', rationale='个案谈判', basis_kind='case_negotiation', basis_refs=['source:1'], actor='录入人')


def confirm(client, item, **updates):
    payload=dict(actor='确认人',confirmed_scope={'roles':['party_b'],'business_scopes':['power_trading'],'event_types':['liability'],'stages':['履约']},basis_refs=['source:1'])
    payload.update(updates)
    return client.post('/api/v1/legal-cases/'+item['case_id']+'/confirm',json=payload)


def test_candidate_confirm_retire_and_frozen_snapshot(casebook):
    book, client = casebook
    item = client.post('/api/v1/legal-cases',json=candidate()).json()
    context={'our_party_code':'party_b','business_scope':'power_trading','business_scope_state':'matched','stage':'履约'}
    event={'event_type':'liability','trigger_quote':'赔偿全部损失'}
    assert book.retrieve_cases(event,context,set(),book.current_version()) == []
    published = confirm(client,item)
    assert published.status_code == 200
    frozen=book.current_version()
    hits=book.retrieve_cases(event,context,set(),frozen)
    assert len(hits)==1 and hits[0]['scope_match']
    assert hits[0]['confirmation']['actor_authentication']=='self_reported'
    assert book.retrieve_cases(event,context,{'contract:family-a'},frozen)==[]
    assert book.retrieve_cases(event,{**context,'our_party_code':'party_a'},set(),frozen)==[]
    assert book.retrieve_cases(event,{**context,'business_scope_state':'conflict'},set(),frozen)==[]
    assert client.post('/api/v1/legal-cases/'+item['case_id']+'/retire',json={'actor':'确认人','reason':'意见撤回'}).status_code==200
    assert book.retrieve_cases(event,context,set(),book.current_version())==[]
    assert book.retrieve_cases(event,context,set(),frozen)==hits
    history=client.get('/api/v1/legal-cases/'+item['case_id']).json()['versions']
    assert [v['state'] for v in history]==['candidate','confirmed','retired']


def test_confirmation_requires_scope_and_verified_legal_basis(casebook):
    _, client=casebook
    legal=candidate();legal['basis_kind']='legal_requirement'
    item=client.post('/api/v1/legal-cases',json=legal).json()
    assert confirm(client,item).status_code==422
    assert confirm(client,item,confirmed_scope={}).status_code==422
    result=confirm(client,item,basis_verification='已核对原文及适用条件')
    assert result.status_code==200
    assert len(client.get('/api/v1/legal-cases').json()['items'])==1


def test_filters_before_ranking_and_exception_guard(casebook):
    book, client=casebook
    event={'event_type':'liability','trigger_quote':'赔偿全部损失'}
    context={'our_party_code':'party_b','business_scope':'power_trading','business_scope_state':'matched','stage':'履约'}
    for family, changes in [('good',{}),('wrong-event',{'event_types':['payment']}),('wrong-stage',{'stages':['签署']}),('wrong-business',{'business_scopes':['weather']})]:
        item=client.post('/api/v1/legal-cases',json=candidate(family)).json()
        scope={'roles':['party_b'],'business_scopes':['power_trading'],'event_types':['liability'],'stages':['履约'],**changes}
        assert confirm(client,item,confirmed_scope=scope).status_code==200
    exceptional=candidate('exceptions');exceptional['exceptions']=['另有特别约定时不适用']
    item=client.post('/api/v1/legal-cases',json=exceptional).json()
    assert confirm(client,item).status_code==200
    hits=book.retrieve_cases(event,context,set(),book.current_version(),limit=1)
    assert [h['family_id'] for h in hits]==['contract:good']
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        book.retrieve_cases(event,context,set(),'unknown-version')
    assert error.value.status_code==422


def test_missing_rationale_stays_candidate_and_confirmation_is_explicit(casebook):
    _, client=casebook
    data=candidate(); data['rationale']=''
    item=client.post('/api/v1/legal-cases',json=data).json()
    assert confirm(client,item).status_code==422
    assert client.get('/api/v1/legal-cases/'+item['case_id']).json()['current']['state']=='candidate'
    item=client.post('/api/v1/legal-cases',json=candidate('confirmed')).json()
    assert confirm(client,item).status_code==200
    assert confirm(client,item).status_code==409


def test_source_binding_rejects_fabrication_and_unbound_case_not_retrieved(casebook):
    book,client=casebook
    data=candidate();data['source_version_id']='missing'
    assert client.post('/api/v1/legal-cases',json=data).status_code==422
    data=candidate();data.pop('source_version_id',None)
    item=client.post('/api/v1/legal-cases',json=data).json()
    assert confirm(client,item).status_code==200
    assert book.retrieve_cases({'event_type':'liability','text':'赔偿全部损失'},{'our_party_code':'party_b','business_scope':'power_trading','business_scope_state':'matched','stage':'履约'},set(),book.current_version())==[]
    assert client.get('/api/v1/legal-cases/'+item['case_id']).json()['current']['state']=='confirmed'


def test_freeze_excludes_source_hash_contract_and_near_duplicate(casebook):
    import json
    from app.legal_casebook import freeze_exclusions
    book,client=casebook
    text='甲方的交易信息由乙方维护，违约赔偿全部损失。资料由双方按月核对，协商解决争议。'
    with book.store.connect() as db:
        db.execute("INSERT INTO contracts VALUES('origin','{}','t')")
        db.execute("INSERT INTO versions VALUES('orig','origin',1,?,'x',X'00',?,'t')",('b'*64,json.dumps({'blocks':[{'id':'p','text':text}]})))
        for vid,cid,digest,body in [('samecontract','origin','c'*64,'完全不同的新版本'),('samehash','copy','b'*64,'独立文本'),('near','near-contract','d'*64,'注'+text)]:
            if cid!='origin':db.execute('INSERT INTO contracts VALUES(?,?,?)',(cid,'{}','t'))
            db.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?,?)',(vid,cid,2 if cid=='origin' else 1,digest,'x',b'0',json.dumps({'blocks':[{'id':'p','text':body}]}),'t'))
    data=candidate();data.update(source_version_id='orig',source_hash='b'*64)
    item=client.post('/api/v1/legal-cases',json=data).json()
    assert item['family_id']=='contract:origin'
    assert item['source_binding']=='verified_version'
    assert confirm(client,item).status_code==200
    for vid in ['samecontract','samehash','near']:
        with book.store.connect() as db: frozen=freeze_exclusions(db,vid,[])
        assert 'contract:origin' in frozen['excluded_family_ids']
        assert 'b'*64 in frozen['excluded_source_hashes']
        assert frozen['document_version_id']==vid
    data.update(source_hash='e'*64)
    assert client.post('/api/v1/legal-cases',json=data).status_code==422
    data.update(source_hash='b'*64,original_span='不存在的原文')
    assert client.post('/api/v1/legal-cases',json=data).status_code==422


def test_source_hash_is_hard_exclusion_even_without_family_match(casebook):
    book,client=casebook
    item=client.post('/api/v1/legal-cases',json=candidate()).json()
    assert confirm(client,item).status_code==200
    context={'our_party_code':'party_b','business_scope':'power_trading','business_scope_state':'matched','stage':'履约'}
    event={'event_type':'liability','text':'赔偿全部损失'}
    version=book.current_version()
    assert len(book.retrieve_cases(event,context,set(),version))==1
    assert book.retrieve_cases(event,context,set(),version,excluded_source_hashes=['a'*64])==[]
    assert book.retrieve_cases(event,{**context,'document_sha256':'A'*64},set(),version)==[]


def test_source_binding_derives_identity_and_checks_feedback_version(casebook):
    book,client=casebook
    with book.store.connect() as db:
        db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)',('r','family-a','v-family-a','idem','hash','completed','{}','t'))
        db.execute('INSERT INTO legal_feedback VALUES(?,?,?,?,?,?)',('feedback','r','idem','hash','{}','t'))
    data=candidate();data.pop('source_hash');data.pop('source_version_id');data['feedback_id']='feedback';data['family_id']='pretend-other-family'
    result=client.post('/api/v1/legal-cases',json=data)
    assert result.status_code==201
    assert result.json()['source_hash']=='a'*64
    assert result.json()['family_id']=='contract:family-a'
    assert result.json()['source_version_id']=='v-family-a'
    data['source_version_id']='v-good'
    assert client.post('/api/v1/legal-cases',json=data).status_code==422


def test_short_identical_text_reimport_is_excluded(casebook):
    from app.legal_casebook import freeze_exclusions
    book,client=casebook
    client.post('/api/v1/legal-cases',json=candidate())
    with book.store.connect() as db:
        db.execute("INSERT INTO contracts VALUES('short-copy','{}','t')")
        db.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?,?)',('short-v','short-copy',1,'f'*64,'x',b'0',json.dumps({'blocks':[{'id':'x','text':'  违约赔偿全部损失\n'}]}),'t'))
        metadata=freeze_exclusions(db,'short-v')
    assert 'contract:family-a' in metadata['excluded_family_ids']
