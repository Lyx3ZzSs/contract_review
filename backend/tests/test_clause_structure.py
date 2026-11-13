def test_clause_mapping_preserves_each_paragraph_once_and_groups_numbered_clause():
    from app import parser
    assert hasattr(parser, 'build_clauses'), 'clause structure not available'
    blocks=[{'id':f'p{i}', 'text':s} for i,s in enumerate(['合同','第一条 服务范围','提供数据服务。','1.1 接口要求','采用HTTPS。','第二条 费用','总价100元。'])]
    original=[dict(b) for b in blocks]
    clauses=parser.build_clauses('v1',blocks)
    ids=[i for c in clauses for i in c['block_ids']]
    assert sorted(ids)==sorted(b['id'] for b in blocks)
    assert len(set(ids))==len(ids)
    assert blocks==original
    first=next(c for c in clauses if c['number']=='第一条')
    child=next(c for c in clauses if c['number']=='1.1')
    assert first['block_ids']==['p1','p2']
    assert child['parent_id']==first['id']


def test_unstructured_paragraphs_not_arbitrarily_grouped():
    from app import parser
    assert hasattr(parser, 'build_clauses')
    cs=parser.build_clauses('v',[{'id':'a','text':'普通段落'},{'id':'b','text':'另一普通段落'}])
    assert [x['block_ids'] for x in cs]==[['a'],['b']]


def test_parser_preserves_table_location_and_image_gap():
    from io import BytesIO
    from zipfile import ZipFile
    from app.parser import parse_docx
    data=BytesIO()
    with ZipFile(data,'w') as z:
        z.writestr('word/document.xml','''<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
        <w:p><w:r><w:t>附件技术协议</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>接口说明</w:t><w:drawing/></w:r></w:p></w:tc></w:tr></w:tbl>
        <w:p><w:r><w:drawing/></w:r></w:p></w:body></w:document>''')
    value=parse_docx(data.getvalue())
    assert value.get('image_block_ids')==['p2','p3']
    assert value['block_locations']['p2']=={'table':1,'row':1,'cell':1}
    assert len(value['blocks'])==2
