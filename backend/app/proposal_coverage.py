"""Post-edit mechanism checks, separate from source/anchor validation.

These checks detect known unresolved exposures, not legal equivalence or approval.
"""
import re

PATTERNS = {
    'performed_fee_exposure': re.compile(r'当季及所有未付|退[还回][^。；]{0,20}(?:全部合同所得|所有费用|全部费用)|不承担服务期内|退[还回]全部'),
    'possible_cumulative_liability': re.compile(r'(?:另外|额外|另行)[^。；]{0,20}赔偿|(?:并|且|还应)赔偿[^。；]{0,30}(?:损失|费用)|赔偿[^。；]{0,30}全部损失|差额|补足'),
    'missing_aggregate_cap': re.compile(r'次数无上限|次数不限|不设上限'),
}

def check_coverage(event, proposals, sources, *, required_resolution=None):
    anchor=event['event_anchor']; original=anchor['quote']; text=original
    edits=[p for p in proposals if event['event_id'] in p['event_ids'] and p['state'] in ('draft','context_required')]
    for p in sorted(edits,key=lambda p:p['anchor']['start'],reverse=True):
        a=p['anchor']; left=a['start']-anchor['start'];right=a['end']-anchor['start']
        if a['block_id']!=anchor['block_id'] or not 0<=left<=right<=len(original):continue
        text=text[:left]+p['after_text']+text[right:]
    missing=[]
    for mechanism in event['mechanisms']:
        pattern=PATTERNS.get(mechanism)
        fee_retained=mechanism=='performed_fee_exposure' and any(not re.search(r'未提供|未履行|尚未履行',m.group()) for m in re.finditer(r'不予支付[^，。；]*服务费',text))
        if not edits or text==original or (pattern and pattern.search(text)) or fee_retained:
            missing.append(mechanism)
        elif mechanism=='missing_aggregate_cap' and not re.search(r'上限|累计.*不超过|累计.*为限',text):
            missing.append(mechanism)
    if required_resolution=='existing_assessment' and (not re.search(r'第?\d+\.\d+.*考核服务费',text) or re.search(r'解除|违约金|退还|赔偿',text)):
        missing.append('assessment_group_not_replaced')
    if required_resolution=='delete_fee_sentence' and text.strip():
        missing.append('extra_fee_sentence_not_deleted')
    state='incomplete' if missing else 'context_required' if any(p['state']=='context_required' for p in edits) else 'complete'
    return {'event_id':event['event_id'],'state':state,'missing_mechanisms':missing,'edited_event_text':text,
            'semantic_review':'requires_human_review'}
