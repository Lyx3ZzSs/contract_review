import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.store import Store
from app.review_records import register


@pytest.fixture
def records(tmp_path):
    store = Store(tmp_path / 'records.sqlite3')
    app = FastAPI()
    register(app, store)
    with store.connect() as db:
        for cid, purpose in [('business', 'business'), ('test', 'test')]:
            contract = {'title': '北辰服务合同', 'data_purpose': purpose, 'party_details': {'counterparties': ['北辰新能源有限公司']}}
            db.execute('INSERT INTO contracts VALUES(?,?,?)', (cid, json.dumps(contract), '2026-11-01'))
            db.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?,?)', ('v-'+cid,cid,1,'hash','合同.docx',b'PK', '{}','2026-11-01'))
        for rid, cid, status, time in [('old','business','completed','2026-11-17T10:00:00Z'),('new','business','running','2026-11-18T10:00:00Z'),('hidden','test','failed','2026-11-18T12:00:00Z')]:
            run = {'id':rid, 'status':status,'created_at':time,'result_schema_version':'interactive-review-v3','issues':[{'id':'a','status':'flag'},{'id':'b','status':'insufficient_evidence'}], 'findings':[],'rule_results':[]}
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)', (rid,cid,'v-'+cid,rid,'hash',status,json.dumps(run),time))
        for action in ['acknowledged','needs_business_confirmation']:
            db.execute('INSERT INTO decisions(run_id,finding_id,payload,created_at) VALUES(?,?,?,?)',('old','a',json.dumps({'finding_id':'a','action':action}),'2026-11-17'))
    return TestClient(app), store


def test_rounds_and_counts_exclude_tests_and_preserve_number_when_filtered(records):
    client, _ = records
    body = client.get('/api/v1/review-records').json()
    assert body['total'] == 2
    assert body['counts'] == {'all':2,'active':1,'completed':1,'failed':0,'needs_input':0}
    assert [(r['id'],r['round_number'],r['is_latest']) for r in body['items']] == [('new',2,True),('old',1,False)]
    body = client.get('/api/v1/review-records',params={'state':'active','since':'2026-11-18','q':'北辰新能源'}).json()
    assert body['total'] == 1 and body['items'][0]['round_number'] == 2
    assert body['items'][0]['document_version_id'] == 'v-business'
    assert client.get('/api/v1/review-records/hidden').status_code == 404


def test_search_is_literal_and_pagination_is_clamped(records):
    client, _ = records
    assert client.get('/api/v1/review-records',params={'q':"%' OR 1=1 --"}).json()['total']==0
    body=client.get('/api/v1/review-records',params={'page_size':1,'page':90}).json()
    assert body['page']==2 and body['items'][0]['id']=='old'
    assert client.get('/api/v1/review-records',params={'q':'不存在'}).json()['items']==[]


def test_completion_freezes_human_counts_and_keeps_ai_status_separate(records):
    client, store=records
    before=client.get('/api/v1/review-records/old').json()
    assert before['pending']==2 and before['completed_at'] is None
    with store.connect() as db:
        run=json.loads(db.execute("SELECT payload FROM runs WHERE id='old'").fetchone()[0])
        run['module_errors']=[{'message':'partial'}]
        db.execute("UPDATE runs SET payload=? WHERE id='old'",(json.dumps(run),))
        result={'id':'result','created_at':'2026-11-17T11:00:00Z','decisions':[{'finding_id':'a','action':'acknowledged'}],'review_snapshot':run}
        db.execute('INSERT INTO results VALUES(?,?,?,?)',('result','old',json.dumps(result),result['created_at']))
    after=client.get('/api/v1/review-records/old').json()
    assert after['status']=='completed' and after['incomplete'] is True
    assert after['pending']==1 and after['handled']==1 and after['result_id']=='result'
    assert after['completed_at']=='2026-11-17T11:00:00Z'


@pytest.mark.parametrize('params',[{'state':'bogus'},{'since':'invalid'},{'page':0},{'page_size':51},{'q':'x'*201}])
def test_invalid_query_rejected(records,params):
    assert records[0].get('/api/v1/review-records',params=params).status_code==422


def test_missing_record(records):
    assert records[0].get('/api/v1/review-records/missing').status_code==404


@pytest.mark.parametrize('model_reviewed,partial',[(True,True),(True,False),(False,False)])
def test_needs_input_record_classification(records,model_reviewed,partial):
    client,store=records
    with store.connect() as db:
        run=json.loads(db.execute("SELECT payload FROM runs WHERE id='new'").fetchone()[0])
        run.update(status='needs_input',module_errors=[{'message':'部分失败'}] if partial else [])
        if model_reviewed:run['extraction_status']='model_reviewed'
        db.execute("UPDATE runs SET status='needs_input',payload=? WHERE id='new'",(json.dumps(run),))
    category='completed' if model_reviewed else 'needs_input'
    detail=client.get('/api/v1/review-records/new').json()
    assert (detail['status'],detail['record_status'],detail['incomplete'])==('needs_input',category,partial)
    result=client.get('/api/v1/review-records',params={'state':category,'page_size':1}).json()
    assert result['items']==[detail] and result['counts'][category]==result['total']==1+model_reviewed
