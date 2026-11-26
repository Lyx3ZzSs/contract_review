"""Durable review queue and server-owned draft metadata."""
import json
import os
from hashlib import sha256
from uuid import uuid4
from datetime import datetime, timezone
from fastapi import HTTPException
from pydantic import Field, ValidationError
from typing import Literal
from .models import Model, Evidence, ExtractionCreate
from .review_policy import prompt_hash, active_version
from .rule_registry import CONFIGURED_RULES_POLICY
from .field_review import FieldObservation, classify
from .amount_review import AmountObservation, LegacyAmountObservation, classify as classify_amount


def now():return datetime.now(timezone.utc).isoformat()
def dumps(x):return json.dumps(x,ensure_ascii=False,sort_keys=True)


class Candidate(Model):
    rule_id: str
    status: str
    explanation: str = Field(min_length=1)
    evidence: list[Evidence]
    suggested_text: str | None = None


class ReviewOutput(Model):
    findings: list[Candidate] = Field(min_length=5,max_length=100)


class StructuredCandidate(Candidate):
    field_checks: list[FieldObservation] | None = None


class StructuredOutput(Model):
    findings: list[StructuredCandidate] = Field(min_length=5,max_length=100)


class ComputedCandidate(StructuredCandidate):
    status: Literal['flag','no_flag_for_target_rule','insufficient_evidence','not_applicable']
    amount_checks: list[LegacyAmountObservation] | None = None


class ComputedOutput(Model):
    findings: list[ComputedCandidate] = Field(min_length=5,max_length=100)


class CalibratedCandidate(ComputedCandidate):
    amount_checks: list[AmountObservation] | None = None


class CalibratedOutput(Model):
    findings: list[CalibratedCandidate] = Field(min_length=5,max_length=100)


def output_schema(version):
    if version == CONFIGURED_RULES_POLICY:
        from .configured_review import ConfiguredRulesSchema
        return ConfiguredRulesSchema
    if version in ('redlines-v6','redlines-v7'):
        from .structured_review import PipelineSchema
        return PipelineSchema
    return (CalibratedOutput if version=='redlines-v5' else ComputedOutput if version=='redlines-v4' else StructuredOutput if version=='redlines-v3' else ReviewOutput)


def schema_hash(version):
    return sha256(dumps(output_schema(version).model_json_schema()).encode()).hexdigest()


STAGES = {
    'queued':'等待后台处理', 'preparing':'正在准备合同与审查规则',
    'extracting':'正在识别附件引用、金额关系和关键字段',
    'checking':'正在核验基础规则与责任条款',
    'validating':'正在核对证据并整理结果', 'done':'AI 审查完成，待人工复核',
}


def set_stage(payload, stage):
    if stage not in STAGES:raise ValueError('未知审查阶段')
    timestamp=now()
    payload.update(stage=stage,progress=STAGES[stage],stage_updated_at=timestamp)
    history=payload.setdefault('stage_history',[])
    if not history or history[-1]['stage']!=stage:
        history.append({'stage':stage,'started_at':timestamp})


def enqueue_review(db,cid,body,*,bundle=None,parent_run_id=None,interactive=None):
    from .llm import Settings
    settings = Settings.load()
    model=body.model or settings.model
    policy_version=active_version()
    from .rule_registry import rule_snapshot
    from .configured_review import implementation_hash
    c=db.execute('SELECT * FROM contracts WHERE id=?',(cid,)).fetchone()
    if not c:raise HTTPException(404,'合同不存在')
    doc=db.execute('SELECT * FROM versions WHERE contract_id=? ORDER BY revision DESC LIMIT 1',(cid,)).fetchone()
    if not doc:raise HTTPException(422,'尚无正文')
    from .materials import current_bundle,ensure_bundle
    current=current_bundle(db,cid)
    enabled=os.getenv('RIXIN_INTERACTIVE_REVIEW','0')=='1'
    interactive=enabled if interactive is None else interactive
    if (interactive or current) and not enabled:
        raise HTTPException(503,'交互式资料包审查暂未启用；已有材料不能退回仅正文审查')
    if body.document_version_id and body.document_version_id!=doc['id']:
        raise HTTPException(409,'正文版本已变化，请刷新后重新审查')
    context={k:json.loads(c['payload'])[k] for k in ('our_party','stage')}
    from zoneinfo import ZoneInfo
    from .review_context import normalize_review_context
    from .liability_limit import project_confirmation

    context = normalize_review_context(context)
    confirmation = project_confirmation(cid, datetime.now(ZoneInfo('Asia/Shanghai')).date())
    if confirmation:
        context['liability_confirmation'] = confirmation
    if interactive:
        bundle = bundle or ensure_bundle(db, cid, doc['id'])
    fingerprint = {'version': doc['id'], 'model': model, 'bundle': bundle['id'] if bundle else None,
                   'context': context, 'policy': policy_version}
    request_hash=sha256(dumps(fingerprint).encode()).hexdigest()
    old=db.execute('SELECT * FROM runs WHERE contract_id=? AND idem=?',(cid,body.idempotency_key)).fetchone()
    if old:
        if old['request_hash']!=request_hash:raise HTTPException(409,'幂等键已用于不同审查')
        return json.loads(old['payload'])
    active=db.execute("SELECT payload FROM runs WHERE contract_id=? AND status IN ('queued','running') AND version_id=?",(cid,doc['id'])).fetchall()
    if any(json.loads(row['payload']).get('model')==model and json.loads(row['payload']).get('material_bundle_id')==(bundle['id'] if interactive else None) for row in active):
        raise HTTPException(409,'当前版本已有审查任务，请刷新查看进度')
    rid=str(uuid4())
    payload = {
        'id': rid, 'contract_id': cid, 'document_version_id': doc['id'], 'document_sha256': doc['sha256'],
        'created_at': now(), 'status': 'queued', 'mode': 'model_review',
        'rule_snapshot': rule_snapshot(policy_version),
        'request': {'document_version_id': doc['id'], 'idempotency_key': body.idempotency_key,
                    'facts': None, 'extraction_id': None},
        'engine_version': 'interactive-review-v3', 'result_schema_version': 'interactive-review-v3',
        'review_prompt_version': policy_version, 'review_prompt_sha256': prompt_hash(policy_version),
        'review_schema_sha256': schema_hash(policy_version), 'review_implementation_sha256': implementation_hash(),
        'extraction_status': 'pending', 'coverage': 'parsed_document_only',
        'findings': [], 'error': None, 'progress': '等待后台处理', 'model': model,
        'context_snapshot': context, 'issues': [], 'rule_results': [], 'module_errors': [],
        'diagnostics': {}, 'parent_run_id': parent_run_id, 'revision_proposals': [],
    }
    if bundle:
        payload.update(material_bundle_id=bundle['id'], coverage='parsed_material_bundle')
    set_stage(payload,'queued')
    db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)',(rid,cid,doc['id'],body.idempotency_key,request_hash,'queued',dumps(payload),payload['created_at']))
    db.execute('INSERT INTO jobs(id,run_id,state,attempts) VALUES(?,?,?,0)',(rid,rid,'queued'))
    return payload


def restore_overview(db, run):
    """Older workers persisted verified overview sections only in the execution snapshot."""
    if run.get('analysis_artifacts') or run.get('status') not in ('needs_input','completed'):
        return run
    row = db.execute("""SELECT json_extract(payload, '$.artifacts.transaction-overview')
                        FROM review_execution_states WHERE run_id=?""", (run['id'],)).fetchone()
    if not row or not row[0]:
        return run
    overview = json.loads(row[0])
    if overview.get('state') in ('completed','failed'):
        run['analysis_artifacts'] = {'transaction-overview':overview}
    if overview.get('state') == 'failed':
        errors = run.get('module_errors') or []
        if not any(e.get('module')=='transaction-overview' for e in errors):
            errors.append({'module':'transaction-overview','code':'overview_incomplete',
                           'message':overview.get('message') or '交易分析未完整结束。'})
        run.update(module_errors=errors,stage='partial',progress='部分检查未完成，待人工复核')
    return run


def register(app,store):
    @app.post('/api/v1/contracts/{cid}/reviews',status_code=202)
    def enqueue(cid:str,body:ExtractionCreate):
        with store.connect() as db:
            return enqueue_review(db,cid,body)

    @app.get('/api/v1/contracts/{cid}/reviews')
    def history(cid:str):
        with store.connect() as db:
            if not db.execute('SELECT id FROM contracts WHERE id=?',(cid,)).fetchone():raise HTTPException(404,'合同不存在')
            from .materials import is_stale, is_context_stale
            values=[json.loads(r['payload']) for r in db.execute('SELECT payload FROM runs WHERE contract_id=? ORDER BY created_at DESC',(cid,))]
            return [restore_overview(db,v)|{'stale':is_stale(db,v),'context_stale':is_context_stale(db,v)} for v in values]

    @app.get('/api/v1/contracts/{cid}/results')
    def results(cid:str):
        with store.connect() as db:
            return [json.loads(r['payload']) for r in db.execute('SELECT results.payload FROM results JOIN runs ON runs.id=results.run_id WHERE runs.contract_id=? ORDER BY results.created_at DESC',(cid,))]

    @app.get('/api/v1/contracts/{cid}/draft-state')
    def get_state(cid:str):
        with store.connect() as db:
            row=db.execute('SELECT payload FROM draft_states WHERE contract_id=?',(cid,)).fetchone()
            return json.loads(row['payload']) if row else None


def review(settings,model,blocks,context,rules,*,prompt_version='redlines-v7',progress_callback=None):
    import httpx
    from .llm import ExtractionError
    from .review_policy import PROMPTS
    if not prompt_version.startswith('redlines-') or prompt_version not in PROMPTS:raise ExtractionError('unknown_prompt','未知审查口径版本，未执行。')
    if prompt_version in ('redlines-v6','redlines-v7'):
        from .structured_review import review_structured
        return review_structured(settings,model,blocks,context,rules,indexed=prompt_version=='redlines-v7',progress_callback=progress_callback)
    if progress_callback:progress_callback('checking')
    instructions=PROMPTS[prompt_version]
    output_type=output_schema(prompt_version)
    content={'schema':output_type.model_json_schema(),'context':context,'rules':rules,'blocks':blocks}
    if len(dumps(content))>80000:raise ExtractionError('input_too_large','正文超过当前单次审查上限，未截断；请拆分资料。')
    try:
        with httpx.Client(timeout=httpx.Timeout(settings.timeout,connect=10),trust_env=False) as client:
            r=client.post(settings.base_url+'/chat/completions',headers={'Authorization':'Bearer '+settings.api_key},json={
                'model':model,'messages':[{'role':'system','content':instructions},{'role':'user','content':dumps(content)}],
                'max_tokens':8192,'stream':False})
        if r.status_code!=200:raise ExtractionError('gateway_http_error',f'模型网关HTTP {r.status_code}')
        data=r.json();choice=data['choices'][0]
        if choice.get('finish_reason')!='stop':raise ExtractionError('incomplete_output','模型输出不完整，未采纳。')
        content=choice['message']['content'].strip()
        # Some gateways wrap a JSON object in one Markdown code fence. Strip only
        # this complete wrapper; all schema, coverage and quote checks still apply.
        lines=content.splitlines()
        if len(lines)>=3 and lines[0] in ('```json','```') and lines[-1]=='```':
            content='\n'.join(lines[1:-1])
        output=output_type.model_validate_json(content)
        allowed={r['id'] for r in rules}
        if {f.rule_id for f in output.findings}!=allowed:raise ValueError('规则覆盖不完整')
        texts={b['id']:b['text'] for b in blocks}
        records=[]
        for f in output.findings:
            if f.status not in ('flag','no_flag_for_target_rule','insufficient_evidence','not_applicable'):raise ValueError('状态无效')
            if f.status=='flag' and not f.evidence:raise ValueError('风险缺少证据')
            observations=getattr(f,'field_checks',None)
            if prompt_version in ('redlines-v3','redlines-v4','redlines-v5') and f.rule_id=='RL-05' and observations is None:raise ValueError('RL-05缺少结构化观察')
            if observations and f.rule_id!='RL-05':raise ValueError('字段观察不能用于其他规则')
            evidence=f.evidence+[e for item in observations or [] for e in item.evidence+item.requirement_evidence]
            amount_observations=getattr(f,'amount_checks',None)
            if prompt_version in ('redlines-v4','redlines-v5') and f.rule_id=='RL-02' and amount_observations is None:raise ValueError('RL-02缺少计算观察')
            if amount_observations and f.rule_id!='RL-02':raise ValueError('计算观察不能用于其他规则')
            evidence += [e for item in amount_observations or [] for e in item.evidence]
            for e in evidence:
                if e.block_id not in texts or texts[e.block_id].count(e.quote)!=1:raise ValueError('证据不存在或不唯一')
                e.start=texts[e.block_id].index(e.quote);e.end=e.start+len(e.quote)
            if len(f.evidence)!=1:f.suggested_text=None
            value=f.model_dump(mode='json')
            if prompt_version in ('redlines-v3','redlines-v4','redlines-v5') and f.rule_id=='RL-05':
                if not observations and f.status in ('flag','insufficient_evidence'):raise ValueError('缺项状态没有字段观察')
                value['model_proposed_status']=f.status;value['model_explanation']=f.explanation
                value['status'],value['explanation']=classify(observations)
                if value['status']!=f.status or value['status']!='flag':value['suggested_text']=None
                # All cited observations remain locatable and inspectable.
                unique={(e.block_id,e.start,e.end,e.quote):e.model_dump(mode='json') for e in evidence}
                value['evidence']=list(unique.values())
                if len(value['evidence'])!=1:value['suggested_text']=None
            if prompt_version in ('redlines-v4','redlines-v5') and f.rule_id=='RL-02':
                if not amount_observations and f.status in ('flag','insufficient_evidence'):raise ValueError('金额问题没有计算观察')
                value['model_proposed_status']=f.status;value['model_explanation']=f.explanation
                value['status'],value['explanation'],value['computed_calculations']=classify_amount(amount_observations)
                value['suggested_text']=None
                value['evidence']=list({(e.block_id,e.start,e.end,e.quote):e.model_dump(mode='json') for e in evidence}.values())
            records.append(value)
        if progress_callback:progress_callback('validating')
        return records
    except ExtractionError:raise
    except httpx.TimeoutException:raise ExtractionError('gateway_timeout','模型调用超时，请重试。') from None
    except Exception as exc:
        error=ExtractionError('invalid_review','审查输出格式、规则覆盖或证据校验失败，未采纳。')
        # Diagnostic paths and fixed validator messages only; never echo model text.
        if isinstance(exc,ValidationError):
            error.diagnostics=[{'type':e['type'],'location':list(e['loc'])} for e in exc.errors()]
        elif type(exc) is ValueError and str(exc) in ('规则覆盖不完整','状态无效','风险缺少证据','RL-05缺少结构化观察','字段观察不能用于其他规则','RL-02缺少计算观察','计算观察不能用于其他规则','证据不存在或不唯一','缺项状态没有字段观察','金额问题没有计算观察'):
            error.diagnostics=[{'type':'semantic_validation','reason':str(exc)}]
        raise error from None
