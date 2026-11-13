"""Run controlled live comparisons. Inputs and expectations are never combined in requests."""
import argparse,json,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
from app.llm import Settings,ExtractionError
from app.review_jobs import review,output_schema
from app.review_policy import prompt_hash

ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).parent

def grade(findings,expected):
    # Every finding for a rule must agree; one good finding cannot hide another bad one.
    return [{'rule_id':rid,'expected':allowed,'actual':sorted({f['status'] for f in findings if f['rule_id']==rid}),
             'passed':bool([f for f in findings if f['rule_id']==rid]) and all(f['status'] in allowed for f in findings if f['rule_id']==rid)} for rid,allowed in expected.items()]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--versions',nargs='+',default=['redlines-v1','redlines-v2']);ap.add_argument('--model',default='deepseek-v4-flash');ap.add_argument('--repeats',type=int,default=1);ap.add_argument('--workers',type=int,default=3);ap.add_argument('--cases',nargs='*');ap.add_argument('--output',default='comparison.json');args=ap.parse_args()
    cases=[json.loads(x) for x in (HERE/'inputs.jsonl').read_text().splitlines()]
    if args.cases:cases=[c for c in cases if c['id'] in args.cases]
    expectations={x['id']:x for x in map(json.loads,(HERE/'expectations.jsonl').read_text().splitlines())}
    all_rules=json.loads((ROOT/'analysis/legal-corpus/draft-v0.1/rules.json').read_text())['rules']
    rules=[{k:r[k] for k in ('id','title','trigger','non_trigger_or_exceptions','insufficient_evidence_behavior')} for r in all_rules if r['id'].startswith('RL-')]
    settings=Settings.load();out=HERE/args.output;records=[]
    def run(case,version,repeat):
        began=time.monotonic();row={'case_id':case['id'],'split':case['split'],'prompt_version':version,'prompt_sha256':prompt_hash(version),'output_schema_sha256':sha256(json.dumps(output_schema(version).model_json_schema(),sort_keys=True).encode()).hexdigest(),'repeat':repeat,'input_sha256':sha256(json.dumps({'blocks':case['blocks'],'context':case['context'],'rules':rules},ensure_ascii=False,sort_keys=True).encode()).hexdigest()}
        try:
            row['findings']=review(settings,args.model,case['blocks'],case['context'],rules,prompt_version=version)
            row['checks']=grade(row['findings'],expectations[case['id']]['expected']);row['status']='validated'
        except ExtractionError as exc:row.update(status='failed',error={'code':exc.code,'message':exc.message,'diagnostics':getattr(exc,'diagnostics',[])},checks=[{'rule_id':rid,'passed':False,'actual':[],'expected':allowed} for rid,allowed in expectations[case['id']]['expected'].items()])
        row['elapsed_seconds']=round(time.monotonic()-began,2);return row
    def save():
        summary={}
        for v in args.versions:
            rows=[r for r in records if r['prompt_version']==v];checks=[c for r in rows for c in r['checks']]
            summary[v]={'completed_requests':len(rows),'failed_requests':sum(r['status']=='failed' for r in rows),'targeted_checks':len(checks),'status_agreements':sum(c['passed'] for c in checks),'all_target_checks_passed_cases':sum(all(c['passed'] for c in r['checks']) for r in rows)}
        out.write_text(json.dumps({'created_at':datetime.now(timezone.utc).isoformat(),'model':args.model,'timeout_seconds':settings.timeout,'expected_requests':len(cases)*len(args.versions)*args.repeats,'repeats':args.repeats,'metrics_scope':'Provisional engineering status agreement, not legal accuracy. Failed requests count as failed checks. No evaluation labels enter model requests.','summary':summary,'records':sorted(records,key=lambda x:(x['case_id'],x['prompt_version'],x['repeat']))},ensure_ascii=False,indent=2)+'\n')
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(run,c,v,n) for c in cases for n in range(1,args.repeats+1) for v in args.versions]
        for f in as_completed(futures):
            r=f.result();records.append(r);save();print(r['case_id'],r['prompt_version'],r['repeat'],r['status'],sum(c['passed'] for c in r['checks']),'/',len(r['checks']),r['elapsed_seconds'],flush=True)
    print(json.dumps(json.loads(out.read_text())['summary'],ensure_ascii=False),flush=True)

if __name__=='__main__':main()
