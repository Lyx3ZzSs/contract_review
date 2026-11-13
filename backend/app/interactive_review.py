"""Opt-in interactive candidate. Legacy v7 prompts and behavior are untouched."""
import json
import re
import time
from hashlib import sha256
from . import structured_review as legacy
from .attachment_review import AttachmentResults, ATTACHMENT_PROMPT, evaluate_attachment_references, index_attachment_contents
from .review_issues import build_review_issues, RESULT_SCHEMA_VERSION
from .reference_index import index_references
from .amount_review import classify as classify_amount
from .field_review import classify as classify_field
from .llm import ExtractionError

PROMPT_VERSION = 'interactive-review-candidate-v4'
FACT_PROMPT = legacy.INDEXED_FACT_PROMPT + '''
本次是完整资料包审查。blocks 每段标记 origin 与 material_version_id；主文与已收附件是不同来源。
attachments 只列 main_document 正文明确引用的附件，不从材料标题/文件名制造新引用；引用和用途 refs 必须来自正文。
calculations、missing_prices、fields 则检查所有已读取的正文和材料全文，包括技术附件中的价格、税、数量及空白字段。
资料包已含真实计价内容时不能仍以正文旧有“未提供”字样断定当前缺失；但内容不匹配或只有标题仍需保留不确定。
用户 assertions 和 links 是未核验说明/候选关联，不是文档事实，也不能用于证据。材料里嵌套提及的名称不自动成为主文附件引用。
'''
OTHER_PROMPT = legacy.OTHER_PROMPT + '\n本次范围含主文与可读附件全文。附件逐项核验由独立结果处理；不要把已收材料标题当新增附件。用户说明与关联不能当文档证据。'
VERSION_PROMPT = FACT_PROMPT + '\n---\n' + ATTACHMENT_PROMPT + '\n---\n' + OTHER_PROMPT


def prompt_hash():
    return sha256(VERSION_PROMPT.encode()).hexdigest()


def schema_hash():
    value = {'facts': legacy.ContractFacts.model_json_schema(), 'attachments': AttachmentResults.model_json_schema(),
             'other_results': legacy.OtherResults.model_json_schema(), 'result_schema_version': RESULT_SCHEMA_VERSION}
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def model_source_payload(value, sources):
    """Encode every paragraph pointer consistently before any model call.

    Stored evidence uses immutable public IDs; the model sees only its local bN
    alphabet, including nested evidence and user-proposed links. Text is untouched.
    """
    by_id = {block['id']: ref for ref, block in sources.blocks.items()}

    def paragraph(block_id):
        if block_id not in by_id:
            raise legacy.fail('payload_references_unknown_source')
        return by_id[block_id]

    def encode(item):
        if isinstance(item, list):
            return [encode(child) for child in item]
        if not isinstance(item, dict):
            return item
        return {key: paragraph(child) if key == 'block_id' else
                [paragraph(block_id) for block_id in child] if key == 'target_block_ids' else
                encode(child) for key, child in item.items()}

    return encode(value)


def reference_candidates(sources):
    """Unify an explicit annex number/title pair, never filename guesses."""
    aliases = {}
    for block in sources.blocks.values():
        for number, name in re.findall(r'(附件(?:[A-Z][A-Z0-9-]*|\d+|[一二三四五六七八九十]+))\s*[：:]?\s*《([^》]+)》', block['text']):
            aliases.setdefault(number, set()).add(name)
    aliases = {number: next(iter(names)) for number, names in aliases.items() if len(names) == 1}
    seeds, _ = index_references(sources, legacy.grounded_role, legacy.TECH, legacy.PRICE)
    # Explicit names are retrieval candidates, never proof that a file is received.
    # The legacy vocabulary omits ordinary named agreements without an annex number.
    for ref, block in sources.blocks.items():
        for clause in re.split(r'[。；;\n]', block['text']):
            if not re.search(r'详见|参见|为准|依据|按照|依照|附件|附表', clause):
                continue
            for name in re.findall(r'《([^》\n]{1,100})》', clause):
                explicit_annex = bool(re.search(r'附件\s*[:：]\s*《' + re.escape(name), clause))
                document_name = bool(re.search(r'附件|附表|协议|清单|确认单|说明|方案|报告|报价|价目|授权书|规范', name))
                if not explicit_annex and (not document_name or re.search(r'法典|法律|条例|国家标准|行业标准', name)):
                    continue
                seeds.append({'name': name, 'references': [ref], 'technical_refs': [], 'pricing_refs': []})
    merged = {}
    for seed in seeds:
        name = aliases.get(seed['name'], seed['name'])
        item = merged.setdefault(name, {'name': name, 'references': [], 'technical_refs': [], 'pricing_refs': []})
        for ref in seed['references']:
            text = sources.text([ref])
            # Number-only mentions remain model candidates: do not fabricate a
            # literal title in their evidence to satisfy the grounding validator.
            if name not in text:
                continue
            item['references'].append(ref)
            if legacy.grounded_role(name, text, legacy.TECH):
                item['technical_refs'].append(ref)
            if legacy.grounded_role(name, text, legacy.PRICE):
                item['pricing_refs'].append(ref)
    return [{k: list(dict.fromkeys(v)) if isinstance(v, list) else v for k, v in s.items()} for s in merged.values() if s['references']], aliases


def review_interactive(settings, model, blocks, context, rules, bundle, *, progress_callback=None):
    started = time.monotonic()
    all_blocks = list(blocks)
    owner = {}
    for material in bundle.get('materials', []):
        # Partial text is still reviewed; full matching is separately prohibited.
        for block in material.get('blocks', []):
            if material.get('parse_status') not in ('failed', 'unsupported'):
                all_blocks.append(block)
                owner[block['id']] = material['id']
    if len({b['id'] for b in all_blocks}) != len(all_blocks):
        raise legacy.fail('duplicate_source_block_id')
    if len(legacy.encoded({'blocks': all_blocks, 'context': context, 'bundle': bundle})) > 80000:
        raise ExtractionError('input_too_large', '资料包超过当前审查上限，未截断正文或附件。')
    sources = legacy.Sources(all_blocks)
    main_sources = legacy.Sources(blocks)
    main_refs = set(main_sources.blocks)
    public = [b | {'origin': 'material' if sources.blocks[b['id']]['id'] in owner else 'main_document',
                   'material_version_id': owner.get(sources.blocks[b['id']]['id'])} for b in sources.public]
    seeds, aliases = reference_candidates(main_sources)
    _, plans = index_references(sources, legacy.grounded_role, legacy.TECH, legacy.PRICE)
    trace = []
    deadline = time.monotonic() + 3 * settings.timeout
    material_inventory = [{k: m.get(k) for k in ('id', 'filename', 'parse_status')} for m in bundle.get('materials', [])]
    payload = {'context': context, 'blocks': public, 'materials': material_inventory,
               'document_parse_status': bundle.get('document_parse_status', 'parsed'),
               'document_contains_unreadable_images': bool(bundle.get('document_image_block_ids')),
               'assertions': bundle.get('assertions', []), 'candidate_links': bundle.get('links', [])}

    def validate_facts(facts):
        facts = facts.model_copy(deep=True)
        merged = {}
        for attachment in facts.attachments:
            if not set(attachment.references + attachment.technical_refs + attachment.pricing_refs).issubset(main_refs):
                raise legacy.fail('material_title_is_not_main_reference')
            name = aliases.get(attachment.name.strip('《》'), attachment.name.strip('《》'))
            # Only unify when every cited paragraph actually contains the title.
            if name != attachment.name and all(name in sources.text([r]) for r in attachment.references):
                attachment.name = name
            old = merged.get(attachment.name)
            if old:
                for key in ('references', 'technical_refs', 'pricing_refs'):
                    setattr(old, key, list(dict.fromkeys(getattr(old, key) + getattr(attachment, key))))
            else:
                merged[attachment.name] = attachment
        facts.attachments = list(merged.values())
        for price in facts.missing_prices:
            if price.attachment_name in aliases:
                price.attachment_name = aliases[price.attachment_name]
        return legacy.normalize_indexed_facts(facts, sources, seeds, plans)

    if progress_callback:
        progress_callback('extracting')
    _, (facts, (attachments, amounts, fields), normalization) = legacy.extract_call(
        settings, model, FACT_PROMPT, legacy.ContractFacts,
        model_source_payload(payload | {'attachment_reference_candidates': seeds, 'normalized_instalment_candidates': plans}, sources),
        validate_facts, deadline, trace)
    if progress_callback:
        progress_callback('checking')
    checks = []
    if attachments:
        content_candidates = index_attachment_contents(attachments, bundle, sources)
        def validate_attachments(result):
            if sorted(c.name for c in result.checks) != sorted(a['name'] for a in attachments):
                raise legacy.fail('attachment_coverage_mismatch')
            by_name = {c.name: c.model_dump(exclude={'name'}) for c in result.checks}
            return evaluate_attachment_references([a | {'observation': by_name[a['name']]} for a in attachments], bundle, sources)
        _, checks = legacy.extract_call(settings, model, ATTACHMENT_PROMPT, AttachmentResults,
            model_source_payload(payload | {'attachment_references': attachments, 'attachment_content_candidates': content_candidates}, sources), validate_attachments, deadline, trace)
        # The legacy index describes the original main document. A now verified
        # supplement supersedes only the missing attachment observation, never
        # unrelated amount or field observations inside that supplement.
        matched = {c['reference_name'] for c in checks if c['attachment_state'] == 'matched'}
        facts = facts.model_copy(deep=True)
        facts.missing_prices = [m for m in facts.missing_prices if not (m.kind == 'pricing_attachment' and m.attachment_name in matched)]
        _, amounts, fields = legacy.normalize_facts(facts, sources)
    other, _ = legacy.extract_call(settings, model, OTHER_PROMPT, legacy.OtherResults,
        model_source_payload(payload | {'rules': [r for r in rules if r['id'] in ('RL-01', 'RL-03', 'RL-04')],
                   'attachment_references': attachments, 'attachment_checks': checks}, sources),
        lambda result: legacy.normalize_other(result, sources), deadline, trace)
    if progress_callback:
        progress_callback('validating')
    findings = [{'rule_id': f.rule_id, 'status': f.status, 'explanation': f.explanation,
                 'evidence': sources.evidence(f.refs), 'suggested_text': None} for f in other.findings]
    amount_status, amount_note, calculations = classify_amount(amounts)
    findings.append({'rule_id': 'RL-02', 'status': amount_status, 'explanation': amount_note,
                     'evidence': legacy.unique_evidence([e.model_dump() for a in amounts for e in a.evidence]),
                     'amount_checks': [a.model_dump() for a in amounts], 'computed_calculations': calculations, 'suggested_text': None})
    field_status, field_note = classify_field(fields)
    findings.append({'rule_id': 'RL-05', 'status': field_status, 'explanation': field_note,
                     'evidence': legacy.unique_evidence([e.model_dump() for f in fields for e in f.evidence + f.requirement_evidence]),
                     'field_checks': [f.model_dump() for f in fields], 'suggested_text': None})
    attachment_rule = next(f for f in findings if f['rule_id'] == 'RL-04')
    attachment_rule['attachment_references'] = attachments
    attachment_rule['extraction_diagnostics'] = {'attempts': trace, 'normalization': normalization,
        'elapsed_seconds': round(time.monotonic() - started, 3), 'input_characters': len(legacy.encoded(payload)),
        'review_prompt_version': PROMPT_VERSION, 'prompt_sha256': prompt_hash(), 'schema_sha256': schema_hash(),
        'source_block_ids': [b['id'] for b in all_blocks], 'evidence_granularity': 'paragraph'}
    if not attachments:
        attachment_rule.update(status='no_flag_for_target_rule', explanation='本次正文未识别到附件引用，无附件核验待办。', evidence=[])
    result = build_review_issues('', sorted(findings, key=lambda f: f['rule_id']), checks)
    result['material_bundle_id'] = bundle.get('id')
    result['attachment_checks'] = checks
    return result
