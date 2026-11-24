import pytest
from test_backend import setup
from app.worker import tick
from app.store import Store
from app.llm import Settings


def test_actual_candidate_extraction_failure_survives_api(setup,monkeypatch):
    import app.configured_review as accurate
    from app.llm import ExtractionError
    def failed(*a,**kw):
        raise ExtractionError('invalid_quote','证据校验失败')
    monkeypatch.setattr(accurate,'extract_call',failed)
    c,cid,_,_,path=setup
    response=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'real-partial'})
    assert response.status_code==202,response.text
    assert tick(Store(path),Settings('http://test','fake'))
    response=c.get(f"/api/v1/runs/{response.json()['id']}")
    assert response.status_code==200,response.text
    run=response.json()
    assert run['status']=='needs_input'
    assert len(run['rule_results'])==6
    assert all(r['execution_state']=='failed' for r in run['rule_results'])
    assert run['module_errors']
    assert run['stage']=='partial'
    assert [i['id'] for i in run['issues']]==[i['id'] for i in run['findings']]
    issue=run['issues'][0]
    response=c.post(f"/api/v1/runs/{run['id']}/issues/{issue['id']}/decisions",json={'action':'acknowledged','note':'保留未完成状态','actor':'test'})
    assert response.status_code==201,response.text


def test_candidate_keeps_policy_with_interactive_and_rejects_hash_drift(setup,monkeypatch):
    import json
    monkeypatch.setenv('RIXIN_INTERACTIVE_REVIEW','1')
    c,cid,_,_,path=setup
    response=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'drift'})
    assert response.status_code==202,response.text
    run=response.json()
    assert run['review_prompt_version']=='review-configured-rules-v1'
    assert run['result_schema_version']=='interactive-review-v3'
    with Store(path).connect() as db:
        run['review_implementation_sha256']='old'
        db.execute('UPDATE runs SET payload=? WHERE id=?',(json.dumps(run),run['id']))
    assert tick(Store(path),Settings('http://test','fake'))
    result=c.get(f"/api/v1/runs/{run['id']}").json()
    assert result['status']=='failed'
    assert result['error']['code']=='review_policy_mismatch'


@pytest.mark.parametrize('interactive',[False,True])
def test_candidate_worker_preserves_unreadable_inline_images_without_bundle(setup,monkeypatch,interactive):
    import json
    import app.configured_review as accurate
    monkeypatch.setenv('RIXIN_INTERACTIVE_REVIEW','1' if interactive else '0')
    c,cid,version,_,path=setup
    with Store(path).connect() as db:
        parsed=json.loads(db.execute('SELECT parsed FROM versions WHERE id=?',(version['id'],)).fetchone()[0])
        parsed['blocks']=[{'id':'v:p1','text':'合同应遵守《附件技术规范》要求。'},{'id':'v:p2','text':'设备运行温度应为零下十度至五十度。'}]
        parsed['image_block_ids']=['v:image1']
        db.execute('UPDATE versions SET parsed=? WHERE id=?',(json.dumps(parsed),version['id']))
    seen=[]
    def fake(settings,model,prompt,schema,payload,validate,deadline,trace):
        seen.append(payload)
        if schema.__name__=='GroundedFacts':
            raw={'attachments':[{'name':'附件技术规范','references':['b1'],'technical_refs':['b1'],'pricing_refs':[]}],'calculations':[],'missing_prices':[],'fields':[]}
        elif schema.__name__=='LimitFacts':raw={'supplier':'不确定','role_refs':[],'scenarios':[],'uncertainties':[]}
        elif schema.__name__=='AssignmentFacts':raw={'clauses':[]}
        elif schema.__name__=='AttachmentResults':raw={'checks':[{'name':'附件技术规范','state':'matched','content_refs':['b2'],'basis_refs':['b1'],'explanation':'正文已包含技术内容'}]}
        else:raw={'findings':[{'rule_id':r,'status':'no_flag_for_target_rule','explanation':'未触发','refs':[]} for r in ['RL-01','RL-04']]}
        value=schema.model_validate(raw)
        return value,validate(value)
    monkeypatch.setattr(accurate,'extract_call',fake)
    response=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'image-case'})
    assert response.status_code==202,response.text
    run=response.json()
    assert bool(run.get('material_bundle_id')) is interactive
    assert tick(Store(path),Settings('http://test','fake'))
    result=c.get(f"/api/v1/runs/{run['id']}")
    assert result.status_code==200,result.text
    data=result.json()
    assert bool(data.get('material_bundle_id')) is interactive
    assert data['coverage']==('parsed_material_bundle' if interactive else 'parsed_document_only')
    assert data['attachment_checks'][0]['attachment_state']=='unreadable'
    assert next(r for r in data['rule_results'] if r['rule_id']=='RL-04')['status']=='insufficient_evidence'
    assert not data['module_errors']
    assert any(p.get('document_contains_unreadable_images') for p in seen)


def test_default_review_only_executes_configured_rule_snapshot(setup, monkeypatch):
    from app import configured_review as agent
    from app.rule_registry import CONFIGURED_RULES_POLICY
    monkeypatch.delenv('RIXIN_REVIEW_POLICY',raising=False)
    c,cid,_,_,path=setup
    configured_ids = ['RL-01', 'RL-02', 'RL-03', 'RL-04', 'RL-05', 'VL-01']
    current = c.get('/api/v1/rules').json()
    assert current['version'] == CONFIGURED_RULES_POLICY
    assert [r['id'] for r in current['rules']] == configured_ids
    response=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'default-release'})
    assert response.status_code==202,response.text
    queued = response.json()
    assert queued['review_prompt_version'] == CONFIGURED_RULES_POLICY
    assert queued['rule_snapshot']['rules'] == current['rules']
    assert 'case_guidance_snapshot' not in queued

    def record(rid):
        return dict(rule_id=rid, status='insufficient_evidence' if rid=='VL-01' else 'no_flag_for_target_rule',
                    explanation='配置规则结果', evidence=[], execution_state='completed')

    def baseline(settings, model, blocks, context, rules, **kwargs):
        assert [rule['id'] for rule in rules] == configured_ids[:-1]
        return dict(rule_results=[record(r['id']) for r in rules], issues=[],
                    diagnostics={}, attachment_checks=[], module_errors=[])

    def display_only(settings, model, prompt, schema, payload, validate, deadline, trace):
        from app.transaction_display import TransactionOverview
        assert schema is TransactionOverview
        source = payload['blocks'][0]
        value = schema(sections=[dict(title='交易概况', text=source['text'], refs=[source['id']])])
        settings.stream_callback('started', revision=1)
        settings.stream_callback('delta', revision=1, changes=[dict(field='section:0:text', offset=0, text=source['text'])])
        return value, validate(value)

    monkeypatch.setattr(agent, 'baseline_review', baseline)
    monkeypatch.setattr(agent.liability_limit, 'run_limit', lambda *a, **kw: record(a[6]['id']))
    monkeypatch.setattr(agent, 'extract_call', display_only)
    assert tick(Store(path), Settings('http://test','fake'))
    result = c.get(f"/api/v1/runs/{queued['id']}").json()
    assert result['stage'] == 'done' and not result['module_errors']
    assert [r['rule_id'] for r in result['rule_results']] == configured_ids
    assert {i['rule_id'] for i in result['issues']} <= set(configured_ids)
    assert set(result['execution_phases']) == {'parse','rules'}
    state = c.get(f"/api/v1/runs/{queued['id']}/execution-state").json()
    overview = state['artifacts']['transaction-overview']
    assert overview['state'] == 'completed' and overview['sections'][0]['evidence'][0]['block_id']
    events = c.get(f"/api/v1/runs/{queued['id']}/execution-events").json()['events']
    assert any(e['type']=='analysis_section' for e in events)
    assert result['revision_proposals'] == []
    assert next(i for i in result['issues'] if i['rule_id']=='VL-01')['display_group'] == 'context'


def test_configured_review_never_loads_historical_case_edits(setup, monkeypatch):
    from app import configured_review as agent
    from app.legal_casebook import Casebook
    from app.rule_registry import CONFIGURED_RULES_POLICY
    from test_backend import docx
    monkeypatch.setenv('RIXIN_REVIEW_POLICY', CONFIGURED_RULES_POLICY)
    c,_,_,_,path = setup
    cid = c.post('/api/v1/contracts', json={'title':'责任修订测试','contract_type':'服务',
                                          'our_party':'乙方','stage':'pre_sign'}).json()['id']
    text = '乙方责任：违约金按日0.5%，甲方可要求退还已付款。'
    upload = c.post(f'/api/v1/contracts/{cid}/versions', files={'file':('合同.docx',docx(text))})
    assert upload.status_code == 201

    def freeze(*args, **kwargs):
        pytest.fail('The configured review must not load historical case edits')

    def baseline(settings, model, blocks, context, rules, **kwargs):
        return dict(rule_results=[dict(rule_id=r['id'], status='no_flag_for_target_rule', explanation='未触发',
                                       evidence=[], execution_state='completed') for r in rules],
                    issues=[], diagnostics={}, attachment_checks=[], module_errors=[])

    def limit(call, settings, model, sources, bundle, context, rule, trace, **kwargs):
        evidence = sources.evidence([next(iter(sources.blocks))])
        return dict(rule_id='VL-01', status='flag',
                    explanation='责任核对', evidence=evidence, execution_state='completed')

    def draft(settings,model,prompt,schema,payload,validate,deadline,trace):
        target, = payload['issues']
        anchor, = target['evidence']
        return schema(proposals=[dict(event_ids=[target['event_id']],ref=anchor['ref'],operation='replace',
                    before_text='已付款',after_text='未履行部分对应款项',rationale='按履行范围结算。')],pending=[]),None

    monkeypatch.setattr(agent,'extract_call',draft)
    monkeypatch.setattr(Casebook,'__init__',freeze)
    monkeypatch.setattr(agent,'baseline_review',baseline)
    monkeypatch.setattr(agent.liability_limit,'run_limit',limit)
    response=c.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'project-wording'})
    assert response.status_code==202,response.text
    assert tick(Store(path),Settings('http://test','fake'))
    result = c.get(f"/api/v1/runs/{response.json()['id']}").json()
    assert result['stage']=='done',result.get('error')
    proposal, = result['revision_proposals']
    assert proposal['after_text']=='未履行部分对应款项' and proposal['event_ids']==['VL-01']
    assert not result.get('case_guidance_snapshot')


def test_configured_candidates_retry_only_rejected_issues_with_the_offending_value(setup, monkeypatch):
    from io import BytesIO
    from xml.sax.saxutils import escape
    from zipfile import ZipFile, ZipInfo
    from app import configured_review as agent
    from app.rule_registry import CONFIGURED_RULES_POLICY

    monkeypatch.setenv('RIXIN_REVIEW_POLICY',CONFIGURED_RULES_POLICY)
    client,_,_,_,path = setup
    cid=client.post('/api/v1/contracts',json={'title':'条款修改测试','contract_type':'服务',
                                            'our_party':'乙方','stage':'pre_sign'}).json()['id']
    daily='1.1 乙方未按期完成技术服务的，每逾期1天，应向甲方支付技术服务报酬0.5%的违约金，逾期超过90日的，甲方有权单方解除合同。'
    refund='1.4合同因乙方原因解除的，甲方有权停止支付并要求乙方退还甲方已支付的全部款项，且乙方应支付技术服务报酬5%的违约金。'
    deadline='2.1 收到发票后10日内付款，双方确认付款期限为收到发票后15日。'
    confidentiality='3.1 乙方披露保密信息时应赔偿甲方全部损失。'
    paragraphs=''.join(f'<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>' for text in (daily,refund,deadline,confidentiality))
    stream=BytesIO()
    with ZipFile(stream,'w') as z:
        z.writestr(ZipInfo('word/document.xml'),f'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{paragraphs}</w:body></w:document>')
    assert client.post(f'/api/v1/contracts/{cid}/versions',files={'file':('合同.docx',stream.getvalue())}).status_code==201

    def baseline(settings,model,blocks,context,rules,**kwargs):
        evidence=agent.Sources(blocks).evidence(['b3'])
        records=[dict(rule_id=r['id'],status='flag' if r['id']=='RL-01' else 'no_flag_for_target_rule',
                      execution_state='completed',evidence=evidence if r['id']=='RL-01' else [],explanation='付款期限前后不一致。')
                 for r in rules]
        return dict(rule_results=records,issues=[],diagnostics={},attachment_checks=[],module_errors=[])

    def limit(call,settings,model,sources,bundle,context,rule,trace,**kwargs):
        anchors = sources.evidence(['b1','b2','b4'])
        cards = [dict(kind=kind,text=explanation,direction=direction,evidence=[anchor])
                 for kind,explanation,direction,anchor in [
                     ('daily','累计金额待核实。','明确累计责任。',anchors[0]),
                     ('paid_refund','需核对结算范围。','保留已履行部分的服务费。',anchors[1]),
                     ('other_liability','损失范围待明确。','限定赔偿范围。',anchors[2])]]
        return dict(rule_id='VL-01',status='insufficient_evidence',execution_state='completed',
                    explanation='项目上限待确认。',evidence=anchors,
                    card_content=dict(version='review-card-v1',risk_paragraphs=cards,modification_plan=''))

    batches=[]
    def local_call(settings,model,prompt,schema,payload,validate,deadline_at,trace):
        batches.append(payload)
        if schema is agent.SingleClauseDraft:
            draft = schema(after_text='2.1 收到发票后15日内付款。',rationale='按确认期限付款。')
            return draft,validate(draft)
        assert settings.progress_only_stream and settings.stream_callback
        after = {'b1':daily.replace('的违约金','的违约金，累计以【待确认累计上限】为限'),
                 'b2':refund.replace('并要求乙方退还甲方已支付的全部款项',''),
                 'b3':'2.1 收到发票后15日内付款。','b4':confidentiality.replace('全部损失','直接损失')}
        edits = []
        for target in payload['issues']:
            anchor, = target['evidence']
            ref = anchor['ref']
            edit = dict(event_ids=[target['event_id']],ref=ref,operation='replace',before_text=anchor['quote'],
                        after_text=after[ref],rationale='依据本条调整。',requires_context=ref=='b1')
            if ref=='b3':
                edit['after_text']='2.1 收到发票后99日内付款。'
            edits.append(edit)
        return schema(proposals=edits,pending=[]),None

    monkeypatch.setattr(agent,'baseline_review',baseline)
    monkeypatch.setattr(agent.liability_limit,'run_limit',limit)
    monkeypatch.setattr(agent,'extract_call',local_call)
    q=client.post(f'/api/v1/contracts/{cid}/reviews',json={'idempotency_key':'configured-candidates'})
    assert q.status_code==202,q.text
    rid=q.json()['id']
    assert tick(Store(path),Settings('http://test','fake'))
    run=client.get(f'/api/v1/runs/{rid}').json()
    assert run['stage']=='done' and not run['module_errors']
    assert sorted(len(b['issues']) for b in batches if 'issues' in b)==[1,3]
    retry, = (b for b in batches if 'issue' in b)
    assert retry['issue']['event_id']=='RL-01' and '99' in retry['validation_feedback']
    assert run['execution_phases']['drafting']['state']=='completed'
    proposals={p['event_ids'][0]:p for p in run['revision_proposals']}
    assert len(proposals)==4
    clauses={issue['clause_number']:proposals[issue['event_id']] for issue in run['issues'] if issue['clause_number']}
    assert clauses['1.1']['anchor']['quote']==daily
    assert clauses['1.1']['state']=='context_required' and '【待确认累计上限】' in clauses['1.1']['after_text']
    assert '超过90日' in clauses['1.1']['after_text']
    assert clauses['1.4']['anchor']['quote']==refund
    assert '退还' not in clauses['1.4']['after_text'] and '5%' in clauses['1.4']['after_text']
    assert proposals['RL-01']['after_text']=='2.1 收到发票后15日内付款。'
    events=client.get(f'/api/v1/runs/{rid}/execution-events').json()['events']
    limit_events=[e['type'] for e in events if e['payload'].get('task_id')=='base:liability-limit']
    assert limit_events==['task_discovered','task_started','task_completed']
    first_draft=next(e['seq'] for e in events if e['type']=='phase_updated' and e['payload']['phase']['id']=='drafting')
    rule_updates=[e['payload'] for e in events if e['type']=='issue_upserted' and e['payload']['issue']['rule_id']=='RL-01']
    assert any(update['issue'].get('revision_plan',{}).get('state')=='generating' for update in rule_updates)
    assert next(u for u in rule_updates if u['proposals'])['issue']['revision_plan']['state']=='ready'
    assert any('单独补拟' in u['issue'].get('revision_plan',{}).get('message','') for u in rule_updates)
    assert any('等待核对跨条冲突' in u['issue'].get('revision_plan',{}).get('message','') and not u['proposals'] for u in rule_updates)
    assert all(u['issue']['review_state']=='reviewed' for u in rule_updates)
    for number in ('1.1','1.4'):
        updates=[e for e in events if e['type']=='issue_upserted' and e['payload']['issue'].get('clause_number')==number]
        assert updates[0]['seq']<first_draft and updates[0]['payload']['proposals']==[]
        assert updates[-1]['payload']['proposals']==[clauses[number]]
        assert updates[0]['payload']['issue']['id']==updates[-1]['payload']['issue']['id']
    availability=client.get(f'/api/v1/runs/{rid}/proposal-availability').json()
    assert all('MODIFY' in availability['proposals'][p['id']]['modes'] for p in proposals.values())
