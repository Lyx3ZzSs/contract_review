import json
import httpx
import pytest
from app.llm import Settings, ExtractionError
from app.review_jobs import review

RULES=[{'id':f'RL-0{i}'} for i in range(1,6)]
BLOCKS=[{'id':'p1','text':'🙂 合同金额待填写。'}]


def output():
    return {'findings':[{'rule_id':r['id'],'status':'insufficient_evidence','explanation':'需补充材料',
      'evidence':[{'block_id':'p1','start':0,'end':1,'quote':'合同金额待填写'}],'suggested_text':None} for r in RULES]}


def respond(monkeypatch,payload,finish='stop',status=200,fenced=False):
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):
            return httpx.Response(status,json={'choices':[{'finish_reason':finish,'message':{'content':('```json\n' if fenced else '')+json.dumps(payload,ensure_ascii=False)+('\n```' if fenced else '')}}]})
    monkeypatch.setattr(httpx,'Client',Client)


def test_review_recomputes_unicode_offsets(monkeypatch):
    respond(monkeypatch,output())
    fs=review(Settings('http://test','test-key'),'deepseek-v4-flash',BLOCKS,{},RULES,prompt_version='redlines-v1')
    assert fs[0]['evidence'][0]['start']==2 and fs[0]['evidence'][0]['end']==9


@pytest.mark.parametrize('bad',['missing_rule','fake_quote','unknown_block','no_evidence','invalid_status','incomplete'])
def test_review_rejects_invalid_candidates(monkeypatch,bad):
    payload=output();f=payload['findings'][0]
    if bad=='missing_rule':f['rule_id']='RL-02'
    if bad=='fake_quote':f['evidence'][0]['quote']='不存在的引用'
    if bad=='unknown_block':f['evidence'][0]['block_id']='p100'
    if bad=='no_evidence':f.update(status='flag',evidence=[])
    if bad=='invalid_status':f['status']='approved'
    respond(monkeypatch,payload,finish='length' if bad=='incomplete' else 'stop')
    with pytest.raises(ExtractionError):review(Settings('http://test','test-key'),'deepseek-v4-flash',BLOCKS,{},RULES,prompt_version='redlines-v1')


def test_single_json_fence_keeps_evidence_validation(monkeypatch):
    respond(monkeypatch,output(),fenced=True)
    fs=review(Settings('http://test','test-key'),'deepseek-v4-flash',BLOCKS,{},RULES,prompt_version='redlines-v1')
    assert fs[0]['evidence'][0]['start']==2
    payload=output();payload['findings'][0]['evidence'][0]['quote']='虚构'
    respond(monkeypatch,payload,fenced=True)
    with pytest.raises(ExtractionError):review(Settings('http://test','test-key'),'deepseek-v4-flash',BLOCKS,{},RULES,prompt_version='redlines-v1')


def test_review_sends_requested_policy_without_labels(monkeypatch):
    from app.review_policy import PROMPTS
    captured=[]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):
            captured.append(kwargs['json']['messages'])
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(output())}}]})
    monkeypatch.setattr(httpx,'Client',Client)
    for version in ('redlines-v1','redlines-v2'):
        review(Settings('http://test','test-key'),'deepseek-v4-flash',BLOCKS,{'stage':'pre_sign'},RULES,prompt_version=version)
        assert captured[-1][0]['content']==PROMPTS[version]
        body=json.loads(captured[-1][1]['content'])
        assert set(body)=={'schema','context','rules','blocks'}
    assert captured[0]!=captured[1]


def test_evaluation_does_not_hide_conflicting_findings():
    from evaluation.run_calibration import grade
    findings=[{'rule_id':'RL-02','status':'no_flag_for_target_rule'},{'rule_id':'RL-02','status':'insufficient_evidence'}]
    assert not grade(findings,{'RL-02':['no_flag_for_target_rule']})[0]['passed']
    assert not grade([],{'RL-02':['no_flag_for_target_rule']})[0]['passed']
