"""Independent issue identities and deterministic rule aggregation."""
from copy import deepcopy
from hashlib import sha256
import re

RESULT_SCHEMA_VERSION = 'interactive-review-v1'
STATUSES = {'flag', 'insufficient_evidence', 'no_flag_for_target_rule', 'not_applicable'}

LIABILITY_CLAUSE_MODE = 'liability_clause'
LIABILITY_TOPICS = {
    'fee_forfeiture': '已履约费用结算', 'stacked_remedies': '责任适用与叠加',
    'repeat_deduction': '按次扣减', 'daily': '按日计费', 'paid_refund': '解约退款',
    'other_liability': '供应方责任',
}


def liability_clause_issues(rule):
    if rule.get('execution_state')!='completed':
        return []
    paragraphs = (rule.get('card_content') or {}).get('risk_paragraphs',[])
    anchors = {e['block_id']:e for e in rule.get('evidence',[])}
    issues = {}
    for paragraph in paragraphs:
        kind = paragraph.get('kind')
        evidence = paragraph.get('evidence',[])
        if kind not in LIABILITY_TOPICS or not evidence or not paragraph.get('text'):
            continue
        anchor = evidence[0]
        bid = anchor['block_id']
        if any(anchors.get(e['block_id'])!=e for e in evidence):
            continue
        number = re.match(r'^\s*(\d+(?:\.\d+)+)(?=[^\d.]|$)',anchor['quote'])
        topic = paragraph.get('title') or LIABILITY_TOPICS[kind]
        title = f'{number[1]} {topic}' if number else topic
        key = 'VL-01:' + sha256(f'{bid}:{anchor["start"]}:{anchor["end"]}'.encode()).hexdigest()[:24]
        issue = dict(
            rule_id='VL-01',subject_key=key,event_id=key,event_anchor=anchor,evidence=evidence,
            title=title,**({'clause_number':number[1]} if number else {}),
            explanation=paragraph['text'],suggested_text=None,status=paragraph.get('status') or 'insufficient_evidence',
            execution_state='completed',execution_mode=LIABILITY_CLAUSE_MODE,display_group='legal_issue',
            review_category='transaction',review_state='reviewed',mechanisms=[kind],
            provenance={'origin':'configured_rule','rule_id':'VL-01'},
            presentation=dict(version='issue-presentation-v1',title=title,summary=paragraph['text'],
                              next_step=paragraph.get('direction') or '',observations=[]),
        )
        issues[key] = issue
    return list(issues.values())


def summarize_rule_status(statuses):
    if not statuses or any(s not in STATUSES for s in statuses):
        raise ValueError('Rule aggregation requires valid coverage results')
    for status in ('flag', 'insufficient_evidence', 'no_flag_for_target_rule', 'not_applicable'):
        if status in statuses:
            return status


def build_review_issues(run_id, findings, attachment_checks, *, expected_rule_ids=None, additional_issues=None, split_liability=False):
    expected_rule_ids = expected_rule_ids or [f'RL-0{i}' for i in range(1, 6)]
    if sorted(f['rule_id'] for f in findings) != sorted(expected_rule_ids):
        raise ValueError('Exactly five rule coverage results required')
    rules = deepcopy(findings)
    issues = []
    for rule in rules:
        rid = rule['rule_id']
        if rid == 'RL-04':
            candidates = deepcopy(attachment_checks)
            if candidates:
                rule['status'] = summarize_rule_status([c['status'] for c in candidates])
                rule['explanation'] = '已逐项核验正文引用的附件；各项状态及依据见独立核验项。'
                rule['evidence'] = list({(e['block_id'], e['start'], e['end']): e for c in candidates for e in c['evidence']}.values())
            rule['attachment_checks'] = deepcopy(candidates)
            if additional_issues is not None and not candidates and rule['status'] in ('flag','insufficient_evidence'):
                candidates=[deepcopy(rule)]
        elif rid=='VL-01' and split_liability:
            candidates = liability_clause_issues(rule) or [deepcopy(rule)]
        elif rid.startswith('CR-'):
            candidates = [deepcopy(i) for i in additional_issues or [] if i['rule_id'] == rid]
            if not candidates and rule.get('execution_state') == 'failed': candidates = [deepcopy(rule)]
        else:
            candidates = [deepcopy(rule)]
        for item in candidates:
            key = item.get('subject_key', rid)
            item.update(id='issue-' + sha256(f'{run_id}:{rid}:{key}'.encode()).hexdigest()[:24], run_id=run_id,
                        rule_id=rid, subject_key=key, kind='attachment' if rid == 'RL-04' else 'rule',
                        ai_status=item['status'], clause_ids=item.get('clause_ids', []), supersedes_issue_id=None)
            issues.append(item)
    return {'result_schema_version': 'interactive-review-v2' if additional_issues is not None else RESULT_SCHEMA_VERSION, 'rule_results': rules, 'issues': issues, 'findings': deepcopy(issues)}
