"""Verified proposal writes: editor mutations become applied only after saved DOCX proof."""
import json
import time
from uuid import uuid4
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field
from .onlyoffice import get_session, now, dump
from .document_versions import current, commit_version
from .parser import parse_docx
from .proposal_document import verify_document
from .proposal_anchors import AnchorError, relocate_anchor
from .proposal_rechecks import assessment, public_assessment, per_proposal
from .review_issues import LIABILITY_CLAUSE_MODE

class Prepare(BaseModel):
    session_id: str
    expected_version_id: str
    mode: Literal['ALL', 'COMMENT', 'MODIFY']
    idempotency_key: str = Field(min_length=1, max_length=100)
    manual_replacement: str | None = Field(default=None, max_length=10000)

class Confirm(BaseModel):
    session_id: str
    save_request_id: str = ""
    allow_cancel: bool = True

class Undo(BaseModel):
    session_id: str
    expected_version_id: str

class Cancel(Undo):
    editor_result: Literal['rejected', 'absent']


def read(db, oid):
    row = db.execute('SELECT payload FROM proposal_operations WHERE id=?', (oid,)).fetchone()
    if not row: raise HTTPException(404, '修改操作不存在')
    return json.loads(row[0])


def put(db, op):
    db.execute('UPDATE proposal_operations SET payload=? WHERE id=?', (dump(op), op['id']))


def writable(db, sid, cid=None):
    s = get_session(db, sid)
    if cid and s['contract_id'] != cid: raise HTTPException(409, '操作不属于当前合同')
    v = current(db, s['contract_id'])
    if s['state'] != 'open' or s['lease_until'] < time.time() or s['head_version_id'] != v['id']:
        raise HTTPException(409, '当前编辑会话不可写，请重新打开正文')
    return s, v


def operations(db, cid):
    return [json.loads(r[0]) for r in db.execute('SELECT payload FROM proposal_operations WHERE contract_id=? ORDER BY created_at', (cid,))]


def managed_descendant(db, cid, source, head):
    """Only our confirmed operations may explain a version change; never rebase over manual edits."""
    edges = {o.get('after_version_id'): o['before_version_id'] for o in operations(db, cid) if o['state'] in ('applied', 'reverted')}
    edges.update({o.get('reverted_version_id'): o['before_version_id'] for o in operations(db, cid) if o['state']=='reverted'})
    seen = set()
    while head != source and head not in seen:
        seen.add(head)
        head = edges.get(head)
        if not head: return False
    return head == source


def restored_head(previous, head):
    restored = {o.get('reverted_version_id'):o['before_version_id'] for o in previous if o['state']=='reverted'}
    seen = set()
    while head in restored and head not in seen:
        seen.add(head)
        head = restored[head]
    return head


def public(op, head, previous=()):
    return {k: v for k, v in op.items() if k not in ('expected_blocks', 'target', 'comment', 'request')} | {'can_undo': op['state']=='applied' and op.get('after_version_id')==restored_head(previous, head)}


def progress(previous, rid, pid):
    applied = [o for o in previous if o['run_id'] == rid and o['proposal_id'] == pid and o['state'] == 'applied']
    return {kind: next((o for o in reversed(applied) if o['mode'] != excluded), None)
            for kind, excluded in (('comment', 'MODIFY'), ('revision', 'COMMENT'))}


def missing_mode(mode, completed):
    comment = mode != 'MODIFY' and not completed['comment']
    revision = mode != 'COMMENT' and not completed['revision']
    return 'ALL' if comment and revision else 'COMMENT' if comment else 'MODIFY' if revision else None


def proposal_reasons(value, proposal, completed, *, awaiting_manual_text=False):
    base = action_reasons(value, proposal, awaiting_manual_text=awaiting_manual_text)
    reasons = {}
    for mode in ('ALL', 'COMMENT', 'MODIFY'):
        missing = missing_mode(mode, completed)
        reasons[mode] = base[missing] if missing else '本项操作已完成'
    if proposal.get('operation')=='comment':
        reasons['ALL'] = '请分别添加批注和修订'
    return reasons


def operation_targets(value):
    yield from value.get('revision_proposals', [])
    for issue in value.get('issues', []):
        anchor = issue.get('event_anchor')
        if issue.get('execution_mode')!=LIABILITY_CLAUSE_MODE or not anchor or anchor not in issue['evidence']:
            continue
        direction = (issue.get('presentation') or {}).get('next_step')
        yield dict(id=issue['id'],document_version_id=value['document_version_id'],anchor=anchor,
                   state='draft',operation='comment',before_text=anchor['quote'],after_text='',
                   rationale=' '.join(filter(None,[issue['explanation'],direction])))

def appended_paragraphs(proposal):
    """Legacy drafts can express an append as the unchanged quote plus new lines."""
    before = proposal.get('before_text', '')
    after = proposal.get('after_text', '').replace('\r\n', '\n')
    if proposal.get('operation') == 'replace' and before and after.startswith(before + '\n'):
        suffix = after[len(before):]
    elif proposal.get('operation') == 'insert' and not before:
        suffix = after
    else:
        return []
    # Blank separator lines and indentation describe layout, not clause content.
    lines = [line.strip(' \t') for line in suffix.split('\n') if line.strip(' \t')]
    if any('\r' in line or '\t' in line for line in lines) or len(after) > 30000:
        return []
    return lines


def action_reasons(value, proposal, *, awaiting_manual_text=False):
    """Business confirmation is independent of writing a review draft or comment."""
    p = proposal
    state = p.get('state')
    reasons = dict.fromkeys(('ALL', 'COMMENT', 'MODIFY'), '')
    if state not in ('draft', 'context_required', 'conflict') or p.get('validation_errors'):
        return dict.fromkeys(reasons, '建议的原文或内容校验未通过，暂不能写入')
    if state == 'conflict':
        reasons['ALL'] = reasons['MODIFY'] = '关联修改存在冲突，可先添加批注'
    elif any(e.get('module') == 'revision-verification' and e.get('code') != 'revision_conflict'
             for e in (value.get('module_errors') or [])):
        reasons['ALL'] = reasons['MODIFY'] = '修改稿整体核验未完成，可先添加批注'
    before, after = p.get('before_text', ''), p.get('after_text', '')
    if not appended_paragraphs(p) and (any(c in before + after for c in '\n\r\t')
            or not awaiting_manual_text and (p.get('operation') != 'replace' or not after.strip() or before == after)):
        reasons['ALL'] = reasons['MODIFY'] = '当前修改不能自动替换，可添加批注'
    if not p.get('rationale', '').strip():
        reasons['ALL'] = reasons['COMMENT'] = '建议缺少批注内容'
    return reasons


def locate_target(proposal, source, blocks, version_id, revision=None):
    p = proposal
    if p.get('document_version_id') != version_id:
        raise HTTPException(409, '建议与审查版本不一致')
    anchor = p.get('anchor') or {}
    index = next((i for i, b in enumerate(source) if b['id'] == anchor.get('block_id')), -1)
    if index < 0:
        raise HTTPException(409, '建议的原文段落标识无效')
    before = anchor.get('quote') if p.get('operation') == 'insert' else p.get('before_text', '')
    start, end = anchor.get('start'), anchor.get('end')
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source[index]['text']) or not before or source[index]['text'][start:end] != before or anchor.get('quote') != before:
        raise HTTPException(409, '建议与引用范围不一致，请人工核对')
    expected = source[index]['text']
    quote = before
    if revision and not revision.get('append_paragraphs'):
        original = revision['target']
        start = original['start']
        expected = original['paragraph'][:start]+revision['after_text']+original['paragraph'][original['end']:]
        quote = revision['after_text']
        end = start + len(revision['after_text'])
    try:
        located = relocate_anchor(source,blocks,anchor['block_id'],quote,start,end,expected_paragraph=expected)
    except AnchorError as exc:
        error = HTTPException(409,exc.message)
        error.code = exc.code
        raise error from None
    return located


def write_position_reason(proposal, block, end, image_ids, mode):
    if block['id'] in image_ids:
        return '目标段落含图片，请在正文中处理'
    if mode == 'COMMENT':
        return ''
    if not appended_paragraphs(proposal):
        return ''
    if block.get('table_location'):
        return '表格单元格暂不支持自动新增段落，可添加批注'
    if block['text'][end:].strip(' \t'):
        return '引用之后还有同段正文，请核对新增条款的插入位置'
    # Older insert drafts did not encode the paragraph break. Infer a paragraph
    # append only for an anchor covering the entire non-whitespace source.
    if proposal['operation'] == 'insert' and not proposal['after_text'].startswith(('\n','\r\n')):
        start = end - len(proposal['anchor']['quote'])
        if block['text'][:start].strip(' \t'):
            return '引用仅覆盖部分段落，请核对是否需要另起一段'
    return ''


def applicable_reasons(value, p, completed, check, *, awaiting_manual_text=False):
    reasons = proposal_reasons(value,p,completed,awaiting_manual_text=awaiting_manual_text)
    local = per_proposal(check,p,completed)
    if check['status']=='blocked':
        return dict.fromkeys(reasons,check['message']),local
    if local['status'] not in ('not_required','applicable'):
        for mode in reasons:
            if not reasons[mode] and missing_mode(mode,completed) in ('ALL','MODIFY'):
                reasons[mode] = local['reason'] or '正文已更新，需先复核本建议的适用性'
    return reasons,local


def verify_saved(before, after, op):
    actual = json.loads(after['parsed'])['blocks']
    if [b['text'] for b in actual] != op['expected_blocks']:
        raise HTTPException(409, '保存的正文与本次建议不一致，未标记为已应用，请核对正文')
    if op['target'].get('table_location'):
        original = json.loads(before['parsed'])['blocks']
        if [b.get('table_location') for b in original] != [b.get('table_location') for b in actual]:
            raise HTTPException(409, '保存后正文所在的表格单元格发生变化，请核对')
    return verify_document(before['content'], after['content'], op)


def register(app, store):
    @app.get('/api/v1/proposal-operations/{oid}')
    def get_operation(oid: str):
        with store.connect() as db:
            op = read(db,oid)
            return public(op,current(db,op['contract_id'])['id'],operations(db,op['contract_id']))

    @app.get('/api/v1/runs/{rid}/proposal-operations')
    def list_ops(rid: str):
        with store.connect() as db:
            row = db.execute('SELECT contract_id FROM runs WHERE id=?', (rid,)).fetchone()
            if not row: raise HTTPException(404, '审查不存在')
            head = current(db, row[0])['id']
            previous=operations(db,row[0])
            return [public(o, head, previous) for o in previous if o['run_id']==rid]

    @app.get('/api/v1/runs/{rid}/proposal-availability')
    def availability(rid: str):
        with store.connect() as db:
            row=db.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
            if not row: raise HTTPException(404,'审查不存在')
            head=current(db,row['contract_id']);value=json.loads(row['payload'])
            source=json.loads(db.execute('SELECT parsed FROM versions WHERE id=?',(row['version_id'],)).fetchone()[0])['blocks']
            parsed=json.loads(head['parsed']);blocks=parsed['blocks'];eligible=[];proposals={}
            previous = operations(db, row['contract_id'])
            check = assessment(db,row,head,value,previous)
            for p in operation_targets(value):
                pid=p.get('proposal_id') or p.get('id')
                completed = progress(previous, rid, pid)
                reasons,local=applicable_reasons(value,p,completed,check)
                manual_revision_reason = applicable_reasons(value,p,completed,check,awaiting_manual_text=True)[0]['MODIFY'] if p.get('operation')=='comment' else None
                location = {'status':'invalid_anchor','message':''}
                try:
                    found=locate_target(p,source,blocks,row['version_id'],completed['revision'])
                    b=found['block'];start,end=found['start'],found['end']
                    for requested in reasons:
                        mode = missing_mode(requested,completed)
                        position_reason = write_position_reason(p,b,end,parsed.get('image_block_ids',[]),mode)
                        reasons[requested] = reasons[requested] or position_reason
                        if requested=='MODIFY' and manual_revision_reason is not None:
                            manual_revision_reason = manual_revision_reason or position_reason
                    location={'status':'current' if head['id']==row['version_id'] else 'relocated',
                        'message':'' if head['id']==row['version_id'] else '已在当前保存版本中重新定位原文',
                        'target':{'documentVersionId':head['id'],'blockId':b['id'],'paragraph':b['text'],
                                  'start':start,'end':end,'quote':b['text'][start:end],
                                  'blocks':[{'id':b['id'],'text':b['text']} for b in blocks]}}
                    if any(o['state']=='prepared' for o in previous):
                        raise HTTPException(409,'上一操作的保存结果待确认，请先恢复该操作')
                except HTTPException as exc:
                    reasons=dict.fromkeys(reasons,exc.detail)
                    if manual_revision_reason is not None:
                        manual_revision_reason = exc.detail
                    if 'target' not in location:
                        location={'status':getattr(exc,'code','invalid_anchor'),'message':exc.detail}
                modes=[mode for mode,reason in reasons.items() if not reason]
                proposals[pid]={'append_paragraphs':appended_paragraphs(p),'modes':modes,'reasons':reasons,'completed':{k:bool(v) for k,v in completed.items()},
                                'location':location,'recheck':local}
                if manual_revision_reason is not None:
                    proposals[pid]['manual_revision_reason'] = manual_revision_reason
                if modes:eligible.append(pid)
            blocking = next((o for o in previous if o['state']=='prepared'), None)
            visible_check = check
            if proposals and not value.get('revision_proposals') and check['status']=='required':
                visible_check = {**check,'status':'not_required','message':''}
            return {'document_version_id':head['id'],'eligible':eligible,'proposals':proposals,
                    'blocking_operation':public(blocking,head['id'],previous) if blocking else None,
                    'recheck':public_assessment(visible_check)}

    @app.post('/api/v1/runs/{rid}/proposals/{pid}/operations')
    def prepare(rid: str, pid: str, body: Prepare):
        with store.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
            if not row: raise HTTPException(404, '审查不存在')
            cid = row['contract_id']; s, head = writable(db, body.session_id, cid)
            request = body.model_dump(exclude_none=True)
            previous = operations(db, cid)
            for op in previous:
                if op['request']['idempotency_key']==body.idempotency_key:
                    if op['request']!=request or op['run_id']!=rid or op['proposal_id']!=pid: raise HTTPException(409, '重复请求参数不一致')
                    return op
            if any(o['state']=='prepared' for o in previous): raise HTTPException(409, '上一操作尚未确认，请先重试保存确认')
            if head['id'] != body.expected_version_id: raise HTTPException(409, '正文版本已变化')
            value = json.loads(row['payload'])
            if row['status'] not in ('completed','needs_input'): raise HTTPException(409, '审查尚未完成')
            p = next((p for p in operation_targets(value) if (p.get('proposal_id') or p.get('id'))==pid), None)
            if not p: raise HTTPException(404, '修改建议不存在')
            completed = progress(previous, rid, pid)
            if body.manual_replacement is not None:
                if p.get('operation')!='comment' or body.mode!='MODIFY' or completed['revision']:
                    raise HTTPException(409,'该意见当前不能填写修订')
                replacement = body.manual_replacement.strip()
                if not replacement or replacement==p['before_text'] or any(c in replacement for c in '\n\r\t'):
                    raise HTTPException(422,'请填写与原文不同的单段修订内容')
                p = {**p,'operation':'replace','after_text':replacement}
            check=assessment(db,row,head,value,previous)
            reasons,local=applicable_reasons(value,p,completed,check)
            reason=reasons[body.mode]
            if reason:raise HTTPException(409,reason)
            mode = missing_mode(body.mode, completed)
            continuation = None
            prior = completed['revision'] if mode == 'COMMENT' else completed['comment']
            if prior:
                continuation = {'bookmark':prior['bookmark'],'mode':prior['mode'], 'comment':prior['comment'],
                                'ooxml_comment_id':prior.get('proof',{}).get('comment_id')}
                # Preserve a previous comment when the native replacement moves its range.
                if mode == 'MODIFY':
                    mode = 'ALL'
            source = db.execute('SELECT parsed FROM versions WHERE id=?', (row['version_id'],)).fetchone()
            blocks = json.loads(source[0])['blocks']
            parsed = json.loads(head['parsed'])
            current_blocks = parsed['blocks']
            found = locate_target(p,blocks,current_blocks,row['version_id'],completed['revision'])
            index,b,start,end = found['index'],found['block'],found['start'],found['end']
            reason = write_position_reason(p,b,end,parsed.get('image_block_ids',[]),mode)
            if reason:
                raise HTTPException(409,reason)
            before, after = p.get('before_text',''), p.get('after_text','')
            comment = p.get('rationale','').strip()
            if p.get('message') and p.get('state') in ('context_required','conflict'):
                comment += '\n\n待核对事项：' + p['message']
            if mode=='COMMENT' and local['status'] not in ('not_required','applicable'):
                comment += '\n\n版本核对：正文已更新，本条意见基于原审查。' + (local['reason'] or '适用性尚待复核。')
            if prior and prior['mode']=='COMMENT':
                comment = prior['comment']
            oid = str(uuid4()); expected = [b['text'] for b in current_blocks]
            appended = appended_paragraphs(p) if mode != 'COMMENT' else []
            if appended:
                expected[index + 1:index + 1] = appended
            elif mode!='COMMENT': expected[index] = b['text'][:start]+after+b['text'][end:]
            op = dict(id=oid,contract_id=cid,run_id=rid,proposal_id=pid,mode=mode,requested_mode=body.mode,state='prepared',phase='prepared',before_version_id=head['id'],session_id=s['id'],created_at=now(),request=request,bookmark='rx_'+oid.replace('-',''),comment=comment,expected_blocks=expected,
                      target=dict(version=head['id'],blockId=b['id'],paragraph=b['text'],quote=b['text'][start:end],start=start,end=end,blocks=[{'id':b['id'],'text':b['text']} for b in current_blocks]),after_text=after,append_paragraphs=appended,continuation=continuation,
                      applicability={'check_id':check.get('check_id'),'base_version_id':check['base_version_id'],'context_hash':check['context_hash'],'status':local['status']})
            if b.get('table_location'):
                op['target']['table_location'] = b['table_location']
            db.execute('INSERT INTO proposal_operations VALUES(?,?,?,?,?,?)',(oid,cid,rid,pid,dump(op),op['created_at']))
            return op

    @app.post('/api/v1/proposal-operations/{oid}/confirm')
    def confirm(oid: str, body: Confirm):
        error = None
        with store.connect() as db:
            op = read(db,oid)
            _, after = writable(db,body.session_id,op['contract_id'])
            changed_session = op['session_id'] != body.session_id
            if changed_session and get_session(db,op['session_id'])['state'] != 'closed':
                raise HTTPException(409, '原编辑会话尚未关闭，请先恢复原会话')
            if op['state']!='prepared': return public(op,after['id'])
            candidates = [json.loads(x[0]) for x in db.execute(
                'SELECT payload FROM editor_save_requests WHERE session_id IN (?,?)', (op['session_id'],body.session_id))]
            candidates = [x for x in candidates if x.get('state')=='committed'
                          and x.get('created_at','') >= op['created_at']
                          and x.get('request',{}).get('expected_head_version_id')==op['before_version_id']
                          and x.get('document_version_id')==after['id']]
            r = next((x for x in candidates if x['id']==body.save_request_id), candidates[-1] if candidates else None)
            # A closed key cannot later overwrite this newly opened, unchanged snapshot.
            # In the original session an actual post-prepare save receipt is required.
            if body.allow_cancel and after['id']==op['before_version_id'] and (r or changed_session):
                op.update(state='cancelled',phase='cancelled',verification_error='')
                put(db,op)
                return public(op,after['id'])
            try:
                if not r:
                    raise HTTPException(409, '本次文档保存尚未确认，请先保存或恢复编辑会话')
                before = db.execute('SELECT * FROM versions WHERE id=?',(op['before_version_id'],)).fetchone()
                proof = verify_saved(before,after,op)
                op.update(state='applied',phase='verified',proof=proof,verification_error='',
                          after_version_id=after['id'],save_request_id=r['id'],confirmed_session_id=body.session_id,applied_at=now())
            except HTTPException as exc:
                op.update(phase='saved_unverified' if r else 'prepared',verification_error=exc.detail)
                error = exc
            put(db,op)
            result = public(op,after['id'])
        # Preserve diagnostics even though the caller receives a failed confirmation.
        if error:
            raise error
        return result

    @app.post('/api/v1/proposal-operations/{oid}/cancel')
    def cancel(oid: str, body: Cancel):
        # The client may attest only a pre-mutation rejection or read-only absence.
        # An uncertain bridge result must go through save/confirm instead.
        with store.connect() as db:
            op = read(db,oid)
            _, head = writable(db,body.session_id,op['contract_id'])
            if op['session_id']!=body.session_id and get_session(db,op['session_id'])['state']!='closed':
                raise HTTPException(409,'原编辑会话尚未关闭')
            if head['id']!=body.expected_version_id or head['id']!=op['before_version_id']:
                raise HTTPException(409,'保存版本已变化，请核对操作结果后恢复')
            if op['state']=='prepared':
                op.update(state='cancelled',phase='cancelled',cancellation=body.model_dump());put(db,op)
            return public(op,head['id'])

    @app.post('/api/v1/proposal-operations/{oid}/undo')
    def undo(oid: str, body: Undo):
        with store.connect() as db:
            op = read(db,oid);s,head = writable(db,body.session_id,op['contract_id'])
            exact = op['state']=='applied' and restored_head(operations(db,op['contract_id']),head['id'])==op.get('after_version_id')
            if op['state']=='prepared':
                receipts=[json.loads(r[0]) for r in db.execute('SELECT payload FROM editor_save_requests WHERE session_id=?',(op['session_id'],))]
                exact=any(r.get('state')=='committed' and r.get('document_version_id')==head['id'] and r['request']['expected_head_version_id']==op['before_version_id'] for r in receipts)
                exact=exact and [b['text'] for b in json.loads(head['parsed'])['blocks']]==op['expected_blocks']
            if not exact or head['id']!=body.expected_version_id:
                raise HTTPException(409, '此操作之后已有修改，不能整体回退；请在正文中逐项处理修订')
            pending = [json.loads(r[0]) for r in db.execute('SELECT payload FROM editor_save_requests WHERE session_id=?',(s['id'],))]
            if any(r['state']=='pending' for r in pending): raise HTTPException(409, '请等待保存完成')
            before = db.execute('SELECT * FROM versions WHERE id=?',(op['before_version_id'],)).fetchone()
            restored = commit_version(db,op['contract_id'],before['content'],before['filename'],parse_docx(before['content']),head['id'],session_id=s['id'])
            # Late callbacks from the old document key must never overwrite the restored version.
            db.execute("UPDATE editor_sessions SET state='closed' WHERE contract_id=? AND state IN ('open','view','closing')",(op['contract_id'],))
            op.update(state='reverted',reverted_version_id=restored['id'],reverted_at=now());put(db,op)
            return public(op,restored['id'])
