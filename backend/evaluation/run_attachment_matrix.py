import argparse,json,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from datetime import datetime,timezone
from app.llm import Settings,ExtractionError
from app.structured_review import Sources,FACT_PROMPT,INDEXED_FACT_PROMPT,ContractFacts,normalize_facts,normalize_indexed_facts,extract_call,grounded_role,TECH,PRICE
from app.amount_review import classify
from app.reference_index import index_references
from app.review_policy import prompt_hash
HERE=Path(__file__).parent

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--repeats',type=int,default=2);ap.add_argument('--cases',nargs='*');ap.add_argument('--output');ap.add_argument('--workers',type=int,default=2);ap.add_argument('--version',default='redlines-v6',choices=['redlines-v6','redlines-v7']);args=ap.parse_args()
 cases=list(map(json.loads,(HERE/'attachments.inputs.jsonl').read_text().splitlines()));labels={x['id']:x for x in map(json.loads,(HERE/'attachments.expectations.jsonl').read_text().splitlines())}
 if args.cases:cases=[c for c in cases if c['id'] in args.cases]
 settings=Settings.load();records=[]
 def run(case,repeat):
  trace=[];started=time.monotonic();sources=Sources(case['blocks']);row={'case_id':case['id'],'repeat':repeat,'attempts':trace}
  try:
   if args.version=='redlines-v7':
    seeds,plans=index_references(sources,grounded_role,TECH,PRICE)
    _,(facts,(attachments,amounts,fields),normalization)=extract_call(settings,'deepseek-v4-flash',INDEXED_FACT_PROMPT,ContractFacts,{'context':case['context'],'blocks':sources.public,'attachment_reference_candidates':seeds,'normalized_instalment_candidates':plans},lambda x:normalize_indexed_facts(x,sources,seeds,plans),time.monotonic()+settings.timeout,trace)
    row['normalization']=normalization
   else:
    facts,(attachments,amounts,fields)=extract_call(settings,'deepseek-v4-flash',FACT_PROMPT,ContractFacts,{'context':case['context'],'blocks':sources.public},lambda x:normalize_facts(x,sources),time.monotonic()+settings.timeout,trace)
   kinds={a['name']:a['kind'] for a in attachments};status,_,_=classify(amounts)
   dependencies=sorted({m.attachment_name for m in facts.missing_prices if m.attachment_name})
   label=labels[case['id']];row.update(status='validated',facts=facts.model_dump(mode='json'),attachments=attachments,actual_kinds=kinds,amount_status=status,pricing_dependencies=dependencies,
    passed=kinds==label['kinds'] and status==label['amount_status'] and dependencies==sorted(label['pricing_dependencies']))
  except ExtractionError as e:row.update(status='failed',passed=False,error={'code':e.code,'http_status':getattr(e,'status_code',None),'diagnostics':getattr(e,'diagnostics',[])})
  row['elapsed_seconds']=round(time.monotonic()-started,3);return row
 with ThreadPoolExecutor(max_workers=args.workers) as pool:
  futures=[pool.submit(run,c,n) for c in cases for n in range(1,args.repeats+1)]
  for f in as_completed(futures):
   r=f.result();records.append(r)
   report={'created_at':datetime.now(timezone.utc).isoformat(),'policy':args.version,'prompt_sha256':prompt_hash(args.version),'model':'deepseek-v4-flash','expected_requests':len(cases)*args.repeats,'summary':{'requests':len(records),'validated':sum(x['status']=='validated' for x in records),'passed':sum(x['passed'] for x in records),'rejected_attempts':sum(a['status']=='rejected' for x in records for a in x['attempts'])},'scope':'Synthetic engineering checks, not legal accuracy; no labels sent to model.','records':sorted(records,key=lambda x:(x['case_id'],x['repeat']))}
   (HERE/(args.output or f'attachments-{args.version}-results.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
   print(r['case_id'],r['repeat'],r['status'],r['passed'],flush=True)
if __name__=='__main__':main()
