"""Distribute source-indexed responsibility checks without dropping candidates."""

import re

from .review_evidence import normalized_text, payment_directions


CLAUSE_START = r'(?:^|[。；;])(?:(?:\d+(?:\.\d+)+)|\([一二三四五六七八九十\d]+\))?'
SUPPLIER_STATEMENT = re.compile(
    CLAUSE_START + r'(甲方|乙方)(?:为|系|是)(?:(?:本合同|本项目)的?)?(?:供应方|供应商|服务提供方)(?=[,、。;:]|$)'
)
CONTRACT_DELEGATION = re.compile(CLAUSE_START + r'本合同(?:为|约定由)(甲方|乙方)委托(甲方|乙方)')
SERVICE_PROVIDER = re.compile(
    CLAUSE_START + r'(?:(?:服务目标与考核|服务内容|服务义务):)?'
    r'(甲方|乙方)(?:应|须|负责)?提供本(?:条|合同)(?:所述|约定)(?:各项)?服务'
)


def documented_supplier(paragraphs):
    declarations = {}
    delegates = {}
    providers = {}
    for ref, row in paragraphs.items():
        if row[1]:
            continue
        text = normalized_text(row[-1])
        for party in SUPPLIER_STATEMENT.findall(text):
            declarations.setdefault(party, []).append(ref)
        for client, delegate in CONTRACT_DELEGATION.findall(text):
            if client != delegate:
                delegates.setdefault(delegate, []).append(ref)
        for party in SERVICE_PROVIDER.findall(text):
            providers.setdefault(party, []).append(ref)
    named = declarations.keys() | delegates.keys() | providers.keys()
    if len(named) != 1:
        return None
    party = next(iter(named))
    if party in declarations:
        return party, declarations[party]
    if party in delegates and party in providers:
        return party, list(dict.fromkeys([*delegates[party], *providers[party]]))
    return None


def target_batches(refs, paragraphs, *, target_limit=3):
    batches = []
    group = []
    size = 0
    for ref in refs:
        cost = max(240, len(paragraphs[ref][-1]))
        if group and (len(group) == target_limit or size + cost > 720):
            batches.append(group)
            group, size = [], 0
        group.append(ref)
        size += cost
    if group:
        batches.append(group)
    return batches


def responsibility_batches(refs, paragraphs, role):
    if len(refs) < 6:
        return target_batches(refs, paragraphs)

    def first_score(ref):
        text = paragraphs[ref][-1]
        explicit = any(payer == role for payer, _ in payment_directions(text))
        return not explicit, len(text)

    first = min(refs, key=first_score)
    remaining = [ref for ref in refs if ref != first]
    return [[first], *target_batches(remaining, paragraphs, target_limit=2)]
