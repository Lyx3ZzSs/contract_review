"""Run with: uv run python -m app.worker. SQLite lease queue for local deployment."""
import json, os, time
from pathlib import Path
from uuid import uuid4
from .store import Store
from .review_jobs import now,dumps,review,schema_hash,set_stage
from .llm import Settings,ExtractionError
from .review_policy import PROMPTS, prompt_hash


def tick(store,settings,reviewer=review):
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
        p.update(status='running',started_at=now())
        p.pop('error',None);p.pop('finished_at',None)
        set_stage(p,'preparing')
        db.execute('UPDATE runs SET status=?,payload=? WHERE id=?',('running',dumps(p),row['id']))
        doc=db.execute('SELECT * FROM versions WHERE id=?',(row['version_id'],)).fetchone()
        contract=json.loads(db.execute('SELECT payload FROM contracts WHERE id=?',(row['contract_id'],)).fetchone()['payload'])
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
    try:
        if not settings.api_key:raise ExtractionError('not_configured','模型未配置。')
        policy_version=p.get('review_prompt_version') or 'redlines-v1'
        interactive=p.get('result_schema_version')=='interactive-review-v1'
        accurate=p.get('result_schema_version') in ('interactive-review-v2','interactive-review-v3')
        events=policy_version in ('review-events-v1','review-events-v2')
        if accurate:
            from .accurate_review import review_accurate,implementation_hash
            if events:
                from .event_review_pipeline import implementation_hash
                if policy_version=='review-events-v2':
                    from .event_review_v2 import implementation_hash
            from .rule_registry import ACCURATE_POLICIES,rule_snapshot
            valid=(policy_version in ACCURATE_POLICIES and p.get('review_prompt_sha256')==prompt_hash(policy_version)
                   and p.get('review_schema_sha256')==schema_hash(policy_version)
                   and p.get('review_implementation_sha256')==implementation_hash()
                   and p.get('rule_snapshot')==rule_snapshot(policy_version))
        elif interactive:
            from .interactive_review import review_interactive,PROMPT_VERSION,prompt_hash as interactive_hash,schema_hash as interactive_schema
            from .review_interactions import implementation_hash
            valid=policy_version==PROMPT_VERSION and p.get('review_prompt_sha256')==interactive_hash() and p.get('review_schema_sha256')==interactive_schema() and p.get('review_implementation_sha256')==implementation_hash()
        else:
            valid=policy_version in PROMPTS and (not p.get('review_prompt_sha256') or p['review_prompt_sha256']==prompt_hash(policy_version)) and (not p.get('review_schema_sha256') or p['review_schema_sha256']==schema_hash(policy_version))
        if not valid:raise ExtractionError('review_policy_mismatch','审查口径版本校验失败，未执行。')
        rules=[{k:r[k] for k in ('id','title','trigger','non_trigger_or_exceptions','insufficient_evidence_behavior')} for r in p['rule_snapshot']['rules']]
        if accurate:rules=p['rule_snapshot']['rules']
        blocks=json.loads(doc['parsed'])['blocks']
        context=p.get('context_snapshot') or {k:contract[k] for k in ('contract_type','our_party','stage')}
        if accurate:
            parsed=json.loads(doc['parsed'])
            if 'image_block_ids' not in parsed:
                from .parser import parse_docx,namespace_parsed
                parsed=namespace_parsed(parse_docx(doc['content']),doc['id'])
            # Internal parse metadata is not a user material bundle and gets no ID.
            candidate_bundle=dict(bundle) if bundle is not None else {'materials':[]}
            candidate_bundle['document_image_block_ids']=parsed.get('image_block_ids',[])
            candidate_bundle['document_parse_status']='partial' if candidate_bundle['document_image_block_ids'] else 'parsed'
            if events:
                from .event_review_pipeline import review_events_pipeline,known_family_ids
                if policy_version=='review-events-v2':
                    from .event_review_v2 import review_events_pipeline
                from .legal_casebook import Casebook
                result=review_events_pipeline(settings,p['model'],blocks,context,rules,bundle=candidate_bundle,policy_version=policy_version,progress_callback=progress_callback,document_version_id=doc['id'],casebook=Casebook(store),casebook_version=p.get('casebook_version','casebook-empty-v1'),excluded_family_ids=set(p.get('retrieval_snapshot',{}).get('excluded_family_ids',[]))|known_family_ids(blocks),retrieval_snapshot=p.get('retrieval_snapshot',{}),case_guidance_snapshot=p.get('case_guidance_snapshot'),**({'execution_callback':reporter.emit} if policy_version=='review-events-v2' else {}))
            else:
                if policy_version=='review-context-v1':
                    from .review_context import normalize_review_context
                    context=normalize_review_context(context)
                result=review_accurate(settings,p['model'],blocks,context,rules,bundle=candidate_bundle,policy_version='review-liability-v1' if policy_version=='review-context-v1' else policy_version,progress_callback=progress_callback)
            # Build identities once; issues and compatibility findings must be identical.
            from .review_issues import build_review_issues
            rebuilt=build_review_issues(p['id'],result['rule_results'],result.get('attachment_checks',[]),
                expected_rule_ids=[r['id'] for r in rules],
                additional_issues=[i for i in result['issues'] if i['rule_id'].startswith('CR-') and i.get('execution_state')!='failed'])
            from .clause_structure import build_clauses
            clauses=build_clauses(doc['id'],blocks)
            locations={b:c['id'] for c in clauses for b in c['block_ids']}
            fs=rebuilt['issues']
            if events:
                for f in fs:
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
        elif interactive:
            parsed=json.loads(doc['parsed'])
            if 'image_block_ids' not in parsed:
                from .parser import parse_docx,namespace_parsed
                parsed=namespace_parsed(parse_docx(doc['content']),doc['id'])
            bundle['document_image_block_ids']=parsed.get('image_block_ids',[])
            bundle['document_parse_status']='partial' if bundle['document_image_block_ids'] else 'parsed'
            result=review_interactive(settings,p['model'],blocks,context,rules,bundle,progress_callback=progress_callback)
            from .review_issues import build_review_issues
            result=build_review_issues(p['id'],result['rule_results'],result.get('attachment_checks',[]))
            from .clause_structure import build_clauses
            clauses=build_clauses(doc['id'],blocks)
            locations={b:c['id'] for c in clauses for b in c['block_ids']}
            fs=result['issues']
            for f in fs:
                f['clause_ids']=list(dict.fromkeys(locations[e['block_id']] for e in f['evidence'] if e['block_id'] in locations))
                f['material_bundle_id']=p['material_bundle_id']
            if p.get('parent_run_id'):
                with store.connect() as db:
                    parent=db.execute('SELECT payload FROM runs WHERE id=?',(p['parent_run_id'],)).fetchone()
                    prior=json.loads(parent[0]).get('issues',[]) if parent else []
                for f in fs:
                    matches=[old for old in prior if old.get('subject_key')==f.get('subject_key') and old['rule_id']==f['rule_id']]
                    if len(matches)==1:f['supersedes_issue_id']=matches[0]['id']
            for idx,f in enumerate(result['rule_results']):
                f.update(id=f"{p['id']}:rule:{idx+1}",document_version_id=doc['id'],severity=None,scope='model_candidate',calculation=None)
            p.update(rule_results=result['rule_results'],issues=fs)
        else:
            fs=reviewer(settings,p['model'],blocks,context,rules,prompt_version=policy_version,progress_callback=progress_callback)
        for idx,f in enumerate(fs):
            f.update(document_version_id=doc['id'],severity=None,scope='model_candidate',calculation=None)
            if not interactive and not accurate:f['id']=f"{p['id']}:f{idx+1}"
        if not (accurate and p.get('module_errors')):set_stage(p,'done')
        p.update(findings=fs,status='needs_input',extraction_status='model_reviewed',progress='AI 审查完成，待人工复核',finished_at=now())
        if accurate and p.get('module_errors'):
            p.update(stage='partial',progress='AI 审查部分完成，部分检查未完成，待人工复核')
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
        latest=db.execute('SELECT id FROM versions WHERE contract_id=? ORDER BY revision DESC LIMIT 1',(row['contract_id'],)).fetchone()
        from .materials import is_stale
        p['stale']=is_stale(db,p)
        db.execute('UPDATE runs SET status=?,payload=? WHERE id=?',(p['status'],dumps(p),p['id']))
        append_execution(db,p,owner,'run_failed' if p['status']=='failed' else 'run_partial' if p.get('module_errors') else 'run_completed',{})
        db.execute('UPDATE jobs SET state=? WHERE id=?',('failed' if p['status']=='failed' else 'done',job['id']))
    return True


def main():
    store=Store(os.getenv('RIXIN_DB',str(Path(__file__).resolve().parents[1]/'data/review.sqlite3')))
    settings=Settings.load()
    while True:
        if not tick(store,settings):time.sleep(1)

if __name__=='__main__':main()
