"""Explicit, exact-document historical guidance; never a global casebook policy.

This input is separate from independent review and from cross-contract retrieval.
The evaluation caller freezes the supplied snapshot; no corpus is read implicitly.
"""
import json
from hashlib import sha256

def stage_code(value):
    return {'起草阶段':'pre_sign', '签署前':'pre_sign', 'pre_sign':'pre_sign',
            '履行阶段':'performance', 'performance':'performance'}.get(value, value)

def freeze_runtime_guidance(blocks,context,version_id):
    """Only the explicitly maintained runtime parameter file; never evaluation gold."""
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'policies/case-parameters.json'
    if not path.exists():return None
    snapshot=json.loads(path.read_text())
    matched=bind_guidance(snapshot,blocks,context,version_id)
    ids={e['id'] for e in matched}
    return {**snapshot,'entries':[e for e in snapshot['entries'] if e['id'] in ids]} if ids else None


def text_digest(blocks):
    # Ignore IDs and empty layout paragraphs, never words, numbers or punctuation.
    text='\n'.join(b['text'].strip() for b in blocks if b['text'].strip())
    return sha256(text.encode()).hexdigest()


def bind_guidance(snapshot, blocks, context, version_id):
    if snapshot is None:return []
    if snapshot.get('scope')!='exact_document_only':
        raise ValueError('Case guidance must have exact_document_only scope')
    if not snapshot.get('confirmation',{}).get('answer'):
        raise ValueError('Case guidance needs recorded user confirmation')
    digest=text_digest(blocks);bound=[]
    release=sha256(json.dumps(snapshot,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    for entry in snapshot.get('entries',[]):
        if entry.get('input_text_sha256')!=digest:continue
        if entry.get('role')!=context.get('our_party_code'):continue
        if stage_code(entry.get('stage'))!=stage_code(context.get('stage')):continue
        if not entry.get('source_sha256') or not entry.get('source_target'):continue
        bound.append({**entry,'basis_kind':'case_specific_guidance',
                      'document_version_id':version_id,'guidance_version':snapshot['version'],
                      'guidance_sha256':release,'scope':'exact_document_only',
                      'approved_for_global_policy':False})
    return bound
