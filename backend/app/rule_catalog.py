"""Read-only editorial views and recorded evaluations; never part of execution snapshots."""
import json
from pathlib import Path
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / 'analysis/legal-corpus/draft-v0.1'
EVALUATION = ROOT / 'backend/evaluation'
PRESENTATION_VERSION = 'rule-display-v1'
TITLES = {
    'CR-03': ('付款方式的财务确认', '核对非现金支付方式、适用条件及财务确认依据。'),
    'CR-04': ('软件使用保护', '结合交付范围核对软件使用限制，通用要求仍需确认。'),
    'CR-05': ('逾期付款救济', '核对我方暂停服务或解除权，具体期限依据需确认。'),
    'CR-01': ('累计责任范围与上限', '依据本案条款核对扣款次数和累计责任；公司阈值待确认。'),
    'CR-02': ('责任叠加与已履约费用保护', '核对考核、退费、违约金、赔偿及已履约费用的关系，提交法务复核。'),
    'RL-01': ('服务期限是否一致', '在相同对象、期限类型和起算条件下核对期限。'),
    'RL-02': ('金额计算是否一致', '核对同口径的单价、数量、比例和总额。'),
    'RL-03': ('客户转让是否需我方同意', '检查客户是否被明确允许未经我方同意转让。'),
    'RL-04': ('引用附件是否齐全', '核对正文引用的附件，并说明本次材料的缺口。'),
    'RL-05': ('关键内容是否填写完整', '结合合同阶段，检查关键内容的空白或占位。'),
}
STATUS = {'flag': '发现目标规则问题', 'insufficient_evidence': '证据不足，需核对',
          'no_flag_for_target_rule': '未触发本项规则', 'not_applicable': '不适用'}
KINDS = {'technical': '技术用途', 'pricing': '计价用途', 'mixed': '技术及计价用途',
         'unknown': '用途不明', 'other': '其他用途'}


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise HTTPException(503, f'规则资料暂不可用：{path.name}') from exc


def rows(path):
    try:
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except (OSError, ValueError) as exc:
        raise HTTPException(503, f'案例资料暂不可用：{path.name}') from exc


def presentation():
    confirmation = read(CORPUS / 'execution-logic-confirmation.json')
    sources = read(CORPUS / 'sources.json') if (CORPUS / 'sources.json').exists() else []
    return {
        'version': PRESENTATION_VERSION,
        'items': {rid: {'title': title, 'summary': summary} for rid, (title, summary) in TITLES.items()},
        'sources': [{k: s[k] for k in ('id', 'filename', 'sha256')} for s in sources],
        'confirmation': {k: confirmation[k] for k in (
            'id', 'date', 'user_statement', 'scope', 'pending_configuration', 'not_covered')},
        'current_scope': '当前仅检查已解析正文。附件资料包联审尚未接入，不能据此确认全部附件齐全。',
    }


def status_text(values):
    return ' / '.join(STATUS.get(s, s) for s in values)


def kinds_text(kinds):
    return '；'.join(f'{name}：{KINDS.get(kind, kind)}' for name, kind in kinds.items()) or '无附件引用'


def trial(record, report, actual, passed, explanation='', evidence=None):
    failed = record.get('status') == 'failed'
    return {
        'repeat': record['repeat'], 'status': 'failed' if failed else record['status'],
        'actual': '执行失败' if failed else actual, 'passed': None if failed else passed,
        'explanation': explanation, 'evidence': evidence or [],
        'error_code': record.get('error', {}).get('code') if failed else None,
        'policy_version': record.get('prompt_version', report.get('policy')),
        'prompt_sha256': record.get('prompt_sha256', report.get('prompt_sha256')),
        'created_at': report['created_at'], 'model': report['model'],
        # Keep rejected format attempts as well as final request failures visible.
        'rejected_attempts': sum(a.get('status') == 'failed' for a in record.get('attempts', [])),
    }


def cases_for(rule_id):
    if rule_id not in TITLES:
        raise HTTPException(404, '规则不存在')
    cases = []
    for label in (rows(CORPUS / 'cases.labels.jsonl') if (CORPUS / 'cases.labels.jsonl').exists() else []):
        ref = label.get('reference', {})
        if label['origin'] != 'historical' or rule_id not in ref.get('rules', []):
            continue
        cases.append({
            'id': label['case_id'], 'category': 'historical', 'title': ref['title'],
            'expected': label['proposed_expected_behavior'], 'label_status': label['label_status'],
            'approved_for_scoring': label['approved_for_scoring'],
            'excerpts': [{'location': e['location'], 'text': e['original'], 'source_id': e['source_id']} for e in ref['evidence']],
            'reviewer_comment': ref.get('reviewer_comment'), 'trials': [],
            'limitation': '历史法务意见；预期结论尚未逐项裁定。本页无可关联的模型运行记录，不能计为通过。',
            'source_file': 'cases.labels.jsonl',
        })
    inputs = {r['id']: r for r in rows(EVALUATION / 'inputs.jsonl')}
    report = read(EVALUATION / 'structured-v7-repeat.json')
    for exp in rows(EVALUATION / 'expectations.jsonl'):
        if rule_id not in exp['expected']:
            continue
        trials = []
        for record in report['records']:
            if record['case_id'] != exp['id']:
                continue
            findings = [f for f in record.get('findings', []) if f['rule_id'] == rule_id]
            check = next((c for c in record.get('checks', []) if c['rule_id'] == rule_id), None)
            trials.append(trial(record, report, status_text([f['status'] for f in findings]) or '未返回本项结果',
                                check['passed'] if check else None,
                                '\n'.join(f['explanation'] for f in findings),
                                [e for f in findings for e in f.get('evidence', [])]))
        cases.append({
            'id': exp['id'], 'category': 'engineering', 'title': exp['purpose'],
            'expected': status_text(exp['expected'][rule_id]), 'label_status': exp['label_status'],
            'approved_for_scoring': False, 'excerpts': [{'location': b['id'], 'text': b['text']} for b in inputs[exp['id']]['blocks']],
            'trials': trials, 'limitation': '工程构造样例，用于检查执行口径；不代表真实合同审查准确率。',
            'source_file': 'structured-v7-repeat.json',
        })
    # Attachment classification is a distinct extraction check, not an RL-04 verdict.
    if rule_id in ('RL-02', 'RL-04'):
        inputs = {r['id']: r for r in rows(EVALUATION / 'attachments.inputs.jsonl')}
        report = read(EVALUATION / 'attachments-redlines-v7-results.json')
        for exp in rows(EVALUATION / 'attachments.expectations.jsonl'):
            def comparison(value):
                if rule_id == 'RL-04':
                    return kinds_text(value.get('actual_kinds', value.get('kinds', {})))
                deps = '、'.join(value.get('pricing_dependencies', [])) or '无'
                return f"{STATUS.get(value.get('amount_status'), '未返回金额结果')}；计价附件依赖：{deps}"
            trials = []
            for record in report['records']:
                if record['case_id'] != exp['id']:
                    continue
                passed = (record.get('actual_kinds') == exp['kinds'] if rule_id == 'RL-04' else
                          record.get('amount_status') == exp['amount_status'] and record.get('pricing_dependencies') == exp['pricing_dependencies'])
                trials.append(trial(record, report, comparison(record), passed))
            cases.append({
                'id': exp['id'], 'category': 'attachment',
                'title': '附件用途识别' if rule_id == 'RL-04' else '附件计价依赖检查',
                'expected': comparison(exp), 'label_status': 'engineering_expectation', 'approved_for_scoring': False,
                'excerpts': [{'location': b['id'], 'text': b['text']} for b in inputs[exp['id']]['blocks']],
                'trials': trials, 'limitation': '附件专项工程验证，仅核对正文引用用途及计价依赖，不验证资料包是否齐全。',
                'source_file': 'attachments-redlines-v7-results.json',
            })
    trials = [t for c in cases for t in c['trials']]
    return {'rule_id': rule_id, 'cases': cases, 'summary': {
        'historical_cases_available': (CORPUS / 'cases.labels.jsonl').exists(),
        'historical_cases': sum(c['category'] == 'historical' for c in cases),
        'engineering_cases': sum(c['category'] != 'historical' for c in cases),
        'recorded_requests': len(trials), 'differences': sum(t['passed'] is False for t in trials),
        'failed_requests': sum(t['status'] == 'failed' for t in trials),
    }}
