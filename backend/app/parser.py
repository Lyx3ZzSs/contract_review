from io import BytesIO
from zipfile import ZipFile, BadZipFile
from defusedxml import ElementTree as ET
from .clause_structure import build_clauses, STRUCTURE_VERSION, validate_tree
from .docx_structure import WordStructure

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
MAX_FILE = 20 * 1024 * 1024
PARSER_VERSION = 'docx-paragraphs-v3'
# Properties can contain w:tab too: those nodes define tab stops, not characters.
# Both text extraction and saved-range verification must use this boundary.
PROPERTY_TAGS = frozenset(W + name for name in (
    'pPr', 'rPr', 'sdtPr', 'sdtEndPr', 'tblPr', 'tblPrEx', 'trPr', 'tcPr', 'sectPr'))


def text(node):
    # Current proposed view: exclude removed text, include insertions.
    if node.tag in PROPERTY_TAGS or node.tag in (W + 'del', W + 'moveFrom'):
        return ''
    if node.tag == W + 't':
        return node.text or ''
    if node.tag == W + 'tab':
        return '\t'
    if node.tag in (W + 'br', W + 'cr'):
        return '\n'
    return ''.join(text(child) for child in node)


def parse_docx(data: bytes):
    if len(data) > MAX_FILE:
        raise ValueError('DOCX超过20MB')
    try:
        with ZipFile(BytesIO(data)) as z:
            entries = z.infolist()
            if len(entries) > 5000 or sum(e.file_size for e in entries) > 100 * 1024 * 1024:
                raise ValueError('DOCX解压内容超过限制')
            if len({e.filename for e in entries}) != len(entries):
                raise ValueError('DOCX包含重复条目')
            root = ET.fromstring(z.read('word/document.xml'))
            styles = ET.fromstring(z.read('word/styles.xml')) if 'word/styles.xml' in z.namelist() else None
            numbering = ET.fromstring(z.read('word/numbering.xml')) if 'word/numbering.xml' in z.namelist() else None
    except (BadZipFile, KeyError) as exc:
        raise ValueError('文件不是有效的DOCX') from exc
    paragraphs=list(root.iter(W+'p'))
    paragraph_ids={id(p):f'p{i}' for i,p in enumerate(paragraphs,1)}
    blocks = [{'id': paragraph_ids[id(p)], 'text': text(p)} for p in paragraphs if text(p).strip()]
    image_block_ids=[paragraph_ids[id(p)] for p in paragraphs if any(n.tag in (W+'drawing',W+'pict') for n in p.iter())]
    locations={}
    for t,table in enumerate(root.iter(W+'tbl'),1):
        for r,row in enumerate(table.findall(W+'tr'),1):
            for c,cell in enumerate(row.findall(W+'tc'),1):
                for p in cell.iter(W+'p'):
                    locations[paragraph_ids[id(p)]]={'table':t,'row':r,'cell':c}
    for block in blocks:
        if block['id'] in locations:block['table_location']=locations[block['id']]
    structure = WordStructure(styles, numbering)
    by_id = {b['id']:b for b in blocks}
    for p in paragraphs:
        # Empty list items still advance Word's counters, without becoming text blocks.
        metadata = structure.paragraph(p)
        if paragraph_ids[id(p)] in by_id:
            by_id[paragraph_ids[id(p)]].update(metadata)
    if not blocks:
        raise ValueError('未提取到正文文字，扫描件需要OCR')
    return {'parser_version': PARSER_VERSION, 'view': 'proposed', 'blocks': blocks,
            'block_locations':locations,'image_block_ids':image_block_ids,
            'limitations': ['仅主文档段落及表格单元格文字；未解析图片、页眉页脚、外部附件。',
                            '段落ID仅在当前文档版本有效；不对应编辑器内部节点。',
                            '编号与标题作为结构元数据保存；不确定的条款归属需人工核对。',
                            '保留上传文件中的修订和批注，审查文本不含批注。'],
            'tracked_changes_present': any(n.tag in (W+'ins', W+'del', W+'moveFrom', W+'moveTo') for n in root.iter())}


def namespace_parsed(parsed, version_id):
    for block in parsed['blocks']:block['id']=version_id+':'+block['id']
    parsed['block_locations']={version_id+':'+k:v for k,v in parsed.get('block_locations',{}).items()}
    parsed['image_block_ids']=[version_id+':'+i for i in parsed.get('image_block_ids',[])]
    parsed['clauses']=build_clauses(version_id,parsed['blocks'])
    parsed['structure_version']=STRUCTURE_VERSION
    parsed['structure_summary']=validate_tree(parsed['clauses'], parsed['blocks'])
    return parsed
