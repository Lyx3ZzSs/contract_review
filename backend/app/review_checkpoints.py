"""Run-scoped model receipts for resumable review execution.

Only schema/source-validated outputs are reusable. Revalidate against current
inputs on every hit; implementation and full request hashes prevent stale reuse.
"""
import json
import time
from hashlib import sha256
from .llm import ExtractionError
from .review_jobs import dumps, now
from .review_transport import call_with_retry


def checkpointed_call(store, run, owner, call):
    def check(db):
        job = db.execute('SELECT owner,state FROM jobs WHERE run_id=?', (run['id'],)).fetchone()
        if not job or job['owner'] != owner or job['state'] != 'running':
            raise ExtractionError('lease_lost', '执行权已移交后台重试任务')

    def invoke(settings, model, prompt, schema, payload, validate, deadline, trace):
        started = time.monotonic()
        fingerprint = {'implementation': run.get('review_implementation_sha256'),
            'document': run['document_version_id'], 'model': model, 'endpoint': settings.base_url,
            'prompt': prompt, 'schema': getattr(validate, 'wire_schema', schema).model_json_schema(), 'input': payload,
            'thinking': settings.thinking, 'reasoning_effort': settings.reasoning_effort,
            'max_output_tokens': settings.max_output_tokens}
        key = sha256(dumps(fingerprint).encode()).hexdigest()
        with store.connect() as db:
            check(db)
            row = db.execute('SELECT payload FROM review_checkpoints WHERE run_id=? AND input_hash=?',
                             (run['id'], key)).fetchone()
        if row:
            receipt = json.loads(row[0])
            value = schema.model_validate(receipt['output'])
            result = validate(value)
            if settings.stream_callback:
                settings.stream_callback('started', revision=1)
                settings.stream_callback('validating', revision=1)
            trace.append({'stage': schema.__name__, 'status': 'restored', 'checkpoint': key,
                          'elapsed_seconds': round(time.monotonic()-started, 3)})
            return value, result
        offset = len(trace)
        value, result = call_with_retry(call, settings, model, prompt, schema,
                                        payload, validate, deadline, trace)
        if any(entry.get('unresolved') for entry in trace[offset:]):
            # A resumed run must be free to complete the missing work.
            with store.connect() as db:
                check(db)
            return value, result
        receipt = {'stage': schema.__name__, 'output': value.model_dump(mode='json'),
                   'trace': trace[offset:], 'created_at': now()}
        with store.connect() as db:
            check(db)
            db.execute('INSERT INTO review_checkpoints VALUES(?,?,?) ON CONFLICT(run_id,input_hash) DO NOTHING',
                       (run['id'], key, dumps(receipt)))
        return value, result
    return invoke
