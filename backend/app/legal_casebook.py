"""Versioned case opinions, explicit self-reported confirmation, immutable releases."""
import json
import re
from typing import Literal
from uuid import uuid4
from fastapi import HTTPException
from pydantic import Field, model_validator
from .legal_feedback import ExactText, StrictModel, encoded, now


class CaseCandidate(StrictModel):
    family_id: str | None = Field(default=None,min_length=1,max_length=200)
    source_hash: str | None = Field(default=None,pattern=r'^[a-fA-F0-9]{64}$')
    source_version_id: str | None = None
    original_span: ExactText = Field(min_length=1,max_length=50000)
    final_opinion: str = Field(min_length=1,max_length=10000)
    final_edit: ExactText | None = Field(default=None,max_length=50000)
    rationale: str = Field(default='',max_length=10000)
    basis_kind: Literal['legal_requirement','company_policy','case_negotiation']
    basis_refs: list[str] = Field(default_factory=list,max_length=100)
    exceptions: list[str] = Field(default_factory=list,max_length=100)
    actor: str = Field(min_length=1,max_length=100)
    feedback_id: str | None = None


class Scope(StrictModel):
    roles: list[Literal['party_a','party_b','neutral']] = Field(min_length=1,max_length=3)
    business_scopes: list[str] = Field(min_length=1,max_length=30)
    event_types: list[str] = Field(min_length=1,max_length=30)
    stages: list[str] = Field(min_length=1,max_length=30)

    @model_validator(mode='after')
    def explicit_scope(self):
        if any(not v.strip() or v.strip() == '*' for values in self.model_dump().values() for v in values):
            raise ValueError('适用范围须明确，不能空白或通配')
        return self


class Confirmation(StrictModel):
    actor: str = Field(min_length=1,max_length=100)
    confirmed_scope: Scope
    basis_refs: list[str] = Field(min_length=1,max_length=100)
    basis_verification: str = Field(default='',max_length=10000)


class Retirement(StrictModel):
    actor: str = Field(min_length=1,max_length=100)
    reason: str = Field(min_length=1,max_length=10000)


def document_text(blocks):
    return re.sub(r'\s+','',''.join(b['text'] for b in blocks))


def document_grams(blocks):
    text=document_text(blocks)
    return {text[i:i+16] for i in range(max(0,len(text)-15))}


def freeze_exclusions(db, document_version_id, blocks=None):
    """Use the caller's transaction; never open a nested SQLite write connection.

    Version-owned parsed text is authoritative; optional blocks is API compatibility.
    Inspect all immutable case versions so historical releases remain isolated too.
    """
    source=db.execute('SELECT * FROM versions WHERE id=?',(document_version_id,)).fetchone()
    if not source:raise HTTPException(422,'待审文档版本不存在')
    query_blocks=json.loads(source['parsed']).get('blocks',[])
    query=document_grams(query_blocks);query_text=document_text(query_blocks)
    families={'contract:'+source['contract_id']};hashes={source['sha256'].lower()};matched=[]
    seen=set()
    for row in db.execute('SELECT payload FROM legal_case_versions'):
        case=json.loads(row[0]);vid=case.get('source_version_id')
        if case.get('source_binding')!='verified_version' or not vid or vid in seen:continue
        seen.add(vid)
        origin=db.execute('SELECT * FROM versions WHERE id=?',(vid,)).fetchone()
        if not origin:continue
        origin_blocks=json.loads(origin['parsed']).get('blocks',[])
        other=document_grams(origin_blocks)
        duplicate=bool(query_text and query_text==document_text(origin_blocks)) or bool(query and other and len(query&other)/min(len(query),len(other))>=0.8)
        reason='same_contract' if origin['contract_id']==source['contract_id'] else 'same_hash' if origin['sha256'].lower()==source['sha256'].lower() else 'near_duplicate' if duplicate else None
        if reason:
            families.add('contract:'+origin['contract_id']);hashes.add(origin['sha256'].lower())
            matched.append({'source_version_id':vid,'reason':reason})
    return {'document_version_id':source['id'],'document_sha256':source['sha256'].lower(),
            'source_contract_id':source['contract_id'],'excluded_family_ids':sorted(families),
            'excluded_source_hashes':sorted(hashes),'matched_sources':matched,'algorithm':'bound-source-16gram-v1'}


class Casebook:
    def __init__(self, store):
        self.store = store

    def current_version(self):
        with self.store.connect() as db:
            row = db.execute('SELECT version FROM legal_casebook_releases ORDER BY sequence DESC LIMIT 1').fetchone()
            return row[0] if row else 'casebook-empty-v1'

    def _current(self, db, case_id):
        row = db.execute('SELECT v.payload FROM legal_cases c JOIN legal_case_versions v ON c.current_version_id=v.id WHERE c.id=?',(case_id,)).fetchone()
        if not row:
            raise HTTPException(404,'案例不存在')
        return json.loads(row[0])

    def _append(self, db, item):
        item = {**item, 'id':str(uuid4()), 'created_at':now()}
        db.execute('INSERT INTO legal_case_versions VALUES(?,?,?,?,?)',(item['id'],item['case_id'],item['version'],encoded(item),item['created_at']))
        db.execute('UPDATE legal_cases SET current_version_id=? WHERE id=?',(item['id'],item['case_id']))
        ids = [row[0] for row in db.execute('SELECT current_version_id FROM legal_cases ORDER BY id')]
        release='casebook-'+str(uuid4())
        db.execute('INSERT INTO legal_casebook_releases(version,payload,created_at) VALUES(?,?,?)',(release,encoded(ids),now()))
        return {**item,'casebook_version':release}

    def create_candidate(self, candidate):
        body=CaseCandidate.model_validate(candidate)
        with self.store.connect() as db:
            vid=body.source_version_id
            if body.feedback_id:
                feedback=db.execute('SELECT r.version_id FROM legal_feedback f JOIN runs r ON f.run_id=r.id WHERE f.id=?',(body.feedback_id,)).fetchone()
                if not feedback:raise HTTPException(422,'来源反馈不存在')
                if vid and vid!=feedback[0]:raise HTTPException(422,'案例来源版本与反馈不一致')
                vid=feedback[0]
            binding={'source_binding':'unverified','family_id':body.family_id or 'unbound:'+str(uuid4())}
            if vid:
                source=db.execute('SELECT * FROM versions WHERE id=?',(vid,)).fetchone()
                if not source:raise HTTPException(422,'案例来源版本不存在')
                if body.source_hash and body.source_hash.lower()!=source['sha256'].lower():raise HTTPException(422,'来源摘要与文档版本不一致')
                blocks=json.loads(source['parsed']).get('blocks',[])
                if not any(body.original_span in b['text'] for b in blocks):raise HTTPException(422,'案例原文不属于绑定文档版本')
                binding={'source_version_id':vid,'source_contract_id':source['contract_id'],'source_hash':source['sha256'].lower(),'source_binding':'verified_version','family_id':'contract:'+source['contract_id'],'declared_family_id':body.family_id}
            item={**body.model_dump(),**binding,'case_id':str(uuid4()),'state':'candidate','version':1,'scope':{},'confirmation':None,'actor_authentication':'self_reported'}
            db.execute('INSERT INTO legal_cases VALUES(?,?,NULL)',(item['case_id'],item['family_id']))
            return self._append(db,item)

    def publish_case(self, candidate_id, confirmed_scope, actor, *, basis_refs, basis_verification=''):
        body=Confirmation(actor=actor,confirmed_scope=confirmed_scope,basis_refs=basis_refs,basis_verification=basis_verification)
        with self.store.connect() as db:
            old=self._current(db,candidate_id)
            if old['state'] != 'candidate':
                raise HTTPException(409,'仅候选案例可以确认；更正意见需新增候选')
            if not old['rationale'].strip():
                raise HTTPException(422,'缺少修改理由，不能确认')
            if not all(ref.strip() for ref in body.basis_refs):
                raise HTTPException(422,'依据不可空白')
            if old['basis_kind'] in ('legal_requirement','company_policy') and not body.basis_verification:
                raise HTTPException(422,'法律或公司政策依据须记录来源核验与适用条件')
            confirmation={**body.model_dump(exclude={'confirmed_scope'}),'actor_authentication':'self_reported','confirmed_at':now()}
            return self._append(db,{**old,'version':old['version']+1,'state':'confirmed','scope':body.confirmed_scope.model_dump(),'confirmation':confirmation,'basis_refs':body.basis_refs})

    def retire_case(self, case_id, actor, reason):
        body=Retirement(actor=actor,reason=reason)
        with self.store.connect() as db:
            old=self._current(db,case_id)
            if old['state']=='retired':
                raise HTTPException(409,'案例已撤回')
            return self._append(db,{**old,'version':old['version']+1,'state':'retired','retirement':{**body.model_dump(),'actor_authentication':'self_reported'}})

    def retrieve_cases(self,event,context,excluded_family_ids,casebook_version,limit=3,*,excluded_source_hashes=()):
        from .case_retrieval import retrieve_cases
        with self.store.connect() as db:
            if casebook_version=='casebook-empty-v1':
                return []
            row=db.execute('SELECT payload FROM legal_casebook_releases WHERE version=?',(casebook_version,)).fetchone()
            if not row:
                raise HTTPException(422,'案例库版本不存在，不能替换为最新版本')
            ids=json.loads(row[0])
            cases=[json.loads(db.execute('SELECT payload FROM legal_case_versions WHERE id=?',(vid,)).fetchone()[0]) for vid in ids]
        return retrieve_cases(event,context,excluded_family_ids,casebook_version,limit,cases=cases,excluded_source_hashes=excluded_source_hashes)


def register(app,store):
    book=Casebook(store)

    @app.get('/api/v1/legal-cases')
    def listing():
        with store.connect() as db:
            items=[json.loads(r[0]) for r in db.execute('SELECT v.payload FROM legal_cases c JOIN legal_case_versions v ON c.current_version_id=v.id ORDER BY c.id')]
        return {'items':items,'casebook_version':book.current_version()}

    @app.get('/api/v1/legal-cases/{case_id}')
    def history(case_id:str):
        with store.connect() as db:
            current=book._current(db,case_id)
            versions=[json.loads(r[0]) for r in db.execute('SELECT payload FROM legal_case_versions WHERE case_id=? ORDER BY version',(case_id,))]
        return {'current':current,'versions':versions}

    @app.post('/api/v1/legal-cases',status_code=201)
    def create(body:CaseCandidate):
        return book.create_candidate(body.model_dump())

    @app.post('/api/v1/legal-cases/{case_id}/confirm')
    def confirm(case_id:str,body:Confirmation):
        return book.publish_case(case_id,body.confirmed_scope.model_dump(),body.actor,basis_refs=body.basis_refs,basis_verification=body.basis_verification)

    @app.post('/api/v1/legal-cases/{case_id}/retire')
    def retire(case_id:str,body:Retirement):
        return book.retire_case(case_id,body.actor,body.reason)
