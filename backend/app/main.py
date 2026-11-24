from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4
import json
import logging
import os
from typing import Literal
from .review_policy import execution_policy
from .rule_catalog import presentation, cases_for
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Depends
from .auth import authorize_resources, install as install_auth, owner_sub, visible, review_author
from fastapi.responses import Response
from .models import ContractCreate, RunCreate, DecisionCreate, Complete, Facts, VersionView, RunView, DecisionView, ResultView, ExtractionCreate, ExtractionView
from .store import Store
from .engine import check
from . import llm

ROOT = Path(__file__).resolve().parents[2]
logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def required(db, table, key):
    # Table names are internal constants, never user input.
    row = db.execute(f'SELECT * FROM {table} WHERE id=?', (key,)).fetchone()
    if row is None:
        raise HTTPException(404, '记录不存在')
    return row


def current_version(db, contract_id):
    r = db.execute('SELECT id FROM versions WHERE contract_id=? ORDER BY revision DESC LIMIT 1', (contract_id,)).fetchone()
    return r['id'] if r else None


def create_app(db_path=None):
    store = Store(db_path or os.getenv('RIXIN_DB', str(ROOT / 'backend/data/review.sqlite3')))
    settings = llm.Settings.load()
    rule_data = json.loads((ROOT / 'analysis/legal-corpus/draft-v0.1/rules.json').read_text())
    core = [r for r in rule_data['rules'] if r['id'].startswith('RL-')]
    snapshot = {'version': rule_data['version'], 'pack_sha256': rule_data['pack_sha256'], 'rules': core}
    app = FastAPI(dependencies=[Depends(authorize_resources)], title='日新法务后端开发 API', version='0.1.0',
                  description='本地开发服务。持久化、已核实事实检查、模型候选审查与人工处理记录；已接入公司统一身份认证；尚无生产规则发布。')
    app.state.store = store
    install_auth(app, store)
    from .subject_review import register as register_subjects
    register_subjects(app, store)
    from .exports import register as register_exports
    register_exports(app, store)
    from .legal_feedback import register as register_feedback
    from .legal_casebook import register as register_casebook
    from .proposal_operations import register as register_proposal_operations
    register_proposal_operations(app, store)
    from .proposal_rechecks import register as register_proposal_rechecks
    register_proposal_rechecks(app, store)
    register_feedback(app,store)
    register_casebook(app,store)
    from .review_records import register as register_records
    register_records(app, store)
    from .parties import register as register_parties
    register_parties(app, store)

    @app.get('/health')
    def health():
        return {'status': 'ok', 'mode': 'local_development', 'semantic_extraction': 'configured' if settings.api_key and settings.base_url else 'not_configured'}

    @app.get('/api/v1/rules')
    def rules():
        from .rule_registry import rule_snapshot
        policy=execution_policy()
        current=rule_snapshot(policy['version'])
        display=presentation()
        display['items']={k:v for k,v in display['items'].items() if k in {r['id'] for r in current['rules']}}
        display['current_scope']='仅执行本页列出的规则。累计责任按已配置口径核对，项目口径未确认时显示待核实。'
        return {**current, 'execution_policy': policy, 'presentation': display}

    @app.get('/api/v1/rules/{rule_id}/cases')
    def rule_cases(rule_id: str):
        return cases_for(rule_id)

    @app.post('/api/v1/contracts', status_code=201)
    def create_contract(body: ContractCreate):
        value = {'id': str(uuid4()), **body.model_dump(), 'owner_sub': owner_sub(), 'created_at': now()}
        with store.connect() as db:
            db.execute('INSERT INTO contracts VALUES(?,?,?)', (value['id'], encoded(value), value['created_at']))
        return value

    @app.get('/api/v1/contracts')
    def contracts(data_purpose: Literal['business', 'test', 'all'] = 'business'):
        with store.connect() as db:
            values = [json.loads(r['payload']) for r in db.execute('SELECT payload FROM contracts ORDER BY created_at DESC')]
            return [v for v in values if visible(v) and (data_purpose == 'all' or v.get('data_purpose', 'business') == data_purpose)]

    @app.get('/api/v1/contracts/{contract_id}')
    def contract(contract_id: str):
        with store.connect() as db:
            value = json.loads(required(db, 'contracts', contract_id)['payload'])
            value['current_document_version_id'] = current_version(db, contract_id)
            value['versions'] = [dict(r) for r in db.execute('SELECT id,revision,sha256,filename,created_at FROM versions WHERE contract_id=? ORDER BY revision', (contract_id,))]
            return value

    @app.get('/api/v1/contracts/{contract_id}/editor-state')
    def editor_state(contract_id: str):
        # Store.connect owns one transaction, so bytes selected by this version
        # cannot be paired with another save's draft state or result history.
        with store.connect() as db:
            required(db, 'contracts', contract_id)
            version_id = current_version(db, contract_id)
            state = db.execute('SELECT payload FROM draft_states WHERE contract_id=?', (contract_id,)).fetchone()
            results = [json.loads(r['payload']) for r in db.execute(
                'SELECT results.payload FROM results JOIN runs ON runs.id=results.run_id WHERE runs.contract_id=? ORDER BY results.created_at DESC',
                (contract_id,))]
            return {'document_version_id': version_id, 'draft_state': json.loads(state['payload']) if state else None, 'results': results}

    @app.post('/api/v1/contracts/{contract_id}/versions', status_code=201, response_model=VersionView)
    async def upload(contract_id: str, file: UploadFile = File(...), expected_version_id: str | None = Form(None), draft_state: str | None = Form(None)):
        from .document_import import document
        name, content, parsed = await document(file, store)
        state = None
        if draft_state:
            try:
                if len(draft_state)>1000000: raise ValueError()
                state=json.loads(draft_state)
                if not isinstance(state,dict): raise ValueError()
            except Exception: raise HTTPException(422,'草稿状态格式无效')
        from .document_versions import commit_version
        with store.connect() as db:
            return commit_version(db,contract_id,content,name,parsed,expected_version_id,state)

    @app.get('/api/v1/versions/{version_id}', response_model=VersionView)
    def version(version_id: str):
        with store.connect() as db:
            row = required(db, 'versions', version_id)
            from .clause_structure import version_structure
            parsed=version_structure(json.loads(row['parsed']),version_id)
            return {k: row[k] for k in ('id','contract_id','revision','sha256','filename','created_at')} | parsed

    @app.get('/api/v1/versions/{version_id}/file')
    def download(version_id: str):
        with store.connect() as db:
            row = required(db, 'versions', version_id)
            return Response(row['content'], media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                            headers={'Content-Disposition': f'attachment; filename="{version_id}.docx"'})

    @app.get('/api/v1/models')
    def models():
        return {'configured': bool(settings.api_key and settings.base_url),
                'default': settings.model, 'available': list(llm.ALLOWED_MODELS)}

    @app.post('/api/v1/versions/{version_id}/extractions', status_code=201, response_model=ExtractionView)
    def extract_version(version_id: str, body: ExtractionCreate):
        if not settings.api_key or not settings.base_url:
            raise HTTPException(503, '模型接口尚未配置')
        model = body.model or settings.model
        fingerprint = sha256(encoded({'model': model}).encode()).hexdigest()
        with store.connect() as db:
            doc = required(db, 'versions', version_id)
            previous = db.execute('SELECT * FROM extractions WHERE version_id=? AND idem=?',
                                  (version_id, body.idempotency_key)).fetchone()
            if previous:
                if previous['request_hash'] != fingerprint:
                    raise HTTPException(409, '幂等键已用于不同模型')
                return json.loads(previous['payload'])
            if current_version(db, doc['contract_id']) != version_id:
                raise HTTPException(409, '请基于最新文档抽取')
            contract_data = json.loads(required(db, 'contracts', doc['contract_id'])['payload'])
            context = {k: contract_data[k] for k in ('our_party','stage')}
            blocks = json.loads(doc['parsed'])['blocks']
            value = {'id':str(uuid4()), 'document_version_id':version_id, 'document_sha256':doc['sha256'],
                     'model':model, 'prompt_version':llm.PROMPT_VERSION, 'status':'running',
                     'origin':'model_extracted', 'created_at':now(), 'evidence_validation':'not_checked',
                     'input_sha256':sha256(encoded(llm.messages(blocks,context)).encode()).hexdigest()}
            db.execute('INSERT INTO extractions VALUES(?,?,?,?,?)',
                       (value['id'],version_id,body.idempotency_key,fingerprint,encoded(value)))
        # Never hold a SQLite transaction over the external network call.
        try:
            value.update(llm.extract(settings,model,blocks,context))
            value.update(status='needs_verification',evidence_validation='exact_quotes_verified')
        except llm.ExtractionError as exc:
            value.update(status='failed',error={'code':exc.code,'message':exc.message})
        except Exception:
            value.update(status='failed',error={'code':'extraction_error','message':'抽取发生内部错误，未采纳结果。'})
        value['finished_at'] = now()
        with store.connect() as db:
            value['stale'] = current_version(db,doc['contract_id']) != version_id
            db.execute('UPDATE extractions SET payload=? WHERE id=?', (encoded(value),value['id']))
        return value

    @app.get('/api/v1/extractions/{extraction_id}', response_model=ExtractionView)
    def extraction(extraction_id: str):
        with store.connect() as db:
            row = required(db,'extractions',extraction_id)
            value = json.loads(row['payload'])
            doc = required(db,'versions',row['version_id'])
            value['stale'] = current_version(db,doc['contract_id']) != doc['id']
            return value

    @app.post('/api/v1/contracts/{contract_id}/runs', status_code=201, response_model=RunView)
    def start(contract_id: str, body: RunCreate):
        request = body.model_dump(mode='json')
        fingerprint = sha256(encoded(request).encode()).hexdigest()
        with store.connect() as db:
            required(db, 'contracts', contract_id)
            previous = db.execute('SELECT * FROM runs WHERE contract_id=? AND idem=?', (contract_id, body.idempotency_key)).fetchone()
            if previous:
                if previous['request_hash'] != fingerprint:
                    raise HTTPException(409, '幂等键已用于不同请求')
                return json.loads(previous['payload'])
            doc = required(db, 'versions', body.document_version_id)
            if doc['contract_id'] != contract_id:
                raise HTTPException(422, '文档不属于当前合同')
            if current_version(db, contract_id) != doc['id']:
                raise HTTPException(409, '请基于最新文档版本发起审查')
            if body.extraction_id:
                extraction_row = required(db, 'extractions', body.extraction_id)
                extraction_data = json.loads(extraction_row['payload'])
                if extraction_row['version_id'] != doc['id'] or extraction_data['status'] != 'needs_verification':
                    raise HTTPException(422, '抽取记录与文档不匹配或抽取未成功')
                if body.facts is None:
                    raise HTTPException(422, '模型事实须人工核实后提交facts与verified_by')
            blocks = {b['id']: b['text'] for b in json.loads(doc['parsed'])['blocks']}
            if body.facts:
                for group in ('terms','amounts','transfers','attachments','fields'):
                    for fact in getattr(body.facts, group):
                        for ev in fact.evidence:
                            if ev.block_id not in blocks or blocks[ev.block_id][ev.start:ev.end] != ev.quote or ev.end > len(blocks[ev.block_id]):
                                raise HTTPException(422, '证据位置或原文与文档版本不匹配')
            payload = {'id': str(uuid4()), 'contract_id': contract_id, 'document_version_id': doc['id'],
                       'document_sha256': doc['sha256'], 'created_at': now(), 'status': 'queued',
                       'mode': 'development_verified_facts', 'rule_snapshot': snapshot, 'request': request,
                       'engine_version': 'verified-facts-v1', 'extraction_status': 'manual_verified' if body.facts else 'not_configured',
                       'coverage': 'submitted_facts_only', 'findings': [], 'error': None}
            db.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)', (payload['id'], contract_id, doc['id'], body.idempotency_key,
                       fingerprint, 'queued', encoded(payload), payload['created_at']))
        return payload

    @app.get('/api/v1/runs/{run_id}', response_model=RunView)
    def run(run_id: str):
        with store.connect() as db:
            value = json.loads(required(db, 'runs', run_id)['payload'])
            from .materials import is_stale, is_context_stale
            value['stale'] = is_stale(db,value)
            value['context_stale'] = is_context_stale(db,value)
            value['decisions'] = [json.loads(r['payload']) for r in db.execute('SELECT payload FROM decisions WHERE run_id=? ORDER BY id', (run_id,))]
            from .issue_presentation import enrich_run_presentation
            return enrich_run_presentation(value)

    @app.post('/api/v1/runs/{run_id}/execute', response_model=RunView)
    def execute(run_id: str):
        # Short local computations are transactional. A later worker uses the same service.
        with store.connect() as db:
            row = required(db, 'runs', run_id)
            value = json.loads(row['payload'])
            if value['mode']=='model_review':
                raise HTTPException(409,'模型审查由Worker执行，请查询进度')
            if row['status'] in ('completed', 'needs_input', 'failed'):
                return value
            if current_version(db, row['contract_id']) != row['version_id']:
                raise HTTPException(409, '正文已变化，需要新审查批次')
            try:
                data = value['request']['facts']
                stage = json.loads(required(db, 'contracts', row['contract_id'])['payload'])['stage']
                findings = check(Facts.model_validate(data) if data else None, stage)
                for idx, finding in enumerate(findings):
                    finding['id'] = f'{run_id}:f{idx+1}'
                    finding['document_version_id'] = row['version_id']
                value['findings'] = findings
                value['status'] = 'needs_input' if any(f['status'] == 'insufficient_evidence' for f in findings) else 'completed'
            except Exception:
                logger.exception('Rule execution failed: %s', run_id)
                value['status'] = 'failed'
                value['error'] = {'code': 'execution_error', 'message': '规则执行失败；不能视为无风险。'}
            value['finished_at'] = now()
            db.execute('UPDATE runs SET status=?,payload=? WHERE id=?', (value['status'], encoded(value), run_id))
            return value

    @app.post('/api/v1/runs/{run_id}/issues/{finding_id}/decisions', status_code=201, response_model=DecisionView)
    @app.post('/api/v1/runs/{run_id}/findings/{finding_id}/decisions', status_code=201, response_model=DecisionView)
    def decide(run_id: str, finding_id: str, body: DecisionCreate):
        with store.connect() as db:
            row = required(db, 'runs', run_id)
            from .materials import is_context_stale
            if is_context_stale(db,json.loads(row['payload'])):
                raise HTTPException(409, '资料包或审查主体已变化，请处理最新审查结果')
            value = json.loads(row['payload'])
            if not any(f['id'] == finding_id for f in value['findings']):
                raise HTTPException(404, '审查发现不存在')
            decision = {**body.model_dump(), **review_author('actor', body.actor), 'finding_id': finding_id, 'created_at': now()}
            db.execute('INSERT INTO decisions(run_id,finding_id,payload,created_at) VALUES(?,?,?,?)',
                       (run_id, finding_id, encoded(decision), decision['created_at']))
            return decision

    @app.post('/api/v1/runs/{run_id}/results', status_code=201, response_model=ResultView)
    def complete(run_id: str, body: Complete):
        with store.connect() as db:
            row = required(db, 'runs', run_id)
            existing = db.execute('SELECT payload FROM results WHERE run_id=?', (run_id,)).fetchone()
            if existing:
                return json.loads(existing['payload'])
            head_version_id = current_version(db, row['contract_id'])
            if body.expected_document_version_id and body.expected_document_version_id != head_version_id:
                raise HTTPException(409, '正文已有新版本，请重新加载正文后继续')
            if not head_version_id:
                raise HTTPException(409, '请先保存合同正文')
            active=db.execute("SELECT * FROM editor_sessions WHERE contract_id=? AND state IN ('open','closing')",(row['contract_id'],)).fetchone()
            if active:
                if active['id']!=body.editor_session_id or active['head_version_id']!=head_version_id:
                    raise HTTPException(409,'请在当前编辑会话确认保存后完成审阅')
                if any(json.loads(r[0])['state'] in ('pending','unconfirmed') for r in db.execute('SELECT payload FROM editor_save_requests WHERE session_id=?',(active['id'],))):
                    raise HTTPException(409,'正文保存仍未确认')
            elif body.editor_session_id:
                raise HTTPException(409,'编辑会话已结束，请重新打开文档')
            if any(json.loads(r[0]).get('state') == 'prepared' for r in db.execute(
                    'SELECT payload FROM proposal_operations WHERE contract_id=?', (row['contract_id'],))):
                raise HTTPException(409, '修改操作尚未确认，请先确认保存或撤销该操作')
            value = json.loads(row['payload'])
            if value['status'] in ('queued', 'running'):
                raise HTTPException(409, '审查任务仍在运行')
            newer = db.execute('SELECT id FROM runs WHERE contract_id=? AND created_at>?', (row['contract_id'], value['created_at'])).fetchone()
            if newer:
                raise HTTPException(409, '请标记最新一轮审阅')
            decisions = [json.loads(r['payload']) for r in db.execute('SELECT payload FROM decisions WHERE run_id=? ORDER BY id', (run_id,))]
            result = {'id': str(uuid4()), 'run_id': run_id, 'created_at': now(), **body.model_dump(exclude={'expected_document_version_id'}), **review_author('reviewer', body.reviewer),
                      'document_version_id': head_version_id, 'review_snapshot': value, 'decisions': decisions,
                      'scope': 'review_completion_record'}
            db.execute('INSERT INTO results VALUES(?,?,?,?)', (result['id'], run_id, encoded(result), result['created_at']))
            return result

    @app.get('/api/v1/results/{result_id}', response_model=ResultView)
    def result(result_id: str):
        with store.connect() as db:
            return json.loads(required(db, 'results', result_id)['payload'])

    from .review_jobs import register
    register(app,store)
    from .review_execution_events import register as register_execution
    register_execution(app,store)
    from .materials import register as register_materials
    register_materials(app,store)
    from .review_interactions import register as register_interactions
    register_interactions(app,store)
    from .onlyoffice import register as register_onlyoffice
    register_onlyoffice(app,store)
    return app
