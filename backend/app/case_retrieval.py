"""Deterministic scoped retrieval. Retrieved opinions are reference data, not rules."""
import re
from hashlib import sha256
from .legal_feedback import encoded


def terms(text):
    words = set(re.findall(r'[a-z0-9_]+', text.lower()))
    for chunk in re.findall(r'[\u4e00-\u9fff]+', text):
        words.update(chunk[i:i+2] for i in range(max(1,len(chunk)-1)))
    return words


def retrieve_cases(event, context, excluded_family_ids, casebook_version, limit=3, *, cases=(), excluded_source_hashes=()):
    """Filter an immutable snapshot; caller supplies cases from that exact release."""
    if context.get('business_scope_state') != 'matched':
        return []
    role = context.get('our_party_code')
    business = context.get('business_scope') or context.get('business_scope_code')
    stage = context.get('stage')
    event_type = event.get('event_type') or event.get('issue_type')
    if not all((role, business, stage, event_type)):
        return []
    query = terms(event.get('trigger_quote','') + ' ' + event.get('text',''))
    hits = []
    hashes={h.lower() for h in excluded_source_hashes}
    if context.get('document_sha256'):hashes.add(context['document_sha256'].lower())
    for case in cases:
        scope = case.get('scope', {})
        if case.get('source_binding')!='verified_version' or not case.get('source_version_id'):
            continue
        if (case.get('source_hash') or '').lower() in hashes:
            continue
        if case.get('state') != 'confirmed' or case.get('family_id') in excluded_family_ids:
            continue
        if not all(value in scope.get(key, []) for key,value in [('roles',role),('business_scopes',business),('stages',stage),('event_types',event_type)]):
            continue
        # Narrative exceptions cannot be evaluated safely by lexical retrieval.
        if case.get('exceptions'):
            continue
        words = terms(case['original_span'] + ' ' + case['final_opinion'])
        score = len(query & words) / max(1,len(query | words))
        if not score:
            continue
        hits.append({**case, 'scope_match':True, 'score':score, 'casebook_version':casebook_version,
                     'content_digest':sha256(encoded(case).encode()).hexdigest(), 'usage':'reference_data_only'})
    return sorted(hits,key=lambda h:(-h['score'], h['case_id']))[:max(0,min(limit,20))]
