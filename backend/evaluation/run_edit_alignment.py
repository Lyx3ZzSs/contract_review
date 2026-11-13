"""Conservative offline alignment scorer; never calls a model or a business DB.

Actual records are EVALUATOR annotations, not raw model responses. *_review fields
must be filled by an independent human reviewing the stored raw model response.
A candidate target mapping alone does not credit an event, reason or semantics.
"""
import argparse
import json
from pathlib import Path

FORBIDDEN={'gold','reviewer_comments','revision_ids','accepted_text','raw_xml','historical_comment'}
def contaminated(value):
    if isinstance(value,dict): return bool(FORBIDDEN.intersection(value)) or any(contaminated(v) for v in value.values())
    if isinstance(value,list): return any(contaminated(v) for v in value)
    return False

def score_edit_alignment(gold, actual, sources):
    envelope=actual if isinstance(actual,dict) else {'findings':actual}
    findings=envelope.get('findings',[])
    families={g.get('family_id') for g in gold}
    leak=contaminated(sources) or any(c.get('family_id') in families for c in envelope.get('retrieved_cases',[]))
    if leak: return {'state':'blocked','block_reason':'same_family_answer_leakage','semantic_review_state':'blocked'}
    if envelope.get('execution_state') in ('failed','incomplete','blocked'):
        return {'state':'blocked','block_reason':'model_execution_incomplete','semantic_review_state':'blocked'}
    blocks=sources.get('blocks',[]) if isinstance(sources,dict) else sources
    texts={b['id']:b['text'] for b in blocks}
    used=set();rows=[]
    for g in gold:
        candidate=[a for a in findings if g['target_id'] in a.get('matched_target_ids',[])]
        ga=g.get('anchor') or {}
        def same_anchor(a):
            aa=a.get('anchor') or {}
            return all(aa.get(k)==ga.get(k) for k in ('block_id','start','end')) and ga.get('block_id') in texts
        a=next((x for x in candidate if same_anchor(x)),candidate[0] if candidate else None)
        exact=False
        if a:
            used.add(a.get('id'))
            aa=a.get('anchor') or {}; start=aa.get('start',-1);end=aa.get('end',-1)
            valid=isinstance(start,int) and isinstance(end,int) and 0<=start<=end<=len(texts.get(aa.get('block_id'),''))
            exact=same_anchor(a) and valid
            if g['kind']=='edit': exact=exact and a.get('before_text')==g['before_text']==texts[ga['block_id']][start:end]
        action=bool(a and g['kind']=='edit' and a.get('operation')==g['operation'] and a.get('after_text')==g['after_text'])
        event=bool(a and exact and a.get('event_review')=='confirmed')
        reason=bool(a and exact and a.get('reason_review')=='confirmed')
        semantics=bool(a and a.get('semantic_review')=='confirmed')
        policy=(a or {}).get('policy_basis_state','unreviewed')
        if g.get('policy_basis_state')=='context_required' and not (a or {}).get('verified_policy_refs'): policy='context_required'
        blocked=not ga or g.get('verification_state')=='blocked'
        complete=event and reason and semantics and policy=='supported' and (g['kind']!='edit' or (exact and action))
        rows.append({'target_id':g['target_id'],'kind':g['kind'],'actual_id':(a or {}).get('id'),'event_match':event,'reason_match':reason,'range_match':exact,'action_match':action,'policy_basis_state':policy,'semantic_review_state':'confirmed' if semantics else 'pending','state':'blocked' if blocked else 'matched' if complete else 'partial' if a else 'missed'})
    edits=[r for r in rows if r['kind']=='edit'];comments=[r for r in rows if r['kind']=='comment']
    return {'state':'complete' if rows and all(r['state']=='matched' for r in rows) else 'partial', 'evaluation_mode':envelope.get('evaluation_mode','independent_review'),'event_coverage':sum(r['event_match'] for r in edits),'event_total':len(edits),'reason_coverage':sum(r['reason_match'] for r in comments),'reason_total':len(comments),'edit_range_matches':sum(r['range_match'] for r in edits),'edit_action_matches':sum(r['action_match'] and r['range_match'] for r in edits),'policy_basis_state':'supported' if rows and all(r['policy_basis_state']=='supported' for r in rows) else 'unresolved','semantic_review_state':'confirmed' if rows and all(r['semantic_review_state']=='confirmed' for r in rows) else 'pending','extra_findings':[a.get('id') for a in findings if a.get('id') not in used], 'extra_findings_correctness':'unadjudicated_not_false_positives','rows':rows}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--gold',required=True);parser.add_argument('--actual',required=True);parser.add_argument('--inputs',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    gold=[json.loads(l) for l in Path(args.gold).read_text().splitlines() if l.strip()]
    source=json.loads(Path(args.inputs).read_text().splitlines()[0])
    result=score_edit_alignment(gold,json.loads(Path(args.actual).read_text()),source)
    Path(args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2))
