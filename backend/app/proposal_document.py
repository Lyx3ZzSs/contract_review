"""Bind saved review evidence to the actual target range, not document-wide counts."""
from collections import Counter
from io import BytesIO
from zipfile import ZipFile
from defusedxml import ElementTree as ET
from fastapi import HTTPException
from .parser import W, text, PROPERTY_TAGS


def document(data):
    with ZipFile(BytesIO(data)) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
        comments = ET.fromstring(archive.read('word/comments.xml')) if 'word/comments.xml' in archive.namelist() else []
    return root, {c.get(W+'id'): '\n'.join(text(p) for p in c.iter(W+'p')) for c in comments}


def paragraph_evidence(paragraph):
    """Offsets are Unicode codepoints in the same proposed view as parser.text."""
    offset = 0
    starts, ends, names, comment_starts, comment_ends, revisions = {}, {}, {}, {}, {}, []

    def walk(node):
        nonlocal offset
        tag, ident = node.tag, node.get(W+'id')
        if tag in PROPERTY_TAGS:
            return
        if tag == W+'bookmarkStart':
            starts[ident] = offset
            names[node.get(W+'name')] = ident
        elif tag == W+'bookmarkEnd':
            ends[ident] = offset
        elif tag == W+'commentRangeStart':
            comment_starts[ident] = offset
        elif tag == W+'commentRangeEnd':
            comment_ends[ident] = offset
        elif tag in (W+'del', W+'moveFrom'):
            removed = ''.join(n.text or '' for n in node.iter() if n.tag in (W+'delText', W+'t'))
            revisions.append(('del', ident, removed, offset, offset, node.get(W+'author','')))
            return
        elif tag == W+'t':
            offset += len(node.text or '')
        elif tag in (W+'tab', W+'br', W+'cr'):
            offset += 1
        start = offset
        for child in node:
            walk(child)
        if tag == W+'ins':
            revisions.append(('ins', ident, text(node), start, offset, node.get(W+'author','')))

    walk(paragraph)
    bookmarks = {name: (starts[ident], ends[ident]) for name, ident in names.items() if ident in ends}
    comments = {ident: (start, comment_ends[ident]) for ident, start in comment_starts.items() if ident in comment_ends}
    return bookmarks, comments, revisions


def revision_counts(root):
    return Counter(r[:3] for p in root.iter(W+'p') for r in paragraph_evidence(p)[2])


def revision_content(root):
    """Saving can renumber or split revision runs without changing their meaning."""
    result = []
    for index, paragraph in enumerate(root.iter(W+'p')):
        merged = []
        for kind, _, value, start, end, author in paragraph_evidence(paragraph)[2]:
            if not value:
                continue
            if merged and merged[-1][0] == kind and merged[-1][4] == author and merged[-1][3] == start:
                old = merged.pop()
                merged.append((kind, old[1]+value, old[2], end, author))
            else:
                merged.append((kind, value, start, end, author))
        result.extend((index, *r) for r in merged)
    return result


def comment_signatures(data):
    # IDs and timestamps may be rewritten by Word. Content and attribution may not.
    with ZipFile(BytesIO(data)) as archive:
        if 'word/comments.xml' not in archive.namelist():
            return Counter()
        comments = ET.fromstring(archive.read('word/comments.xml'))
    return Counter((c.get(W+'author',''), c.get(W+'initials',''),
                    '\n'.join(text(p) for p in c.iter(W+'p'))) for c in comments)


def table_layout(root):
    """Compare logical rows, columns and merges independently of Word formatting."""
    def value(node, parent, name, default, implicit=None):
        prop = node.find(W+parent+'/'+W+name)
        return default if prop is None else prop.get(W+'val', implicit or default)

    tables = []
    for table in root.iter(W+'tbl'):
        rows = []
        for row in table.findall(W+'tr'):
            cells = [(value(c,'tcPr','gridSpan','1'), value(c,'tcPr','vMerge','','continue'),
                      value(c,'tcPr','hMerge','','continue')) for c in row.findall(W+'tc')]
            rows.append((value(row,'trPr','gridBefore','0'), value(row,'trPr','gridAfter','0'), cells))
        tables.append((len(table.findall(W+'tblGrid/'+W+'gridCol')), rows))
    return tables


def verify_document(before, after, op):
    oldroot, _ = document(before)
    root, comments = document(after)
    target = op['target']
    if target.get('table_location') and table_layout(oldroot) != table_layout(root):
        raise HTTPException(409, '保存后的表格行列或合并结构发生变化，请核对')
    start = target['start']
    appended = op.get('append_paragraphs') or []
    expected = target['quote'] if op['mode'] == 'COMMENT' or appended else op['after_text']
    end = start + len(expected)
    paragraphs = [p for p in root.iter(W+'p') if text(p).strip()]
    index = next((i for i, b in enumerate(target['blocks']) if b['id'] == target['blockId']), -1)
    if index < 0 or index >= len(paragraphs):
        raise HTTPException(409, '保存后的目标段落无法确认')
    marked = [(i, paragraph_evidence(p)) for i, p in enumerate(paragraphs)
              if any(n.get(W+'name') == op['bookmark'] for n in p.iter(W+'bookmarkStart'))]
    if len(marked) != 1 or marked[0][0] != index or marked[0][1][0].get(op['bookmark']) != (start, end):
        raise HTTPException(409, '本次文档标记未保存到正确的修改范围，请核对正文')
    _, ranges, revisions = marked[0][1]
    proof = {'bookmark': op['bookmark']}
    if op['mode'] != 'MODIFY':
        expected_comment = op['comment'].replace('\r\n', '\n')
        matches = [ident for ident, value in comments.items()
                   if value == expected_comment and ranges.get(ident) == (start, end)]
        continuation = op.get('continuation') or {}
        if len(matches) != 1:
            raise HTTPException(409, '未验证到本次目标范围内唯一的完整批注，请核对保存结果')
        previous_comments, saved_comments = comment_signatures(before), comment_signatures(after)
        if continuation.get('mode') == 'COMMENT':
            if previous_comments != saved_comments:
                raise HTTPException(409, '补做修订时原有批注内容或作者发生变化，请核对')
        else:
            # OOXML comment IDs are local to each saved package. ONLYOFFICE
            # can give a new comment an old ID while renumbering the old one.
            # Prove addition by content/attribution counts, not ID novelty;
            # the unique target-range match above still binds the proof.
            added = list((saved_comments - previous_comments).elements())
            if previous_comments - saved_comments or len(added) != 1 or added[0][2] != expected_comment:
                raise HTTPException(409, '新增批注未完整保存，或原有批注发生变化，请核对')
        proof['comment_id'] = matches[0]
    if appended:
        # The bookmark and any prior comment stay on the original clause. Prove
        # each added paragraph is its immediate sibling with tracked text.
        anchor = paragraphs[index]
        parent = next((n for n in root.iter() if anchor in list(n)), None)
        if parent is None:
            raise HTTPException(409, '新增段落位置未确认')
        siblings = list(parent)
        pos = siblings.index(anchor) + 1
        inserted = siblings[pos:pos + len(appended)]
        if len(inserted) != len(appended):
            raise HTTPException(409, '新增段落未完整保存')
        # A text-only insertion in an untracked new paragraph leaves a blank line
        # when rejected. The paragraph breaks themselves must be tracked too.
        mark_path = './' + W+'pPr/' + W+'rPr/' + W+'ins'
        if any(p.find(mark_path) is None for p in [anchor, *inserted[:-1]]):
            raise HTTPException(409, '新增段落的换段修订未完整保存')
        for paragraph, value in zip(inserted, appended):
            revisions = paragraph_evidence(paragraph)[2]
            if (paragraph.tag != W+'p' or text(paragraph) != value
                    or ''.join(r[2] for r in revisions if r[0] == 'ins') != value
                    or any(r[0] == 'del' for r in revisions)):
                raise HTTPException(409, '未验证到原条款后完整的新增段落修订')
        for paragraph in inserted:
            parent.remove(paragraph)
        if revision_content(root) != revision_content(oldroot):
            raise HTTPException(409, '新增段落时原有正文修订发生变化')
        return proof
    old_revisions = revision_counts(oldroot)
    if op['mode'] != 'COMMENT':
        new = []
        for r in revisions:
            key = r[:3]
            if old_revisions[key]:
                old_revisions[key] -= 1
            else:
                new.append(r)
        insertions = [r for r in new if r[0] == 'ins' and start <= r[3] <= r[4] <= end]
        # Word may serialize the deleted runs before OR after the insertion.
        deletions = [r for r in new if r[0] == 'del' and r[3] in (start, end)]
        if ''.join(r[2] for r in insertions) != op['after_text'] or ''.join(r[2] for r in deletions) != target['quote']:
            raise HTTPException(409, '目标范围的新增修订与本次替换不一致，请核对正文')
    elif revision_content(root) != revision_content(oldroot):
        raise HTTPException(409, '添加批注时原有修订发生变化，请核对正文')
    return proof
