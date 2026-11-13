"""Fixed input live evaluation; expectations are loaded only after model execution.

Baseline receives the main document, as the old production path does. Candidate also
receives the frozen material bundle. This is a capability comparison, not identical
model payloads. No production database or service is accessed.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import time

from app.llm import Settings
from app.review_policy import prompt_hash

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def assemble_input(case, rules):
    return {key: case.get(key, {} if key in ('context', 'bundle') else [])
            for key in ('blocks', 'context', 'bundle')} | {'rules': rules}


def group_for(label):
    if label.get('provenance') == 'synthetic':
        return 'engineering'
    return 'legal_confirmed' if label.get('approved_for_scoring') is True and label.get('expected_checks') else 'real_observation'


def grade(result, label):
    findings = (result or {}).get('rule_results', (result or {}).get('findings', []))
    checks = []
    for expected in label.get('expected_checks', []):
        rid = expected['rule_id']
        actual = [f.get('status', f.get('ai_status')) for f in findings if f['rule_id'] == rid]
        passed = bool(result) and bool(actual) and all(s in expected['statuses'] for s in actual)
        issue_statuses = [i.get('ai_status', i.get('status')) for i in (result or {}).get('issues', []) if i['rule_id'] == rid]
        if any(s == 'flag' and s not in expected['statuses'] for s in issue_statuses):
            passed = False
        item = {'rule_id': rid, 'expected': expected, 'actual': actual, 'passed': passed, 'status_passed': passed,
                'scorable': group_for(label) != 'real_observation'}
        if 'issue_count' in expected:
            count = sum(i['rule_id'] == rid and i.get('ai_status', i.get('status')) not in ('no_flag_for_target_rule', 'not_applicable') for i in (result or {}).get('issues', [])) if result and 'issues' in result else None
            item['actual_issue_count'] = count
            item['passed'] = passed and count == expected['issue_count']
        checks.append(item)
    return checks


def summarize(records):
    summary = {}
    for group in ('engineering', 'legal_confirmed', 'real_observation'):
        rows = [r for r in records if r['group'] == group]
        checks = [c for r in rows for c in r['checks'] if c['scorable']]
        summary[group] = {'requests': len(rows), 'failed_requests': sum(r['status'] == 'failed' for r in rows),
                          'checks': len(checks), 'passed': sum(c['passed'] for c in checks),
                          'status_passed': sum(c.get('status_passed', c['passed']) for c in checks)}
    return summary


def evidence_metrics(result, payload):
    sources = {b['id']: b['text'] for b in payload['blocks']}
    # Candidate source IDs may be namespaced; retain original and material-prefixed IDs.
    for material in payload['bundle'].get('materials', []):
        for b in material.get('blocks', []):
            sources[b['id']] = b['text']
            sources[f"{material['id']}:{b['id']}"] = b['text']
    evidence = []
    def walk(obj):
        if isinstance(obj, dict):
            if 'block_id' in obj and 'quote' in obj:
                evidence.append(obj)
            for value in obj.values(): walk(value)
        elif isinstance(obj, list):
            for value in obj: walk(value)
    walk(result)
    unique = {(e['block_id'], e['quote']) for e in evidence}
    return {'unique_quotes': len(unique), 'grounded_quotes': sum(b in sources and q in sources[b] for b, q in unique),
            'scope': 'Literal quote grounding only; not legal correctness.'}


def run_case(case, repeat, mode, settings, rules):
    from app.review_jobs import review
    payload = assemble_input(case, rules)
    started = time.monotonic()
    stages = []
    def progress(stage, *args, **kwargs):
        stages.append({'stage': str(stage), 'elapsed_seconds': round(time.monotonic() - started, 3)})
    effective = payload if mode == 'candidate' else {k: v for k, v in payload.items() if k != 'bundle'}
    row = {'case_id': case['case_id'], 'repeat': repeat, 'input_sha256': digest(payload),
           'effective_input_sha256': digest(effective), 'input_characters': len(json.dumps(effective, ensure_ascii=False)),
           'stages': stages}
    try:
        if mode == 'baseline':
            row.update(prompt_version='redlines-v7', prompt_sha256=prompt_hash('redlines-v7'))
            result = {'findings': review(settings, settings.model, payload['blocks'], payload['context'], rules,
                                        prompt_version='redlines-v7', progress_callback=progress)}
        else:
            from app.interactive_review import review_interactive, PROMPT_VERSION, prompt_hash as candidate_hash, schema_hash
            row.update(prompt_version=PROMPT_VERSION, prompt_sha256=candidate_hash(), schema_sha256=schema_hash())
            result = review_interactive(settings, settings.model, payload['blocks'], payload['context'], rules,
                                        payload['bundle'], progress_callback=progress)
        coverage = result.get('rule_results', result.get('findings', []))
        traces = [f.get('extraction_diagnostics', {}).get('attempts', []) for f in coverage if f.get('rule_id') == 'RL-04']
        row.update(status='validated', result=result, evidence=evidence_metrics(result, payload), llm_calls=len(traces[0]) if traces else None)
    except Exception as exc:
        # Deliberately exclude exception text / upstream body / credentials.
        diagnostics = [{k: v for k, v in d.items() if k in ('type', 'reason', 'location')} for d in getattr(exc, 'diagnostics', []) if isinstance(d, dict)]
        row.update(status='failed', error={'code': getattr(exc, 'code', type(exc).__name__), 'diagnostics': diagnostics}, llm_calls=len(getattr(exc, 'attempts', [])))
    row['elapsed_seconds'] = round(time.monotonic() - started, 3)
    row['first_usable_result_seconds'] = row['elapsed_seconds'] if row['status'] == 'validated' else None
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['baseline', 'candidate'], required=True)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+')
    args = parser.parse_args()
    if args.repeats < 1: parser.error('--repeats must be positive')
    cases = [json.loads(line) for line in (HERE / 'interactive.inputs.jsonl').read_text().splitlines()]
    if args.cases:
        unknown = set(args.cases) - {c['case_id'] for c in cases}
        if unknown: parser.error('unknown cases: ' + ', '.join(sorted(unknown)))
        cases = [c for c in cases if c['case_id'] in args.cases]
    all_rules = json.loads((ROOT / 'analysis/legal-corpus/draft-v0.1/rules.json').read_text())['rules']
    rules = [{k: r[k] for k in ('id', 'title', 'trigger', 'non_trigger_or_exceptions', 'insufficient_evidence_behavior')}
             for r in all_rules if r['id'].startswith('RL-')]
    settings = Settings.load()
    rows = []
    began = time.monotonic()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    metadata = {'mode': args.mode, 'model': settings.model, 'timeout_seconds': settings.timeout,
                'gateway_sha256': sha256(settings.base_url.encode()).hexdigest(),
                'baseline_prompt_sha256': prompt_hash('redlines-v7'), 'rules_sha256': digest(rules),
                'dataset_sha256': digest(cases),
                'implementation_sha256': {name: sha256((HERE.parent / 'app' / name).read_bytes()).hexdigest() for name in ('structured_review.py', 'interactive_review.py', 'attachment_review.py', 'review_issues.py') if (HERE.parent / 'app' / name).exists()},
                'expected_requests': len(cases) * args.repeats,
                'repeats': args.repeats, 'workers': 2,
                'scope': 'Engineering and confirmed legal checks separate. Baseline sees main document; candidate additionally sees frozen materials/assertions/links. No legal accuracy claim for unapproved labels. Failed calls remain in denominator.',
                'usage': 'Gateway token usage is not exposed by the review API; unavailable, not estimated.'}
    def save():
        report = metadata | {'created_at': datetime.now(timezone.utc).isoformat(),
                             'wall_seconds': round(time.monotonic() - began, 3), 'summary': summarize(rows),
                             'missing_expectations': [r['case_id'] for r in rows if not r['checks']],
                             'records': sorted(rows, key=lambda r: (r['case_id'], r['repeat']))}
        temporary = args.output.with_suffix('.tmp')
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(args.output)
    save()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run_case, c, n, args.mode, settings, rules) for c in cases for n in range(1, args.repeats + 1)]
        for future in as_completed(futures):
            row = future.result()
            # Expectations only enter the grader after inference, never the model assembly.
            labels = {x['case_id']: x for x in map(json.loads, (HERE / 'interactive.expectations.jsonl').read_text().splitlines())}
            label = labels.get(row['case_id'], {'expected_checks': []})
            row.update(group=group_for(label), checks=grade(row.get('result'), label))
            rows.append(row)
            save()
            print(row['case_id'], row['repeat'], row['status'], flush=True)
    print(json.dumps(summarize(rows), ensure_ascii=False))


if __name__ == '__main__':
    main()
