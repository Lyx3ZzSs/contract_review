"""Compare saved reports; never perform model calls or change runtime policy."""
import argparse
import json
from pathlib import Path
from .run_interactive_review import HERE, grade, group_for, summarize


def attachment_score(result, label):
    expected = label.get('expected_attachment_states')
    available = bool(result is not None and 'attachment_checks' in result)
    actual = sorted(c.get('match_state', c.get('attachment_state', c.get('state', 'unknown'))) for c in (result or {}).get('attachment_checks', []))
    return {'available': available, 'expected': expected, 'actual':actual,
            'passed': expected is not None and available and sorted(expected) == actual}


def compare_reports(baseline, candidate, labels):
    configuration = ('model', 'timeout_seconds', 'gateway_sha256', 'rules_sha256', 'dataset_sha256', 'repeats')
    mismatches = [k for k in configuration if baseline.get(k) != candidate.get(k)]
    indexed = [{(r['case_id'],r['repeat']):r for r in report['records']} for report in (baseline,candidate)]
    changes, regressions, improvements = [], [], []
    attachment_comparisons = []
    graded = [[], []]
    for key in sorted(set(indexed[0]) | set(indexed[1])):
        pair = [data.get(key) for data in indexed]
        label = labels.get(key[0], {'expected_checks': []})
        checks = [grade((row or {}).get('result'), label) for row in pair]
        if 'expected_attachment_states' in label:
            attachment_comparisons.append({'case_id':key[0], 'repeat':key[1], 'baseline':attachment_score((pair[0] or {}).get('result'), label), 'candidate':attachment_score((pair[1] or {}).get('result'), label)})
        for n, row in enumerate(pair):
            if row: graded[n].append(row | {'checks':checks[n], 'group':group_for(label)})
        if not all(pair):
            changes.append({'case_id':key[0], 'repeat':key[1], 'reason':'missing_run'})
            continue
        if pair[0]['input_sha256'] != pair[1]['input_sha256']:
            mismatches.append(f'input:{key[0]}:{key[1]}')
        for a,b in zip(*checks):
            detail = {'case_id':key[0], 'repeat':key[1], 'group':group_for(label), 'rule_id':a['rule_id'],
                      'baseline':a, 'candidate':b,
                      'classification': ('execution_failure' if pair[1]['status'] == 'failed' else
                          'false_positive' if 'flag' in b['actual'] and 'flag' not in b['expected']['statuses'] else
                          'missed_expected_review' if any(s in ('flag','insufficient_evidence') for s in b['expected']['statuses']) and all(s in ('no_flag_for_target_rule','not_applicable') for s in b['actual']) else
                          'status_or_capability_change'), 'baseline_status':pair[0]['status'], 'candidate_status':pair[1]['status']}
            if a['passed'] != b['passed'] or a['actual'] != b['actual']:
                changes.append(detail)
            if a['scorable'] and a['status_passed'] and not b['status_passed']:
                regressions.append(detail)
            if a['scorable'] and not a['passed'] and b['passed']:
                improvements.append(detail)
    complete = all(len(r['records']) == r['expected_requests'] for r in (baseline,candidate)) and set(indexed[0]) == set(indexed[1])
    return {'same_configuration':not mismatches,'configuration_mismatches':mismatches,'complete':complete,
            'summary':{'baseline':summarize(graded[0]),'candidate':summarize(graded[1])},
            'changes':changes,'regressions':regressions,'improvements':improvements,
            'failed_calls': {name:[{'case_id':r['case_id'],'repeat':r['repeat'],'error':r.get('error')} for r in report['records'] if r['status']=='failed'] for name,report in (('baseline',baseline),('candidate',candidate))},
            'attachment_comparisons':attachment_comparisons,
            'fact_extraction_scope':'附件状态分项比较；未建立法务批准的全文事实抽取金标，不报告泛化事实准确率。',
            'enable_candidate':False,
            'activation_note':'仅评估，不自动改生产默认。需确定性完整验收、目标偏差改善及人工审核；法务确认高风险样本为空时不能宣称法律准确率或无新增漏报。',
            'scope':'基线与候选正文/规则相同；候选额外读取资料包。逐字证据统计不等于语义评分。'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    labels={r['case_id']:r for r in map(json.loads,(HERE/'interactive.expectations.jsonl').read_text().splitlines())}
    result=compare_reports(json.loads(args.baseline.read_text()),json.loads(args.candidate.read_text()),labels)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('same_configuration','complete','summary')},ensure_ascii=False))

if __name__=='__main__': main()
