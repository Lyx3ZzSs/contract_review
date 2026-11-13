"""Append-only quality feedback; never changes workflow decisions or active rules."""
import json
from datetime import datetime, timezone
from hashlib import sha256
from typing import Annotated, Literal
from uuid import uuid4
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def now():
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class Anchor(BaseModel):
    model_config = ConfigDict(extra='forbid')
    block_id: str = Field(min_length=1)
    start: int = Field(ge=0, strict=True)
    end: int = Field(ge=0, strict=True)
    quote: str


ExactText = Annotated[str, StringConstraints(strip_whitespace=False)]


class Feedback(StrictModel):
    idempotency_key: str = Field(min_length=1, max_length=100)
    issue_id: str | None = None
    proposal_id: str | None = None
    event_anchor: Anchor | None = None
    verdict: Literal['agree','modify_suggestion','false_positive','not_applicable','business_acceptance','missed_issue']
    reason: str = Field(default='', max_length=10000)
    corrected_text: ExactText | None = Field(default=None, max_length=50000)
    basis_refs: list[str] = Field(default_factory=list, max_length=100)
    actor: str = Field(min_length=1, max_length=100)
    document_version_id: str = Field(min_length=1)

    @model_validator(mode='after')
    def requirements(self):
        if self.verdict == 'modify_suggestion' and self.corrected_text is None:
            raise ValueError('修改建议必须填写修订内容，删除可填写空字符串')
        if self.verdict in ('false_positive','not_applicable','business_acceptance','missed_issue') and not self.reason:
            raise ValueError('必须填写原因或漏审意见')
        if self.verdict == 'missed_issue' and not self.event_anchor:
            raise ValueError('漏审必须提供当前审查版本的原文锚点')
        if self.verdict != 'missed_issue' and not self.issue_id:
            raise ValueError('必须关联本轮审查事项')
        return self


def register(app, store):
    @app.post('/api/v1/runs/{rid}/legal-feedback', status_code=201)
    def create(rid: str, body: Feedback):
        payload = body.model_dump()
        fingerprint = sha256(encoded(payload).encode()).hexdigest()
        with store.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
            if not row:
                raise HTTPException(404, '审查批次不存在')
            old = db.execute('SELECT * FROM legal_feedback WHERE run_id=? AND idem=?', (rid, body.idempotency_key)).fetchone()
            if old:
                if old['request_hash'] != fingerprint:
                    raise HTTPException(409, '提交标识已用于不同反馈')
                return json.loads(old['payload'])
            run = json.loads(row['payload'])
            if body.document_version_id != row['version_id']:
                raise HTTPException(422, '反馈版本必须与本轮审查版本一致')
            issues = run.get('issues', []) + run.get('findings', [])
            if body.issue_id and not any(i.get('id') == body.issue_id for i in issues):
                raise HTTPException(422, '事项不属于本轮审查')
            if body.proposal_id and not any(p.get('proposal_id') == body.proposal_id for p in run.get('revision_proposals', [])):
                raise HTTPException(422, '修改建议不属于本轮审查')
            if body.event_anchor:
                doc = db.execute('SELECT parsed FROM versions WHERE id=?', (row['version_id'],)).fetchone()
                blocks = json.loads(doc['parsed']).get('blocks', [])
                anchor = body.event_anchor
                block = next((b for b in blocks if b['id'] == anchor.block_id), None)
                if block is None or not (0 <= anchor.start <= anchor.end <= len(block['text'])) or block['text'][anchor.start:anchor.end] != anchor.quote:
                    raise HTTPException(422, '锚点无法在本轮原文中核验')
                if body.verdict == 'missed_issue' and not anchor.quote:
                    raise HTTPException(422, '漏审须引用真实原文位置')
            result = {**payload, 'id': str(uuid4()), 'run_id': rid, 'state':'candidate',
                      'actor_authentication':'self_reported', 'applies_to_new_versions':False, 'created_at':now()}
            db.execute('INSERT INTO legal_feedback VALUES(?,?,?,?,?,?)', (result['id'], rid, body.idempotency_key, fingerprint, encoded(result), result['created_at']))
            return result

    @app.get('/api/v1/runs/{rid}/legal-feedback')
    def history(rid: str):
        with store.connect() as db:
            if not db.execute('SELECT 1 FROM runs WHERE id=?', (rid,)).fetchone():
                raise HTTPException(404, '审查批次不存在')
            return {'items':[json.loads(row[0]) for row in db.execute('SELECT payload FROM legal_feedback WHERE run_id=? ORDER BY created_at,id', (rid,))]}
