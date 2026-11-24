"""Run with: uv run python -m app.worker. SQLite lease queue for local deployment."""
import json, os, time
from pathlib import Path
from uuid import uuid4
from .rule_registry import CONFIGURED_RULES_POLICY, matches_rule_snapshot
from . import configured_review
from .configured_review import review_configured, implementation_hash
from .store import Store
from .review_jobs import now,dumps,schema_hash,set_stage
from .llm import Settings,ExtractionError
from .review_policy import prompt_hash


def tick(store,settings,reviewer=review_configured):
    owner=str(uuid4());stamp=time.time()
    with store.connect() as db:
        # Recover an interrupted attempt after its fixed lease expires.
        for job in db.execute("SELECT * FROM jobs WHERE state='running' AND lease_until<?",(stamp,)).fetchall():
            if job['attempts']>=2:
                run=db.execute('SELECT payload FROM runs WHERE id=?',(job['run_id'],)).fetchone()
                p=json.loads(run['payload']);p.update(status='failed',error={'code':'worker_interrupted','message':'审查执行中断，请重新发起。'},progress='执行中断',finished_at=now())
                db.execute("UPDATE jobs SET state='failed',owner=NULL WHERE id=?",(job['id'],));db.execute('UPDATE runs SET status=?,payload=? WHERE id=?',('failed',dumps(p),job['run_id']))
                state=db.execute('SELECT payload FROM review_execution_states WHERE run_id=?',(job['run_id'],)).fetchone()
                if state:
                    from .review_execution_events import append as recover_execution
                    recover_execution(db,p,json.loads(state[0])['attempt_id'],'run_failed',{})
            else:db.execute("UPDATE jobs SET state='queued' WHERE id=?",(job['id'],))
        job=db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
        if not job:return False
        db.execute("UPDATE jobs SET state='running',owner=?,lease_until=?,attempts=attempts+1 WHERE id=?",(owner,stamp+max(300,3*settings.timeout+60),job['id']))
        row=db.execute('SELECT * FROM runs WHERE id=?',(job['run_id'],)).fetchone();p=json.loads(row['payload'])
        if job['lease_until'] is not None:
            p['recovery_count'] = p.get('recovery_count', 0) + 1
        p.update(status='running',started_at=now())
        p.pop('error',None);p.pop('finished_at',None)
        set_stage(p,'preparing')
        db.execute('UPDATE runs SET status=?,payload=? WHERE id=?',('running',dumps(p),row['id']))
        doc=db.execute('SELECT * FROM versions WHERE id=?',(row['version_id'],)).fetchone()
        bundle=None
        if p.get('material_bundle_id'):
            from .materials import load_bundle
            bundle=load_bundle(db,row['contract_id'],p['material_bundle_id'])
    from .review_execution_events import ExecutionReporter, append as append_execution
    reporter=ExecutionReporter(store,dict(p),owner,max(300,3*settings.timeout+60))
    def progress_callback(stage):
        # A reclaimed worker must never overwrite progress from its successor.
        with store.connect() as db:
            lease=db.execute('SELECT owner,state FROM jobs WHERE id=?',(job['id'],)).fetchone()
            if lease['owner']!=owner or lease['state']!='running':
                raise ExtractionError('lease_lost','执行权已移交后台重试任务')
            set_stage(p,stage)
            db.execute('UPDATE jobs SET lease_until=? WHERE id=?',(time.time()+max(300,3*settings.timeout+60),job['id']))
            db.execute('UPDATE runs SET payload=? WHERE id=?',(dumps(p),p['id']))
        reporter.emit('stage_changed',stage=stage)
    policy_version = p.get('review_prompt_version')
    try:
        if policy_version != CONFIGURED_RULES_POLICY:
            raise ExtractionError('review_policy_retired', '旧审查策略已停用，请重新发起审查。')
        if not settings.api_key:
            raise ExtractionError('not_configured', '模型未配置。')
        valid = (p.get('result_schema_version') == 'interactive-review-v3'
                 and p.get('review_prompt_sha256') == prompt_hash(policy_version)
                 and p.get('review_schema_sha256') == schema_hash(policy_version)
                 and p.get('review_implementation_sha256') == implementation_hash()
                 and matches_rule_snapshot(policy_version, p.get('rule_snapshot')))
        if not valid:
            raise ExtractionError('review_policy_mismatch', '审查口径版本校验失败，请重试以创建新批次。')

        from .clause_structure import version_structure
        from .review_checkpoints import checkpointed_call
        from .review_issues import LIABILITY_CLAUSE_MODE, build_review_issues

        parsed = json.loads(doc['parsed'])
        blocks = parsed['blocks']
        if 'image_block_ids' not in parsed:
            from .parser import parse_docx, namespace_parsed
            parsed = namespace_parsed(parse_docx(doc['content']), doc['id'])
        candidate_bundle = dict(bundle) if bundle is not None else {'materials': []}
        candidate_bundle['document_image_block_ids'] = parsed.get('image_block_ids', [])
        candidate_bundle['document_parse_status'] = 'partial' if candidate_bundle['document_image_block_ids'] else 'parsed'
        context = {k: v for k, v in p['context_snapshot'].items()
                   if k not in ('contract_type', 'contract_type_declared', 'business_scope', 'business_scope_code', 'business_scope_state')}
        rules = p['rule_snapshot']['rules']
        structure = version_structure(json.loads(doc['parsed']), doc['id'])
        result = reviewer(settings, p['model'], blocks, context, rules, bundle=candidate_bundle,
                          clauses=structure['clauses'], model_call=checkpointed_call(store, p, owner, configured_review.extract_call),
                          execution_callback=reporter.emit, progress_callback=progress_callback,
                          document_version_id=doc['id'])
        # Build identities once for issues and compatibility findings.
        rebuilt = build_review_issues(p['id'], result['rule_results'], result.get('attachment_checks', []),
                                      expected_rule_ids=[r['id'] for r in rules], additional_issues=[], split_liability=True)
        from .clause_structure import build_clauses
        clauses=build_clauses(doc['id'],blocks)
        locations={b:c['id'] for c in clauses for b in c['block_ids']}
        fs=rebuilt['issues']
        authoritative={(i['rule_id'],i.get('subject_key',i['rule_id'])):i for i in result['issues']}
        for item in fs:
            source=authoritative.get((item['rule_id'],item['subject_key']),{})
            for key in ('review_state','provenance','title','explanation','status','revision_plan','card_content','event_id'):
                if key in source:item[key]=source[key]
            item['ai_status']=item['status']
        for f in fs:
            if f.get('execution_mode')==LIABILITY_CLAUSE_MODE:
                f['display_group'] = 'legal_issue'
            elif f['rule_id'] != 'RL-04' and f['status']=='insufficient_evidence' and f.get('execution_state')!='failed':
                f['display_group'] = 'context'
            else:
                f['display_group']='context' if f['rule_id']=='RL-05' or f.get('review_reason')=='role_unknown' else 'legal_issue'
        p.update(revision_proposals=result.get('revision_proposals',[]),context_snapshot=result.get('context_snapshot',context))
        for idx,f in enumerate(rebuilt['rule_results']):
            f.update(id=f"{p['id']}:rule:{idx+1}",document_version_id=doc['id'],severity=None,scope='model_candidate',calculation=None)
        for f in fs:
            f.update(document_version_id=doc['id'],severity=None,scope='model_candidate',calculation=None)
            f['clause_ids']=list(dict.fromkeys(locations[e['block_id']] for e in f['evidence'] if e['block_id'] in locations))
            if bundle:f['material_bundle_id']=bundle['id']
        if p.get('parent_run_id'):
            with store.connect() as db:
                parent=db.execute('SELECT payload FROM runs WHERE id=?',(p['parent_run_id'],)).fetchone()
                prior=json.loads(parent[0]).get('issues',[]) if parent else []
            for f in fs:
                matches=[old for old in prior if old.get('subject_key')==f.get('subject_key') and old['rule_id']==f['rule_id']]
                if len(matches)==1:f['supersedes_issue_id']=matches[0]['id']
        p.update(rule_results=rebuilt['rule_results'],issues=fs,module_errors=result.get('module_errors',[]),attachment_checks=result.get('attachment_checks',[]),diagnostics=result.get('diagnostics',{}))
        if not p['module_errors']:
            set_stage(p, 'done')
        p.update(findings=fs, status='needs_input', extraction_status='model_reviewed',
                 progress='AI 审查完成，待人工复核', finished_at=now())
        if p['module_errors']:
            p.update(stage='partial', progress='AI 审查部分完成，部分检查未完成，待人工复核')
    except Exception as exc:
        p.update(status='failed',progress='审查失败',finished_at=now(),error={'code':exc.code if isinstance(exc,ExtractionError) else 'worker_error','message':exc.message if isinstance(exc,ExtractionError) else '执行失败，请重试。'})
        if isinstance(exc,ExtractionError):
            for key in ('diagnostics','attempts'):
                if hasattr(exc,key):p['error'][key]=getattr(exc,key)
    try:
        reporter.close()
    except Exception as exc:
        p.update(status='failed',finished_at=now(),error={'code':getattr(exc,'code','progress_failed'),'message':'审查进度提交失败，请重新审查。'})
    with store.connect() as db:
        current=db.execute('SELECT owner,state FROM jobs WHERE id=?',(job['id'],)).fetchone()
        if current['owner']!=owner or current['state']!='running':return True
        from .materials import is_stale
        p['stale']=is_stale(db,p)
        db.execute('UPDATE runs SET status=?,payload=? WHERE id=?',(p['status'],dumps(p),p['id']))
        state=append_execution(db,p,owner,'run_failed' if p['status']=='failed' else 'run_partial' if p.get('module_errors') else 'run_completed',{})
        p['execution_phases']=state.get('phases',{})
        phases=list(p['execution_phases'].values())
        if phases:
            p.setdefault('diagnostics',{})['execution']={'completed_phases':sum(x['state']=='completed' for x in phases),'total_phases':len(phases),'recovery_count':p.get('recovery_count',0)}
        db.execute('UPDATE runs SET payload=? WHERE id=?',(dumps(p),p['id']))
        db.execute('UPDATE jobs SET state=? WHERE id=?',('failed' if p['status']=='failed' else 'done',job['id']))
        codes=[e.get('code') for e in p.get('module_errors',[])] + ([p['error'].get('code')] if p.get('error') else [])
        transient={'gateway_timeout','gateway_unreachable','gateway_stream_error'}
        if policy_version == CONFIGURED_RULES_POLICY and codes and all(c in transient for c in codes) and job['attempts'] < 1:
            p.update(status='queued',progress='正在恢复未完成任务，已保存结果将继续使用',recovery_count=p.get('recovery_count',0)+1)
            p.pop('finished_at',None)
            db.execute('UPDATE runs SET status=?,payload=? WHERE id=?',('queued',dumps(p),p['id']))
            db.execute("UPDATE jobs SET state='queued',owner=NULL,lease_until=NULL WHERE id=?",(job['id'],))
    return True


def main():
    store=Store(os.getenv('RIXIN_DB',str(Path(__file__).resolve().parents[1]/'data/review.sqlite3')))
    settings=Settings.load()
    while True:
        if not tick(store,settings):time.sleep(1)

if __name__=='__main__':main()
