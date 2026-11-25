"""Read-only, paginated review rounds for the workspace history."""
import json
from .review_issues import needs_review
from .auth import principal
from datetime import datetime
from fastapi import HTTPException, Query


def register(app, store):
    def fetch_records(q='', state='all', since=None, page=1, page_size=10, run_id=None):
        if state not in ('all', 'active', 'completed', 'failed', 'needs_input'):
            raise HTTPException(422, '无效的审查状态')
        if since:
            try:
                datetime.fromisoformat(since.replace('Z', '+00:00'))
            except ValueError:
                raise HTTPException(422, '无效的开始时间')
        with store.connect() as db:
            base = '''WITH rounds AS (
                SELECT r.*, r.rowid AS sequence, c.payload AS contract_payload,
                CASE WHEN r.status='needs_input' AND json_extract(r.payload,'$.extraction_status')='model_reviewed'
                     THEN 'completed' ELSE r.status END AS record_status,
                ROW_NUMBER() OVER (PARTITION BY r.contract_id ORDER BY r.created_at, r.rowid) AS round_number,
                ROW_NUMBER() OVER (PARTITION BY r.contract_id ORDER BY r.created_at DESC, r.rowid DESC) AS latest_rank
                FROM runs r JOIN contracts c ON c.id=r.contract_id
                WHERE COALESCE(json_extract(c.payload,'$.data_purpose'),'business')='business'
            ) SELECT * FROM rounds WHERE 1=1'''
            params = []
            user = principal.get()
            if user is not None and not user.admin:
                base += " AND json_extract(contract_payload,'$.owner_sub')=?"
                params.append(user.sub)
            if q.strip():
                base += " AND (instr(lower(json_extract(contract_payload,'$.title')),lower(?))>0 OR EXISTS (SELECT 1 FROM json_each(json_extract(contract_payload,'$.party_details.counterparties')) WHERE instr(lower(value),lower(?))>0) OR instr(lower(COALESCE(json_extract(contract_payload,'$.client_metadata.counterpart'),'')),lower(?))>0)"
                params += [q.strip(), q.strip(), q.strip()]
            if since:
                base += ' AND julianday(created_at)>=julianday(?)'
                params.append(since)
            if run_id:
                base += ' AND id=?'
                params.append(run_id)
            counts = dict.fromkeys(('all', 'active', 'completed', 'failed', 'needs_input'), 0)
            for row in db.execute('SELECT record_status,COUNT(*) AS n FROM (' + base + ') GROUP BY record_status', params):
                category = 'active' if row['record_status'] in ('queued','running') else row['record_status']
                counts['all'] += row['n']
                counts[category] = counts.get(category, 0) + row['n']
            if state != 'all':
                base += " AND record_status IN ('queued','running')" if state == 'active' else ' AND record_status=?'
                if state != 'active': params.append(state)
            total = counts[state]
            page = min(page, max(1, (total + page_size - 1)//page_size))
            rows = db.execute(base + ' ORDER BY created_at DESC,sequence DESC LIMIT ? OFFSET ?', params + [page_size,(page-1)*page_size]).fetchall()
            ids = [r['id'] for r in rows]
            decisions, results = {}, {}
            if ids:
                marks = ','.join('?' for _ in ids)
                for r in db.execute(f'SELECT run_id,finding_id,payload FROM decisions WHERE run_id IN ({marks}) ORDER BY id',ids):
                    decisions.setdefault(r['run_id'],{})[r['finding_id']] = json.loads(r['payload'])
                for r in db.execute(f'SELECT run_id,payload FROM results WHERE run_id IN ({marks})',ids):
                    results[r['run_id']] = json.loads(r['payload'])
            items = []
            for row in rows:
                run, contract = json.loads(row['payload']), json.loads(row['contract_payload'])
                result = results.get(row['id'])
                review = (result or {}).get('review_snapshot') or run
                selected_decisions = {d['finding_id']: d for d in result['decisions']} if result and 'decisions' in result else decisions.get(row['id'], {})
                findings = review.get('issues',[]) if review.get('result_schema_version') in ('interactive-review-v1','interactive-review-v2','interactive-review-v3') else review.get('findings',[])
                required = [f for f in findings if needs_review(f)]
                handled = sum(1 for f in required if (d:=selected_decisions.get(f['id'])) and d.get('action')!='needs_business_confirmation')
                incomplete = bool(run.get('module_errors')) or any(r.get('execution_state') in ('failed','not_run') for r in run.get('rule_results',run.get('findings',[])))
                meta = contract.get('client_metadata') or {}
                items.append(dict(id=row['id'],contract_id=row['contract_id'],title=contract['title'],
                    counterpart='、'.join((contract.get('party_details') or {}).get('counterparties',[])) or meta.get('counterpart','待确认'),
                    round_number=row['round_number'],is_latest=row['latest_rank']==1,created_at=row['created_at'],status=row['status'],record_status=row['record_status'],
                    incomplete=incomplete,pending=len(required)-handled,handled=handled,document_version_id=row['version_id'],
                    result_id=result['id'] if result else None,completed_at=result.get('created_at') if result else None))
            return dict(items=items,total=total,counts=counts,page=page,page_size=page_size)

    @app.get('/api/v1/review-records')
    def records(q:str=Query('',max_length=200),state:str='all',since:str|None=None,page:int=Query(1,ge=1),page_size:int=Query(10,ge=1,le=50)):
        return fetch_records(q,state,since,page,page_size)

    @app.get('/api/v1/review-records/{run_id}')
    def record(run_id:str):
        rows=fetch_records(run_id=run_id)['items']
        if not rows: raise HTTPException(404,'审查记录不存在')
        return rows[0]
