"""Version-local reading units; never infer legal completion from structure."""
import re
STRUCTURE_VERSION = 'clause-tree-v2'
HEADING = re.compile(r'^(第[一二三四五六七八九十百零〇\d]+[章条款])')
NUMBER = re.compile(r'^(\d+(?:\.\d+)+)(?![\d.]|万元|元|年|月|日|%|％)|^(\d+)[.．、](?=\s|[^\d])|^([一二三四五六七八九十百]+)[、．]|^([（(][一二三四五六七八九十\d]+[）)])')

def build_legacy_clauses(document_version_id: str, blocks: list[dict]) -> list[dict]:
    clauses, stack = [], []
    for index,block in enumerate(blocks):
        value=block['text'].strip();match=HEADING.match(value) or NUMBER.match(value)
        if block.get('table_location') or block.get('automatic_numbering'):
            clauses.append(dict(id=f'{document_version_id}:c{len(clauses)+1}',document_version_id=document_version_id,
                parent_id=stack[-1][1]['id'] if stack else None,title=value,number=None,block_ids=[block['id']],
                kind='table_cell' if block.get('table_location') else 'paragraph',source_order=index,
                table_location=block.get('table_location'),extraction_method='unresolved_numbering' if block.get('automatic_numbering') else 'table_paragraph',
                parse_gaps=['自动编号未还原'] if block.get('automatic_numbering') else []))
            # Never join following body text across a table or an unresolved list item.
            stack=[]
        elif match:
            number=next(g for g in match.groups() if g)
            level=0 if number.endswith('章') else 1 if number.endswith('条') else 3 if number.startswith(('（','(')) else number.count('.')+1
            while stack and stack[-1][0]>=level:stack.pop()
            item=dict(id=f'{document_version_id}:c{len(clauses)+1}',document_version_id=document_version_id,parent_id=stack[-1][1]['id'] if stack else None,title=value,number=number,block_ids=[block['id']],kind='clause',extraction_method='numbered_heading',source_order=index)
            clauses.append(item);stack.append((level,item))
        elif stack:stack[-1][1]['block_ids'].append(block['id'])
        else:clauses.append(dict(id=f'{document_version_id}:c{len(clauses)+1}',document_version_id=document_version_id,parent_id=None,title=value,number=None,block_ids=[block['id']],kind='paragraph',extraction_method='unstructured',source_order=index))
    return clauses


ATTACHMENT = re.compile(r'^(附件|附录)\s*([一二三四五六七八九十百\dA-Z]+)(?:\s|[：:、.．]|$)')
SIGNATURE = re.compile(r'^(?:签署页|签字盖章页|签署部分|签章页)(?:\s|[：:]|$)')


def article_number(label):
    label=label.removeprefix('第').removesuffix('条').removesuffix('款')
    if label.isdigit(): return str(int(label))
    digits={c:i for i,c in enumerate('零一二三四五六七八九')}; digits.update({'〇':0,'两':2})
    total=0; digit=0
    for c in label:
        if c in digits: digit=digits[c]
        elif c in '十百千': total+=(digit or 1)*{'十':10,'百':100,'千':1000}[c];digit=0
        else: return None
    return str(total+digit)


def candidate(block):
    text = block['text'].strip()
    if ATTACHMENT.match(text) and len(text) <= 100:
        m = ATTACHMENT.match(text)
        return {'kind':'attachment','number':m[0].strip(' ：:、.．'), 'family':'attachment','level':-1,'method':'attachment_heading'}
    if SIGNATURE.match(text) and len(text) <= 80:
        return {'kind':'signature','number':None,'family':'signature','level':-1,'method':'signature_heading'}
    num = block.get('numbering') or {}
    if block.get('automatic_numbering'):
        if not num.get('resolved'): return {'kind':'paragraph','number':None,'family':'unknown','level':0,'method':'unresolved_numbering'}
        return {'kind':'section' if num['label'].endswith('章') else 'clause' if num.get('ordered') else 'item', 'number':num['label'],
                'family':'auto:'+num['num_id'], 'level':num['level'], 'method':'word_numbering'}
    match = HEADING.match(text)
    if match and re.match(r'^(?:所述|约定|规定|项下|的)',text[match.end():].lstrip()):
        match=None
    if match:
        number = match[0]
        return {'kind':'section' if number.endswith('章') else 'clause','number':number,
                'family':'chapter' if number.endswith('章') else 'subarticle' if number.endswith('款') else 'article','level':0 if number.endswith('章') else 20 if number.endswith('款') else 10,'method':'numbered_heading'}
    match = NUMBER.match(text)
    # Dates, amounts and percentages can look like dotted headings.
    if match and not re.match(r'^\d{4}[.．]\d{1,2}[.．]\d{1,2}', text):
        number = next(g for g in match.groups() if g)
        family = 'paren' if number.startswith(('（','(')) else 'decimal' if number[0].isdigit() else 'chinese_list'
        level = 40 if family == 'paren' else 20 if family == 'chinese_list' else 10*len(number.rstrip('.．、').split('.'))
        return {'kind':'clause','number':number,'family':family,'level':level,'method':'numbered_heading'}
    if block.get('heading_level'):
        return {'kind':'section','number':None,'family':'style','level':block['heading_level'],'method':'word_heading'}
    return None


def build_clauses(document_version_id: str, blocks: list[dict]) -> list[dict]:
    """A document-rooted forest. Direct spans have one owner; ancestors don't duplicate them."""
    nodes = []; stack = []; scope = None; tables = {}

    def append_block(node, block):
        node['block_ids'].append(block['id'])
        node['source_spans'].append({'block_id':block['id'],'start':0,'end':len(block['text'])})

    def create(block, kind, parent, number=None, method='unstructured', gaps=None):
        raw = block['text'].strip()
        gaps=list(gaps or [])
        if any(HEADING.match(line.strip()) for line in raw.splitlines()[1:]):
            gaps.append('单段包含条款边界标记，保留原段待核对')
        title = raw
        # Only remove a number actually present in the source; native numbers are metadata.
        if number and raw.startswith(number) and method != 'word_numbering':
            title = raw[len(number):].lstrip(' .．、：:') or raw
        node = dict(id=f'{document_version_id}:ct2:{len(nodes)+1}',document_version_id=document_version_id,
                    parent_id=parent['id'] if parent else None,kind=kind,number=number,title=title[:160],
                    block_ids=[],source_spans=[],source_order=order,extraction_method=method,structure_source=method,
                    resolution_status='unresolved' if gaps else 'resolved',parse_gaps=gaps or [])
        if block.get('table_location'): node['table_location']=block['table_location']
        append_block(node,block); nodes.append(node); return node

    for order, block in enumerate(blocks):
        if block.get('table_location'):
            table_id = block['table_location']['table']
            if table_id not in tables:
                node=create(block,'table',stack[-1][1] if stack else scope,method='word_table')
                node['title']=f'表格 {table_id}'; tables[table_id]=node
            else: append_block(tables[table_id],block)
            continue
        c = candidate(block)
        if not c:
            if stack: append_block(stack[-1][1],block)
            elif scope: append_block(scope,block)
            else: create(block,'paragraph',None)
            continue
        if c['family'] in ('attachment','signature'):
            scope=create(block,c['kind'],None,c['number'],c['method']); stack=[]; continue
        if c['family']=='unknown':
            create(block,'paragraph',stack[-1][1] if stack else scope,method=c['method'],gaps=['自动编号未还原'])
            stack=[]; continue
        gaps=[]
        family=c['family']; level=c['level']
        # Prefer explicit prefix ancestry, e.g. 2.1 is a child of 2, never of 1.9.
        if family=='decimal' and '.' in c['number'].rstrip('.．、'):
            prefix=c['number'].rstrip('.．、').rsplit('.',1)[0]
            match=next((i for i in range(len(stack)-1,-1,-1) if (stack[i][1]['number'] or '').rstrip('.．、')==prefix),None)
            if match is not None: stack=stack[:match+1]
            else:
                while stack and (stack[-1][0]['family'] in ('decimal','paren','chinese_list') or stack[-1][0]['family'].startswith('auto:')): stack.pop()
                # Do not attach 2.1 to an unrelated "第一条" just because it is nearby.
                if stack and stack[-1][0]['family']=='article' and article_number(stack[-1][1]['number'])!=prefix:
                    stack.pop();gaps.append('条款编号与上级编号不匹配')
                if not stack or stack[-1][0]['family']!='article':
                    gaps.append('未找到编号对应的上级条款')
        elif family.startswith('auto:') or family=='style':
            # Levels are relative to their own list/style hierarchy, not global numbers.
            same=[i for i,(a,_) in enumerate(stack) if a['family']==family]
            if same:
                base=same[0]
                while len(stack)>base and not (stack[-1][0]['family']==family and stack[-1][0]['level']<level): stack.pop()
                if family.startswith('auto:') and level>0 and (len(stack)==base or stack[-1][0]['level']!=level-1):
                    gaps.append('自动编号跳过上级层级，需核对归属')
            else:
                while stack and stack[-1][0]['family'].startswith('auto:'): stack.pop()
                if family.startswith('auto:') and level>0: gaps.append('编号从非首层开始，需核对上级归属')
        else:
            while stack:
                previous=stack[-1][0]
                if previous['family'].startswith('auto:') or previous['family']=='style' and family in ('chapter','article'):
                    stack.pop(); continue
                if previous['level']>=level: stack.pop()
                else: break
        parent=stack[-1][1] if stack else scope
        node=create(block,c['kind'],parent,c['number'],c['method'],gaps)
        stack.append((c,node))
    validate_tree(nodes,blocks)
    return nodes


def block_citations(clauses):
    """Resolve each block to its nearest explicit article and nested list items."""
    paths = {}
    citations = {}
    for clause in clauses:
        label = (clause.get('number') or '').strip()
        parent = paths.get(clause.get('parent_id'), '')
        if re.fullmatch(r'\d+(?:\.\d+)*', label):
            path = f'第{label}条'
        elif label.startswith('第') and label.endswith('条'):
            path = label
        elif parent and re.fullmatch(r'[（(][一二三四五六七八九十百\d]+[）)]', label):
            path = f'{parent}第{label}项'
        elif clause.get('kind') in ('attachment','signature') or label:
            path = ''
        else:
            path = parent
        paths[clause['id']] = path
        if path:
            citations.update(dict.fromkeys(clause['block_ids'],path))
    return citations


def validate_tree(nodes, blocks):
    by_id={n['id']:n for n in nodes}; source={b['id']:b for b in blocks}; owners={k:[] for k in source}
    if len(by_id)!=len(nodes): raise ValueError('条款节点ID重复')
    for node in nodes:
        seen={node['id']}; parent=node.get('parent_id')
        while parent:
            if parent not in by_id or parent in seen: raise ValueError('条款父子关系无效')
            seen.add(parent)
            if by_id[parent]['source_order']>node['source_order']: raise ValueError('条款顺序无效')
            parent=by_id[parent].get('parent_id')
        for span in node['source_spans']:
            bid=span['block_id']; start=span['start']; end=span['end']
            if bid not in source or not 0<=start<end<=len(source[bid]['text']): raise ValueError('条款来源范围无效')
            owners[bid].append((start,end))
        if node['block_ids']!=list(dict.fromkeys(s['block_id'] for s in node['source_spans'])): raise ValueError('条款来源索引不一致')
    for bid, spans in owners.items():
        cursor=0
        for start,end in sorted(spans):
            if start!=cursor: raise ValueError('条款正文遗漏或重复归属')
            cursor=end
        if cursor!=len(source[bid]['text']): raise ValueError('条款正文未完全覆盖')
    return {'node_count':len(nodes),'clause_count':sum(n['kind'] in ('clause','item') for n in nodes),
            'unresolved_count':sum(n['resolution_status']=='unresolved' for n in nodes),'covered_blocks':len(source)}


def version_structure(parsed, version_id):
    """Read immutable stored structure; old snapshots retain their legacy interpretation."""
    if 'clauses' in parsed: return parsed
    return {**parsed,'clauses':build_legacy_clauses(version_id,parsed['blocks']), 'structure_version':'clause-tree-v1'}
