"""Offline evidence screening. Candidate matches always require semantic human review."""
import re


def score_targets(case: dict, labels: list[dict], issues: list[dict]) -> list[dict]:
    blocks = {b['id']: b['text'] for b in case['blocks']}
    rows = []
    for label in labels:
        matches = []; component_matches=set()
        for index, issue in enumerate(issues):
            clause = label['clause_number']
            evidence = issue.get('evidence') or []
            located = any(re.search(r'(?<![\d.])'+re.escape(clause)+r'(?![\d.])', blocks.get(ref.get('block_id'), '')) for ref in evidence)
            if str(issue.get('clause_number', '')) != clause and not located:
                continue
            grounded = []
            for ref in evidence:
                quote = ref.get('quote', '')
                text = blocks.get(ref.get('block_id'), '')
                if quote and quote in text and re.search(r'(?<![\d.])'+re.escape(clause)+r'(?![\d.])', text):
                    grounded.append(quote)
            mechanism = issue.get('mechanism', '') or issue.get('description', '') or issue.get('explanation', '')
            terms = label.get('original_mechanism_terms', [])
            if label.get('mechanisms'):
                supported=[j for j,m in enumerate(label['mechanisms']) if issue.get('review_reason')==m['reason'] and re.search(m['explanation_pattern'],mechanism) and any(re.search(m['source_pattern'],q) for q in grounded)]
                if grounded:component_matches.update(supported)
                mechanism_supported=bool(supported)
            else:
                mechanism_supported = bool(mechanism) and bool(terms) and all(t in mechanism and any(t in q for q in grounded) for t in terms)
            if grounded and mechanism_supported:
                matches.append(index)
        rows.append({'case_id':case['id'],'target_id':label['target_id'],
                     'candidate_match':bool(matches) and (not label.get('mechanisms') or len(component_matches)==len(label['mechanisms'])),'matching_issue_indices':matches,
                     'human_semantic_review':'pending','approved_accuracy_eligible':False,
                     'note':'自动结果仅为证据筛选；接受修订稿须人工核对删除内容与剩余机制，不能据此宣称通过。'})
    return rows


def score_reviewed(original, reviewed, labels, issues):
    old = '\n'.join(b['text'] for b in original['blocks'])
    new = '\n'.join(b['text'] for b in reviewed['blocks'])
    rows=[]
    for label in labels:
        clause=label['clause_number']
        old_clause='\n'.join(b['text'] for b in original['blocks'] if re.search(r'(?<![\d.])'+re.escape(clause)+r'(?![\d.])', b['text']))
        stale=[]
        for i,issue in enumerate(issues):
            for ref in issue.get('evidence',[]):
                quote=ref.get('quote','')
                if quote and quote in old_clause and quote not in new:
                    stale.append(i)
        rows.append({'target_id':label['target_id'],'deleted_quote_issue_indices':sorted(set(stale)),
                     'reviewed_expectation':label['reviewed_expectation'],
                     'human_semantic_review':'pending','approved_accuracy_eligible':False,
                     'note':'无已删引用不代表机制正确；须人工核对剩余限制、责任回指和局部上限。'})
    return rows


def main():
    import argparse
    import hashlib
    import json
    import time
    from pathlib import Path
    from datetime import datetime, timezone
    from app.llm import Settings
    parser=argparse.ArgumentParser()
    parser.add_argument('--policy',default='review-liability-v1')
    parser.add_argument('--model',required=True)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    here=Path(__file__).resolve().parent
    cases=[json.loads(s) for s in (here/'wuwei_alignment.inputs.jsonl').read_text().splitlines() if s]
    digest=lambda x:hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    from app.rule_registry import resolve_rules
    rules=resolve_rules(args.policy)
    manifest={'policy':args.policy,'model':args.model,'rules_sha256':digest(rules),'inputs_sha256':digest(cases)}
    report={'manifest':manifest,'records':[],'legal_confirmed_accuracy':'尚不可计算',
            'warning':'开发校准案例；自动证据筛选不等于语义通过或法务确认准确率'}
    if args.output.exists():
        report=json.loads(args.output.read_text())
        if report['manifest'] != manifest:
            raise ValueError('恢复文件与本次模型、规则或输入不一致')
    from app.accurate_review import review_accurate
    settings=Settings.load()
    def save():
        args.output.parent.mkdir(parents=True,exist_ok=True)
        tmp=args.output.with_suffix(args.output.suffix+'.tmp')
        tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2))
        tmp.replace(args.output)
    for case in cases:
        for repeat in range(1,args.repeats+1):
            previous=[r for r in report['records'] if r['case_id']==case['id'] and r['repeat']==repeat]
            if any(r['status']=='succeeded' for r in previous):
                continue
            started=time.monotonic()
            stages=[]
            row={'case_id':case['id'],'repeat':repeat,'attempt':len(previous)+1,
                 'resumed':bool(previous),'input_sha256':digest(case),'stages':stages,
                 'started_at':datetime.now(timezone.utc).isoformat()}
            def progress(stage,*a,**kw):
                stages.append({'stage':str(stage),'elapsed_seconds':round(time.monotonic()-started,3)})
            try:
                result=review_accurate(settings,args.model,case['blocks'],case['context'],rules,
                                      policy_version=args.policy,progress_callback=progress)
                row['result']=result
                row['status']='failed' if result.get('module_errors') else 'succeeded'
                # Gold is loaded only after the candidate has returned; never passed to review.
                labels=[json.loads(s) for s in (here/'wuwei_alignment.expectations.jsonl').read_text().splitlines() if s]
                row['targets']=(score_reviewed(cases[0],case,labels,result.get('issues',[]))
                                if case['view']=='accepted_revisions' else score_targets(case,labels,result.get('issues',[])))
                row['false_positive_review']={'state':'pending','items':[]}
            except Exception as exc:
                row['status']='failed'
                row['error_type']=type(exc).__name__
                row['error']='调用失败；详细错误请在本地日志核查，避免将配置凭证写入报告'
            row['elapsed_seconds']=round(time.monotonic()-started,3)
            report['records'].append(row)
            save()
    return report


if __name__ == '__main__':
    main()
