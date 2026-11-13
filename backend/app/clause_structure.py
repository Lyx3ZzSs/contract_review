"""Conservative structural index. Source paragraphs remain the review evidence unit."""
import re

HEADING = re.compile(r'^(第[一二三四五六七八九十百零〇\d]+[章条款])(?:[、.．：:\s]|$)')
NUMBER = re.compile(r'^(\d+(?:\.\d+)+)(?:[、.．：:\s]|$)')


def build_clauses(document_version_id: str, blocks: list[dict]) -> list[dict]:
    clauses, stack = [], []
    for block in blocks:
        value = block['text'].strip()
        match = HEADING.match(value) or NUMBER.match(value)
        if match:
            number = match[1]
            level = 0 if number.endswith('章') else 1 if number.endswith('条') else 2 if number.endswith('款') else number.count('.')+1
            while stack and stack[-1][0] >= level:
                stack.pop()
            item = dict(id=f'{document_version_id}:c{len(clauses)+1}', document_version_id=document_version_id,
                        parent_id=stack[-1][1]['id'] if stack else None, title=value, number=number,
                        block_ids=[block['id']], kind='clause', extraction_method='numbered_heading')
            clauses.append(item)
            stack.append((level,item))
        elif stack:
            stack[-1][1]['block_ids'].append(block['id'])
        else:
            clauses.append(dict(id=f'{document_version_id}:c{len(clauses)+1}', document_version_id=document_version_id,
                                parent_id=None,title='',number=None,block_ids=[block['id']],kind='paragraph',extraction_method='unstructured'))
    return clauses
