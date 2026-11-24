"""Version-bound company checks. Provider calls never run inside a DB transaction."""
import json
import re
from datetime import datetime, timezone
from functools import wraps
from threading import RLock
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field
from . import tianyancha

_request_lock = RLock()
CACHE_SECONDS = 86400


def serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with _request_lock:
            return fn(*args, **kwargs)
    return wrapped


def now():
    return datetime.now(timezone.utc).isoformat()


def fresh(stamp):
    if not stamp:
        return False
    return 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(stamp)).total_seconds() < CACHE_SECONDS


def dump(value):
    return json.dumps(value, ensure_ascii=False)


def normalize(value):
    return re.sub(r'\s+', '', value).replace('（', '(').replace('）', ')')


class Request(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    document_version_id: str
    refresh: bool = False


class Decision(BaseModel):
    action: str = Field(pattern='^(confirmed|needs_material|reviewed)$')
    note: str = Field(default='', max_length=2000)


def source(db, cid, vid):
    contract = db.execute('SELECT payload FROM contracts WHERE id=?', (cid,)).fetchone()
    version = db.execute('SELECT contract_id FROM versions WHERE id=?', (vid,)).fetchone()
    if not contract or not version or version['contract_id'] != cid:
        raise HTTPException(404, '合同或文档版本不存在')
    latest = db.execute('SELECT id FROM versions WHERE contract_id=? ORDER BY revision DESC LIMIT 1', (cid,)).fetchone()[0]
    if latest != vid:
        raise HTTPException(409, '正文版本已变化，请重新打开主体审查')
    return json.loads(contract[0])


def public(row):
    payload = json.loads(row['payload'])
    payload.update(id=row['id'], created_at=row['created_at'])
    # Older placeholder snapshots were never queried. Do not interpret them as permission failures.
    for key, (label, api_id) in tianyancha.RISKS.items():
        module = payload['modules'].get(key)
        if not module or (not module.get('queried_at') and not module.get('last_attempt_at') and 'provider_code' not in module):
            payload['modules'][key] = {'label': label, 'api_id': api_id, 'state': 'not_queried', 'message': '尚未查询', 'data': None}
    return payload


def export_subjects(db, cid, vid):
    rows = db.execute('SELECT * FROM subject_checks WHERE contract_id=? AND version_id=? ORDER BY created_at DESC', (cid, vid)).fetchall()
    seen, result = set(), []
    for row in rows:
        payload = public(row)
        if payload['name'] not in seen:
            seen.add(payload['name'])
            result.append(payload)
    return result


def current_check(db, ident):
    row = db.execute('SELECT * FROM subject_checks WHERE id=?', (ident,)).fetchone()
    if not row:
        raise HTTPException(404, '主体查询不存在')
    source(db, row['contract_id'], row['version_id'])
    return public(row)


def require_match(payload):
    if not payload['matched'] or payload['basic']['state'] != 'ready':
        raise HTTPException(409, '请先核对企业匹配结果')


def register(app, store):
    with store.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS subject_checks(id TEXT PRIMARY KEY,contract_id TEXT NOT NULL REFERENCES contracts(id),version_id TEXT NOT NULL REFERENCES versions(id),name TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL)')
        db.execute('CREATE INDEX IF NOT EXISTS subject_contract ON subject_checks(contract_id,version_id,name)')

    @app.get('/api/v1/contracts/{cid}/subjects')
    def subjects(cid: str):
        with store.connect() as db:
            contract = db.execute('SELECT payload FROM contracts WHERE id=?', (cid,)).fetchone()
            if not contract:
                raise HTTPException(404, '合同不存在')
            contract = json.loads(contract[0])
            version = db.execute('SELECT id FROM versions WHERE contract_id=? ORDER BY revision DESC LIMIT 1', (cid,)).fetchone()
            if not version:
                raise HTTPException(409, '请先上传正文')
            return {'version_id': version[0], 'parties': contract.get('party_details', {}), 'checks': export_subjects(db, cid, version[0])}

    @app.post('/api/v1/contracts/{cid}/subjects')
    @serialized
    def check(cid: str, body: Request):
        name = body.name.strip()
        if len(name) < 2:
            raise HTTPException(422, '请填写完整企业名称')
        with store.connect() as db:
            source(db, cid, body.document_version_id)
            old = db.execute('SELECT * FROM subject_checks WHERE contract_id=? AND version_id=? AND name=? ORDER BY created_at DESC LIMIT 1', (cid, body.document_version_id, name)).fetchone()
            if old and not body.refresh and fresh(old['created_at']):
                payload = public(old)
                if payload['basic']['state'] == 'ready':
                    return payload
        basic = tianyancha.query('basic', name)
        data = basic.get('data') or {}
        exact = basic['state'] == 'ready' and normalize(str(data.get('name', ''))) == normalize(name)
        stamp, ident = now(), str(uuid4())
        payload = {'name': name, 'version_id': body.document_version_id, 'basic': basic, 'matched': exact, 'binding': 'exact_name' if exact else 'needs_confirmation', 'modules': {}, 'decision': None, 'source': '天眼查', 'queried_at': stamp}
        for key, (label, api_id) in tianyancha.RISKS.items():
            payload['modules'][key] = {'label': label, 'api_id': api_id, 'state': 'not_queried', 'message': '尚未查询', 'data': None}
        with store.connect() as db:
            source(db, cid, body.document_version_id)
            db.execute('INSERT INTO subject_checks VALUES(?,?,?,?,?,?)', (ident, cid, body.document_version_id, name, dump(payload), stamp))
        return {**payload, 'id': ident, 'created_at': stamp}

    @app.post('/api/v1/subject-checks/{ident}/modules/{module}')
    @serialized
    def module(ident: str, module: str, page: int = 1, refresh: bool = False):
        if module not in tianyancha.MODULES or page < 1 or (module not in tianyancha.PAGED and page != 1) or (refresh and page != 1):
            raise HTTPException(422, '不支持的查询项目或页码')
        with store.connect() as db:
            payload = current_check(db, ident)
            require_match(payload)
            prior = payload['modules'].get(module, {})
            pages = prior.get('pages', {})
            valid_cache = fresh(prior.get('queried_at'))
            if not refresh and valid_cache and prior.get('state') in ('ready', 'empty') and str(page) in pages:
                return payload
            if page > 1:
                if not valid_cache:
                    raise HTTPException(409, '查询结果已过期，请更新该项后再加载更多')
                if str(page - 1) not in pages or (page - 1) * tianyancha.PAGE_SIZE >= (prior.get('data') or {}).get('total', 0):
                    raise HTTPException(422, '请按顺序加载有效页码')
            keyword = str(payload['basic']['data']['id'])
        result = tianyancha.query(module, keyword, page)
        stamp = now()
        result.update(label=tianyancha.ENDPOINTS[module][0], api_id=tianyancha.ENDPOINTS[module][1], last_attempt_at=stamp)
        with store.connect() as db:
            payload = current_check(db, ident)
            prior = payload['modules'].get(module, {})
            succeeded = result['state'] in ('ready', 'empty')
            if succeeded:
                pages = {} if page == 1 else dict(prior.get('pages', {}))
                if page > 1 and result['data']['total'] != prior['data']['total']:
                    result.update(state='failed', message='分页记录总数已变化，请更新该项后重新查询', data=None)
                    succeeded = False
                else:
                    pages[str(page)] = result['data']
                    result.update(pages=pages, queried_at=stamp if page == 1 else prior['queried_at'])
                    if page > 1 and 'details' in prior:
                        result['details'] = prior['details']
            if not succeeded:
                # Keep earlier successful pages with their original timestamp and an explicit failed-attempt state.
                result.update(pages=prior.get('pages', {}), data=prior.get('data'), queried_at=prior.get('queried_at'))
                if 'details' in prior:
                    result['details'] = prior['details']
            payload['modules'][module] = result
            db.execute('UPDATE subject_checks SET payload=? WHERE id=?', (dump(payload), ident))
        return payload

    @app.post('/api/v1/subject-checks/{ident}/bankruptcy/{case_id}')
    @serialized
    def bankruptcy_detail(ident: str, case_id: str):
        with store.connect() as db:
            payload = current_check(db, ident)
            require_match(payload)
            module = payload['modules'].get('bankruptcy', {})
            items = [item for page in module.get('pages', {}).values() for item in page.get('items', [])]
            if not any(str(item.get('uuid')) == case_id for item in items):
                raise HTTPException(404, '案件不属于已查询的该企业记录')
            if not fresh(module.get('queried_at')):
                raise HTTPException(409, '查询结果已过期，请先更新破产重整查询')
            cached = module.get('details', {}).get(case_id)
            if cached and cached['state'] in ('ready', 'empty'):
                return payload
            gid = str((module.get('data') or {}).get('gid') or payload['basic']['data']['id'])
        result = tianyancha.query('bankruptcy_detail', gid, detail_id=case_id)
        result['queried_at'] = now()
        with store.connect() as db:
            payload = current_check(db, ident)
            payload['modules']['bankruptcy'].setdefault('details', {})[case_id] = result
            db.execute('UPDATE subject_checks SET payload=? WHERE id=?', (dump(payload), ident))
        return payload

    @app.post('/api/v1/subject-checks/{ident}/decision')
    @serialized
    def decision(ident: str, body: Decision):
        with store.connect() as db:
            payload = current_check(db, ident)
            if body.action == 'confirmed':
                if payload['basic']['state'] != 'ready':
                    raise HTTPException(409, '没有可确认的企业信息')
                payload.update(matched=True, binding='manual_confirmed')
            if body.action == 'reviewed':
                require_match(payload)
            payload['decision'] = {**body.model_dump(), 'at': now()}
            db.execute('UPDATE subject_checks SET payload=? WHERE id=?', (dump(payload), ident))
        return payload
