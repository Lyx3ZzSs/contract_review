import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app import tianyancha
from io import BytesIO
from docx import Document

@pytest.fixture
def env(tmp_path,monkeypatch):
 c=TestClient(create_app(tmp_path/'db.sqlite3'))
 cid=c.post('/api/v1/contracts',json={'title':'主体测试','contract_type':'服务','our_party':'乙方','stage':'pre_sign','data_purpose':'test'}).json()['id']
 d=Document();d.add_paragraph('甲方：测试有限公司');b=BytesIO();d.save(b)
 v=c.post(f'/api/v1/contracts/{cid}/versions',files={'file':('test.docx',b.getvalue())}).json()['id']
 calls=[]
 def provider(module,keyword,page=1):
  calls.append((module,keyword,page))
  return {'state':'ready','message':'','data':{'name':'测试有限公司','id':123,'creditCode':'123'} if module=='basic' else {'items':[{'name':'股东'}],'total':21}}
 monkeypatch.setattr(tianyancha,'query',provider)
 return c,cid,v,calls,b.getvalue()
def start(e,**extra):
 c,cid,v,*_=e
 return c.post(f'/api/v1/contracts/{cid}/subjects',json={'name':'测试有限公司','document_version_id':v,**extra})
def test_snapshot_cache_and_unknown_risks(env):
 r=start(env);assert r.status_code==200,r.text;p=r.json()
 assert p['matched'] and all(m['state']=='not_queried' and m['data'] is None for m in p['modules'].values())
 assert start(env).json()['id']==p['id'] and len(env[3])==1
 assert start(env,refresh=True).json()['id']!=p['id']
def test_mismatch_confirmation_and_pagination(env):
 c,*_=env;r=start(env,name='旧名称有限公司').json()
 assert not r['matched']
 assert c.post(f"/api/v1/subject-checks/{r['id']}/modules/shareholders").status_code==409
 r=c.post(f"/api/v1/subject-checks/{r['id']}/decision",json={'action':'confirmed','note':'已核对代码'}).json();assert r['matched']
 path=f"/api/v1/subject-checks/{r['id']}/modules/shareholders"
 assert c.post(path).status_code==200
 assert c.post(path).status_code==200
 assert len(env[3])==2
 assert len(c.post(path+'?page=2').json()['modules']['shareholders']['pages'])==2
 assert c.post(path+'?page=0').status_code==422
 assert c.post(f"/api/v1/subject-checks/{r['id']}/modules/unknown").status_code==422

def test_version_change_and_cross_contract(env):
 c,cid,v,calls,raw=env;r=start(env).json()
 other=c.post('/api/v1/contracts',json={'title':'其他','contract_type':'服务','our_party':'乙方','stage':'pre_sign'}).json()['id']
 assert c.post(f'/api/v1/contracts/{other}/subjects',json={'name':'测试有限公司','document_version_id':v}).status_code==404
 d=Document(BytesIO(raw));d.add_paragraph('新正文');b=BytesIO();d.save(b)
 c.post(f'/api/v1/contracts/{cid}/versions',data={'expected_version_id':v},files={'file':('new.docx',b.getvalue())})
 assert start(env).status_code==409
 assert c.post(f"/api/v1/subject-checks/{r['id']}/decision",json={'action':'reviewed'}).status_code==409

def test_export_freezes_subject_decision(env):
 c,cid,v,*_=env;r=start(env).json()
 from app.store import Store
 store=c.app.state.store
 with store.connect() as db:
  from app.exports import capture
  snap,_,_=capture(db,cid,v,None)
 assert snap['subjects'][0]['id']==r['id']
 c.post(f"/api/v1/subject-checks/{r['id']}/decision",json={'action':'needs_material','note':'补充证明'})
 assert snap['subjects'][0]['decision'] is None

@pytest.mark.parametrize('code,state',[(300000,'empty'),(300005,'unavailable'),(300006,'unavailable'),(300004,'failed')])
def test_provider_status_does_not_become_zero(monkeypatch,code,state):
 import httpx
 monkeypatch.setattr(tianyancha,'settings',lambda:('https://open.api.tianyancha.com','test-secret'))
 def get(self,url,**kw):
  assert kw['headers']['Authorization']=='test-secret'
  return httpx.Response(200,json={'error_code':code,'reason':'test-secret'})
 monkeypatch.setattr(httpx.Client,'get',get)
 r=tianyancha.query('basic','测试有限公司')
 assert r['state']==state and r['data'] is None and 'test-secret' not in str(r)

@pytest.mark.parametrize('module', list(tianyancha.RISKS))
def test_all_risk_modules_support_zero_result_cache(env, monkeypatch, module):
 c,*_=env;r=start(env).json();calls=[]
 def provider(key,keyword,page=1):
  calls.append((key,keyword,page))
  return {'state':'empty','message':'本次查询未发现相关记录','data':{'total':0,'items':[],'records':[]},'provider_code':300000}
 monkeypatch.setattr(tianyancha,'query',provider)
 path=f"/api/v1/subject-checks/{r['id']}/modules/{module}"
 p=c.post(path).json();assert p['modules'][module]['state']=='empty'
 assert c.post(path).status_code==200 and len(calls)==1
 assert c.post(path+'?page=2').status_code==422
 assert c.post(path+'?refresh=true').status_code==200 and len(calls)==2


def test_risk_permission_failure_is_retryable_not_a_cache_hit(env,monkeypatch):
 c,*_=env;r=start(env).json();calls=[]
 def provider(*args):
  calls.append(args)
  return {'state':'unavailable','message':'当前账号未开通此项','data':None,'provider_code':300005}
 monkeypatch.setattr(tianyancha,'query',provider)
 path=f"/api/v1/subject-checks/{r['id']}/modules/tax"
 assert c.post(path).json()['modules']['tax']['data'] is None
 assert c.post(path).json()['modules']['tax']['state']=='unavailable' and len(calls)==2


def test_failed_later_page_preserves_prior_records_and_success_time(env,monkeypatch):
 c,*_=env;r=start(env).json()
 good={'state':'ready','message':'','data':{'total':21,'items':[{'caseCode':str(i)} for i in range(20)],'records':[{'title':'已有案件','fields':[]}]}}
 monkeypatch.setattr(tianyancha,'query',lambda *args:good.copy())
 path=f"/api/v1/subject-checks/{r['id']}/modules/execution"
 first=c.post(path).json()['modules']['execution']
 monkeypatch.setattr(tianyancha,'query',lambda *args:{'state':'failed','message':'请求失败','data':None})
 second=c.post(path+'?page=2').json()['modules']['execution']
 assert second['state']=='failed' and second['queried_at']==first['queried_at']
 assert second['data']['total']==21 and second['pages']==first['pages']
 # Provider failures with no code remain failures after GET, including first-query failures.
 c.post(f"/api/v1/subject-checks/{r['id']}/modules/tax")
 fetched=c.get(f'/api/v1/contracts/{env[1]}/subjects').json()['checks'][0]
 assert fetched['modules']['tax']['state']=='failed'
 assert fetched['modules']['execution']['pages']==first['pages']


def test_expired_pages_and_refresh_clear_old_details(env,monkeypatch):
 c,*_=env;r=start(env).json()
 def provider(*args):return {'state':'ready','message':'','data':{'total':21,'gid':'123','items':[{'uuid':'case-a'}],'records':[]}}
 monkeypatch.setattr(tianyancha,'query',provider)
 path=f"/api/v1/subject-checks/{r['id']}/modules/bankruptcy"
 first=c.post(path).json()
 import json
 with c.app.state.store.connect() as db:
  first['modules']['bankruptcy']['queried_at']='2020-01-01T00:00:00+00:00'
  first['modules']['bankruptcy']['details']={'case-a':{'state':'ready','data':{}}}
  db.execute('UPDATE subject_checks SET payload=? WHERE id=?',(json.dumps(first),r['id']))
 assert c.post(path+'?page=2').status_code==409
 assert c.post(f"/api/v1/subject-checks/{r['id']}/bankruptcy/case-a").status_code==409
 updated=c.post(path+'?refresh=true').json()['modules']['bankruptcy']
 assert 'details' not in updated and list(updated['pages'])==['1']


def test_bankruptcy_detail_binds_case_to_company_and_caches(env,monkeypatch):
 c,*_=env;r=start(env).json();calls=[]
 def provider(module,keyword,page=1,**kwargs):
  calls.append((module,keyword,kwargs))
  data={'total':1,'gid':'123','items':[{'uuid':'case-a'}],'records':[]} if module=='bankruptcy' else {'uuid':'case-a','record':{'title':'案件','fields':[]}}
  return {'state':'ready','message':'','data':data}
 monkeypatch.setattr(tianyancha,'query',provider)
 c.post(f"/api/v1/subject-checks/{r['id']}/modules/bankruptcy")
 path=f"/api/v1/subject-checks/{r['id']}/bankruptcy/"
 assert c.post(path+'unrelated').status_code==404 and len(calls)==1
 assert c.post(path+'case-a').json()['modules']['bankruptcy']['details']['case-a']['state']=='ready'
 assert c.post(path+'case-a').status_code==200 and len(calls)==2
 assert calls[-1]==('bankruptcy_detail','123',{'detail_id':'case-a'})


@pytest.mark.parametrize('module,path',[
 ('dishonesty','/services/open/jr/dishonest/2.0'),('execution','/services/open/jr/zhixinginfo/2.0'),
 ('illegal','/services/open/mr/illegalinfo/2.0'),('abnormal','/services/open/mr/abnormal/2.0'),
 ('tax','/services/open/mr/improperTaxpayer'),('bankruptcy','/services/open/jr/bankruptcy/2.0')])
def test_risk_provider_protocol_and_normalized_records(monkeypatch,module,path):
 import httpx
 monkeypatch.setattr(tianyancha,'settings',lambda:('https://open.api.tianyancha.com','secret'))
 item={'caseNo':'测试案号','casecode':'测试案号','putReason':'测试原因','taxpayerName':'测试企业','execMoney':'200000','regdate':1595520000000,'putDate':'2024-01-02','status':0,'applicant':[{'applicantName':'申请人'}],'uuid':'case-a'}
 def get(self,url,**kw):
  assert url=='https://open.api.tianyancha.com'+path
  assert kw['params']=={'keyword':'123','pageNum':2,'pageSize':20}
  assert kw['headers']=={'Authorization':'secret'}
  return httpx.Response(200,json={'error_code':0,'result':{'total':21,'items':[item]}})
 monkeypatch.setattr(httpx.Client,'get',get)
 result=tianyancha.query(module,'123',2)
 assert result['state']=='ready' and result['data']['total']==21
 assert len(result['data']['records'])==1
 if module=='bankruptcy':
  record=result['data']['records'][0]
  assert record['detail_id']=='case-a'
  assert {'label':'案件状态','value':'历史案件'} in record['fields']
 if module=='dishonesty':assert {'label':'立案日期','value':'2020-07-24'} in result['data']['records'][0]['fields']


@pytest.mark.parametrize('body', [[],{'error_code':0}, {'error_code':0,'result':{'total':5,'items':[]}}, {'error_code':0,'result':{'total':0,'items':[{}]}}, {'error_code':0,'result':{'total':1,'items':[None]}}])
def test_malformed_provider_response_never_counts_as_clear(monkeypatch,body):
 import httpx
 monkeypatch.setattr(tianyancha,'settings',lambda:('https://open.api.tianyancha.com','secret'))
 monkeypatch.setattr(httpx.Client,'get',lambda *args,**kwargs:httpx.Response(200,json=body))
 result=tianyancha.query('execution','123')
 assert result['state']=='failed' and result['data'] is None


def test_later_empty_page_is_failure(monkeypatch):
 import httpx
 monkeypatch.setattr(tianyancha,'settings',lambda:('https://open.api.tianyancha.com','secret'))
 monkeypatch.setattr(httpx.Client,'get',lambda *args,**kwargs:httpx.Response(200,json={'error_code':300000}))
 result=tianyancha.query('execution','123',2)
 assert result['state']=='failed' and result['data'] is None


def test_risk_refresh_does_not_change_export_snapshot(env,monkeypatch):
 c,cid,v,*_=env;r=start(env).json()
 monkeypatch.setattr(tianyancha,'query',lambda *a:{'state':'ready','message':'','data':{'total':1,'items':[{}],'records':[{'title':'执行案号','fields':[{'label':'执行标的（元）','value':'200000'}]}]}})
 c.post(f"/api/v1/subject-checks/{r['id']}/modules/execution")
 with c.app.state.store.connect() as db:
  from app.exports import capture
  snapshot,_,_=capture(db,cid,v,None)
 monkeypatch.setattr(tianyancha,'query',lambda *a:{'state':'empty','message':'本次查询未发现相关记录','data':{'total':0,'items':[],'records':[]}})
 c.post(f"/api/v1/subject-checks/{r['id']}/modules/execution?refresh=true")
 assert snapshot['subjects'][0]['modules']['execution']['data']['total']==1
 # Export includes all fetched details, counts, source and explicit unavailable statuses.
 from app.export_docx import generate
 snapshot.update(id='subject-export-test',kind='opinions',run={},report={'risks':[],'revisions':[],'analysis':[]})
 doc=Document(BytesIO(generate(snapshot)));text='\n'.join(p.text for p in doc.paragraphs)
 assert '执行标的（元）：200000' in text and '已加载 1 / 1 条' in text
 assert '尚未查询' in text and '来源：天眼查' in text
