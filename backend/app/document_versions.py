"""One transaction path for uploaded and editor-produced immutable DOCX versions."""
import json
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4
from fastapi import HTTPException
from .parser import namespace_parsed


def current(db,cid):
    return db.execute('SELECT * FROM versions WHERE contract_id=? ORDER BY revision DESC LIMIT 1',(cid,)).fetchone()


def commit_version(db,cid,content,filename,parsed,expected,state=None,session_id=None):
    contract=db.execute('SELECT * FROM contracts WHERE id=?',(cid,)).fetchone()
    if not contract: raise HTTPException(404,'合同不存在')
    active=db.execute("SELECT id FROM editor_sessions WHERE contract_id=? AND state IN ('open','closing')",(cid,)).fetchone()
    if active and active['id']!=session_id: raise HTTPException(409,'正文正在另一编辑会话中，请先保存并关闭该会话')
    old=current(db,cid)
    if (old['id'] if old else None)!=expected: raise HTTPException(409,'文档版本已变化，请刷新后重新保存')
    digest=sha256(content).hexdigest()
    if state is not None: db.execute('INSERT OR REPLACE INTO draft_states VALUES(?,?)',(cid,json.dumps(state,ensure_ascii=False)))
    if old and old['sha256']==digest:
        return {k:old[k] for k in ('id','contract_id','revision','sha256','filename','created_at')} | json.loads(old['parsed'])
    if state is None: db.execute('DELETE FROM draft_states WHERE contract_id=?',(cid,))
    vid=str(uuid4()); namespace_parsed(parsed,vid)
    revision=(old['revision'] if old else 0)+1
    created=datetime.now(timezone.utc).isoformat()
    payload=json.loads(contract['payload'])
    if payload.get('party_details'):
        payload['party_details']['needs_reconfirmation']=digest!=payload['party_details']['file_sha256']
        db.execute('UPDATE contracts SET payload=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),cid))
    db.execute('INSERT INTO versions VALUES(?,?,?,?,?,?,?,?)',(vid,cid,revision,digest,filename,content,json.dumps(parsed,ensure_ascii=False),created))
    return dict(id=vid,contract_id=cid,revision=revision,sha256=digest,filename=filename,created_at=created,**parsed)
