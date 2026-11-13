from copy import deepcopy
import json
import pytest
from app.issue_presentation import enrich_run_presentation
from app.field_review import FieldObservation, classify, classify_one
from test_backend import setup
from test_review_interactions import interactive
from app.store import Store


def observation(name='合同编号', timing='unknown', state='blank', required=False):
    evidence={'block_id':'p1','start':0,'end':5,'quote':'合同编号：'}
    return {'name':name,'value_state':state,'timing':timing,'evidence':[evidence],
            'requirement_evidence':[evidence] if required else []}


def finding(obs, status='insufficient_evidence'):
    return {'id':'i1','rule_id':'RL-05','status':status,'explanation':'原始解释','evidence':[], 'field_checks':obs}


def test_contract_number_and_signature_fields_keep_observations_without_todos():
    fields=[observation()]+[observation(f'签署栏{i}', 'signature_block') for i in range(4)]
    item=finding(fields,status='no_flag_for_target_rule'); source={'findings':[item], 'issues':[deepcopy(item)], 'rule_results':[deepcopy(item)]}
    original=deepcopy(source)
    result=enrich_run_presentation(source)
    assert source==original
    for key in source:
        value=result[key][0]
        assert value['status']==item['status'] and value['id']==item['id'] and value['explanation']==item['explanation']
        p=value['presentation']
        assert p['title']=='本轮未发现需要处理的字段缺项'
        assert len(p['observations'])==5
        assert [o['status'] for o in p['observations']].count('no_flag_for_target_rule')==5
        assert '签署栏' not in p['summary']


@pytest.mark.parametrize('state,timing,required', [('filled','current_required',True),('blank','future_template',False),('blank','signature_block',False),('placeholder','current_required',True),('blank','current_required',False),('unavailable','unknown',False)])
def test_single_field_classification_matches_aggregate(state,timing,required):
    field=FieldObservation(**observation(state=state,timing=timing,required=required))
    assert classify_one(field)==classify([field])


def test_mixed_fields_only_present_actionable_missing_information():
    p=enrich_run_presentation({'findings':[finding([observation(timing='current_required'),observation('税号')])]})['findings'][0]['presentation']
    assert p['title']=='税号的填写要求待确认'
    assert '签署前必填' not in p['summary']
    assert all(not o['requirement_evidence'] for o in p['observations'])


@pytest.mark.parametrize('fields', [None, [], [{'name':'坏数据'}], 'bad'])
def test_missing_or_invalid_metadata_falls_back(fields):
    source={'findings':[finding(fields)]}
    assert enrich_run_presentation(source)==source


def test_old_judgment_is_not_reclassified():
    source={'findings':[finding([observation()],status='insufficient_evidence')]}
    assert enrich_run_presentation(source)==source


def test_amount_uses_saved_decimal_strings_and_ignores_unknown_basis():
    item={'id':'a','rule_id':'RL-02','status':'insufficient_evidence','explanation':'原文',
          'computed_calculations':[{'operation':'sum','operands':['0.1','0.2'],'stated_total':'0.4','computed':'0.3','difference':'-0.1'}],
          'amount_checks':[{'issue':'calculation','operation':'sum','operands':['0.1','0.2'],'stated_total':'0.4','basis':'consistent','evidence':[{'block_id':'p1','start':0,'end':1,'quote':'额'}]}]}
    p=enrich_run_presentation({'findings':[item]})['findings'][0]['presentation']
    assert '0.3' in p['summary'] and '-0.1' in p['summary']
    item['amount_checks'][0]['basis']='unknown'
    assert 'presentation' not in enrich_run_presentation({'findings':[item]})['findings'][0]


def test_get_run_enriches_read_only_without_changing_stored_snapshot(interactive):
    (client,_,_,_,path),run=interactive
    with Store(path).connect() as db:
        stored=json.loads(db.execute('SELECT payload FROM runs WHERE id=?',(run['id'],)).fetchone()[0])
        for key in ('findings','issues','rule_results'):
            item=next(i for i in stored[key] if i['rule_id']=='RL-05')
            item.update(status='insufficient_evidence',field_checks=[observation()])
        payload=json.dumps(stored,ensure_ascii=False)
        db.execute('UPDATE runs SET payload=? WHERE id=?',(payload,run['id']))
    response=client.get(f"/api/v1/runs/{run['id']}")
    assert response.status_code==200,response.text
    item=next(i for i in response.json()['issues'] if i['rule_id']=='RL-05')
    assert item['status']=='insufficient_evidence'
    assert item['presentation'] is None
    history=client.get(f"/api/v1/runs/{run['id']}/issues/{item['id']}/history")
    assert history.status_code==200,history.text
    assert history.json()['items'][-1]['issue']['status']=='insufficient_evidence'
    with Store(path).connect() as db:
        assert db.execute('SELECT payload FROM runs WHERE id=?',(run['id'],)).fetchone()[0]==payload
