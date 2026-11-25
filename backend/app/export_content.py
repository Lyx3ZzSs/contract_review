"""Deterministic export content. Documents are evidence; operations are provenance."""
from collections import Counter
from difflib import SequenceMatcher
from io import BytesIO
from zipfile import ZipFile
import json
from .review_issues import needs_review
from defusedxml import ElementTree as ET
from .export_text import clean
from .parser import W, text
from .proposal_document import paragraph_evidence
from .clause_structure import version_structure

CATEGORIES = {'transaction':'交易条款', 'procedure':'程序性条款', 'wording':'文字符号', 'legality':'合法性', 'other':'其他审查意见'}
DECISIONS = {'acknowledged':'已记录处理', 'ignored':'已忽略', 'false_positive':'标记误报', 'exception_recorded':'已记录例外', 'needs_business_confirmation':'待业务确认'}


def parsed(version):
    return version_structure(json.loads(version['parsed']), version['id'])


def location(data, block_id, start=0):
    blocks = data.get('blocks', [])
    block = next((b for b in blocks if b['id']==block_id), {})
    candidates = [c for c in data.get('clauses', []) if block_id in c.get('block_ids', [])]
    exact = [c for c in candidates if any(s['block_id']==block_id and s.get('start',0)<=start<s.get('end',10**9) for s in c.get('source_spans',[]))]
    clause = (exact or candidates or [{}])[-1]
    number = clause.get('number')
    if number:
        return str(number) if str(number).startswith(('第','附件')) else f'第 {number} 条'
    table = block.get('table_location')
    if table:return f"表 {table['table']} 第 {table['row']} 行第 {table['cell']} 列"
    quote = block.get('text','').strip()
    return (quote[:24]+'…' if len(quote)>24 else quote) or '相关原文'


def references(data):
    return {f'line{i:03}':location(data,b['id']) for i,b in enumerate(data.get('blocks',[]),1)}


def final_issues(run):
    values=run.get('issues',run.get('findings',[]))
    return [f for f in values if needs_review(f)]


def confirmations(p, labels):
    items=p.get('confirmation_items') or ([{'text':p.get('message') or '商务条件尚待确认'}] if p.get('state')=='context_required' else [])
    result={}
    for item in items:
        t=clean(item.get('text'),labels)
        if t:result.setdefault(t.rstrip('；;。 '),t)
    return list(result.values())


def word_parts(content):
    with ZipFile(BytesIO(content)) as z:
        root=ET.fromstring(z.read('word/document.xml'))
        comments=ET.fromstring(z.read('word/comments.xml')) if 'word/comments.xml' in z.namelist() else []
        return root, list(comments)


def current_paragraphs(version):
    data=parsed(version); root,_=word_parts(version['content'])
    nodes=list(root.iter(W+'p')); rows=[]
    for index,node in enumerate(nodes,1):
        t=text(node)
        if not t.strip():continue
        bid=f"{version['id']}:p{index}"
        # Imported fixtures and older persisted versions may use local IDs.
        block=next((b for b in data['blocks'] if b['id'].split(':')[-1]==f'p{index}'),{})
        bid=block.get('id',bid)
        bookmarks,_,_=paragraph_evidence(node)
        numbering=block.get('numbering') or {}
        label=numbering.get('label','') if numbering.get('resolved') else ''
        rows.append({'text':t,'label':location(data,bid),'block_id':bid,'bookmarks':bookmarks,'number':label,'table':block.get('table_location')})
    return rows


def comment_rows(version):
    root,comments=word_parts(version['content']); data=parsed(version)
    anchors={}
    for index,node in enumerate(root.iter(W+'p'),1):
        bookmarks,ranges,_=paragraph_evidence(node)
        b=next((b for b in data['blocks'] if b['id'].split(':')[-1]==f'p{index}'),{})
        for ident,(start,end) in ranges.items():anchors[ident]=(location(data,b.get('id',''),start),text(node)[start:end],[name for name,span in bookmarks.items() if span==(start,end)])
    return [{'text':'\n'.join(text(p) for p in c.iter(W+'p')), 'author':c.get(W+'author',''),
             'location':anchors.get(c.get(W+'id'),('批注位置待核对','',[]))[0], 'quote':anchors.get(c.get(W+'id'),('','',[]))[1],
             'bookmarks':anchors.get(c.get(W+'id'),('','',[]))[2]} for c in comments]


def changes(base, current, operations, run):
    before,after=current_paragraphs(base),current_paragraphs(current)
    keys=lambda rows:[(r['text'],r['number'],json.dumps(r['table'],sort_keys=True)) for r in rows]
    active=[o for o in operations if o.get('state')=='applied' and o.get('mode') in ('MODIFY','ALL')]
    proposals={p.get('proposal_id',p.get('id')):p for p in run.get('revision_proposals',[])}
    result=[]
    for tag,a,b,c,d in SequenceMatcher(None,keys(before),keys(after),autojunk=False).get_opcodes():
        if tag=='equal':continue
        left,right=before[a:b],after[c:d]
        old='\n'.join(r['text'] for r in left);new='\n'.join(r['text'] for r in right)
        linked=[]; mixed=False
        for op in active:
            marked=[r for r in right if op.get('bookmark') in r['bookmarks']]
            if not marked:continue
            p=proposals.get(op['proposal_id']) if op.get('run_id')==run.get('id') else None
            if p:
                linked.append(p)
                for r in marked:
                    start,end=r['bookmarks'][op['bookmark']]
                    if r['text'][start:end]!=op.get('after_text',''):mixed=True
                # A changed paragraph includes edits outside the managed range.
                if len(right)!=1 or right[0]['text'] not in op.get('expected_blocks',[]):mixed=True
        linked=list({p.get('proposal_id',p.get('id')):p for p in linked}.values())
        result.append({'before':old,'after':new,'location':(right or left)[0]['label'],
                       'source':('采用审查建议并有后续修改' if mixed else '采用审查建议') if linked else '文档修改 来源未关联',
                       'proposal_ids':[p.get('proposal_id',p.get('id')) for p in linked],
                       'format_note':'编号或表格位置发生变化' if old==new else ''})
    original=Counter((c['text'],c['author'],c['quote']) for c in comment_rows(base));added=[]
    for c in comment_rows(current):
        k=(c['text'],c['author'],c['quote'])
        if original[k]:original[k]-=1
        else:added.append(c)
    # Deleted comments are real review changes too; do not claim "no changes".
    removed=[]
    for c in comment_rows(base):
        k=(c['text'],c['author'],c['quote'])
        if original[k]:removed.append(c);original[k]-=1
    return {'modifications':result,'comments':added,'removed_comments':removed,'other_changes':['版式、图片或页眉页脚等内容发生变化，请在合同中核对。'] if layout_signature(base['content'])!=layout_signature(current['content']) else []}


def applied_state(p, operations, current):
    """Use saved target evidence; an old click alone is not proof of current content."""
    pid=p.get('proposal_id',p.get('id'));rows=current_paragraphs(current);comments=comment_rows(current)
    revision=comment=False;uncertain=False
    for o in operations:
        if o.get('proposal_id')!=pid or o.get('state')!='applied':continue
        for r in rows:
            if o.get('bookmark') not in r['bookmarks']:continue
            start,end=r['bookmarks'][o['bookmark']]
            if o.get('mode') in ('MODIFY','ALL'):
                if r['text'][start:end]==o.get('after_text',''):revision=True
                else:uncertain=True
        if o.get('mode') in ('COMMENT','ALL') and any(c['text']==o.get('comment') and o.get('bookmark') in c['bookmarks'] for c in comments):comment=True
    return '正文与批注均已保存' if revision and comment else '正文修订已保存' if revision else '批注已保存' if comment else '原修改已有变化 待核对' if uncertain else '当前未确认应用'


def report_content(snapshot, base, current):
    run=snapshot['run'] or {};data=parsed(base);labels=references(data);issues=final_issues(run)
    active_events={f.get('event_id') for f in issues if f.get('event_id')}
    ps={p.get('proposal_id',p.get('id')):p for p in run.get('revision_proposals',[]) if p.get('proposal_id',p.get('id')) and (not p.get('event_ids') or active_events.intersection(p['event_ids']))}
    ordered=sorted(ps.values(),key=lambda p: next((i for i,b in enumerate(data['blocks']) if b['id']==p.get('anchor',{}).get('block_id')),10**9))
    numbers={p.get('proposal_id',p.get('id')):f'修订 {i+1:02}' for i,p in enumerate(ordered)}
    decisions={d['finding_id']:d for d in snapshot['decisions']}
    risks=[]
    for i,f in enumerate(issues,1):
        content=f.get('card_content') or {}
        # Reconciled adjustments supersede the initial card prose.
        paragraphs=content.get('risk_paragraphs',[]) if f.get('review_state')!='adjusted' else []
        explanation='\n'.join(p['text'] for p in paragraphs) if paragraphs else f.get('explanation','')
        linked=[p for p in ordered if f.get('event_id') and f['event_id'] in p.get('event_ids',[])]
        d=decisions.get(f['id'],{})
        evidence=f.get('evidence') or ([f['event_anchor']] if f.get('event_anchor') else [])
        risks.append({'number':i,'title':clean(f.get('title') or (f.get('presentation') or {}).get('title') or '审查事项',labels),
            'category':'信息待办' if f.get('display_group')=='context' else '附件核验' if f.get('rule_id')=='RL-04' else CATEGORIES.get(f.get('review_category'),'其他审查意见'),
            'explanation':clean(explanation,labels),'plan':clean(content.get('modification_plan') if paragraphs else (f.get('revision_plan') or {}).get('message') or f.get('suggested_text'),labels),
            'evidence':[{'location':location(data,e['block_id'],e.get('start',0)),'quote':clean(e.get('quote'),labels)} for e in evidence],
            'decision':DECISIONS.get(d.get('action'),'待处理'),'note':clean(d.get('note'),labels),
            'proposals':[numbers[p.get('proposal_id',p.get('id'))] for p in linked]})
    revisions=[]
    for p in ordered:
        pid=p.get('proposal_id',p.get('id'));anchor=p.get('anchor') or {}
        revisions.append({'id':pid,'number':numbers[pid],'location':location(data,anchor.get('block_id'),anchor.get('start',0)),
            'before':clean(p.get('before_text'),labels),'after':clean(p.get('after_text'),labels),'operation':p.get('operation'),
            'rationale':clean(p.get('rationale'),labels),'confirmation':confirmations(p,labels),
            'state':'候选稿不可应用' if p.get('state') in ('invalid','conflict') else applied_state(p,snapshot['operations'],current),
            'risks':[r['number'] for r in risks if numbers[pid] in r['proposals']]})
    analysis=[]
    for key,value in (run.get('analysis_artifacts') or {}).items():
        if not key.startswith('transaction') or value.get('state')=='failed':continue
        for s in value.get('sections',[]):analysis.append({'title':clean(s.get('title'),labels),'text':clean(s.get('text'),labels)})
    return {'risks':risks,'revisions':revisions,'analysis':analysis}


def layout_signature(content):
    """Ignore timestamps, bookmarks and revision wrappers, retain layout evidence."""
    def normalized(node):
        if node is None:return None
        if node.tag in (W+'pPrChange',W+'rPrChange',W+'sectPrChange'):return None
        attrs=tuple(sorted((k,v) for k,v in node.attrib.items() if 'rsid' not in k))
        children=tuple(v for child in node if (v:=normalized(child)) is not None)
        return (node.tag,attrs,(node.text or '').strip(),children)
    with ZipFile(BytesIO(content)) as z:
        root=ET.fromstring(z.read('word/document.xml'))
        props=[normalized(n) for n in root.iter() if n.tag in (W+'sectPr',W+'tblPr',W+'tblGrid')]
        paragraph_props={repr(normalized(p.find(W+'pPr'))) for p in root.iter(W+'p')}
        props.append(tuple(sorted(k for k in paragraph_props if k!='None')))
        run_props={repr(normalized(r.find(W+'rPr'))) for r in root.iter(W+'r') if text(r)}
        props.append(tuple(sorted(k for k in run_props if k!='None')))
        for name in sorted(z.namelist()):
            if name.startswith(('word/media/','word/header','word/footer')):props.append((name,z.read(name)))
            elif name=='word/styles.xml':props.append(normalized(ET.fromstring(z.read(name))))
        return repr(props)
