"""Normalize user-selected roles; display labels are not domain identifiers."""
ROLE_LABELS={'甲方':'party_a','甲方 · 采购方':'party_a','乙方':'party_b','乙方 · 服务提供方':'party_b','中立审查':'neutral','不确定':'unknown','unknown':'unknown'}
CODES={'party_a':'甲方','party_b':'乙方','neutral':'中立审查','unknown':'不确定'}


def normalize_review_context(payload):
    value={k:v for k,v in payload.items() if k not in ('contract_type','contract_type_declared','business_scope','business_scope_code','business_scope_state')};label=value.get('our_party_label',value.get('our_party',''))
    mapped=ROLE_LABELS.get(label,'unknown');explicit=value.get('our_party_code')
    conflict=explicit in CODES and mapped!='unknown' and explicit!=mapped
    code='unknown' if conflict else explicit if explicit in CODES else mapped
    value.update(our_party_code=code,our_party_label=label,our_party=CODES[code],role_conflict=conflict,
                 role_source='user_selection' if explicit in CODES else 'legacy_mapping' if mapped!='unknown' else 'unknown')
    return value
