from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile
from xml.sax.saxutils import escape
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from app.parser import parse_docx, namespace_parsed
from app.clause_structure import build_clauses, validate_tree
from app.docx_structure import format_counter
from app.main import create_app

NS='http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def paragraph(text, props=''):
    return f'<w:p><w:pPr>{props}</w:pPr><w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>'


def numbered(text, level=0, num=9):
    return paragraph(text,f'<w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="{num}"/></w:numPr>')


def archive(body, styles='', numbering=''):
    out=BytesIO()
    with ZipFile(out,'w') as z:
        z.writestr('word/document.xml',f'<w:document xmlns:w="{NS}"><w:body>{body}</w:body></w:document>')
        if styles: z.writestr('word/styles.xml',f'<w:styles xmlns:w="{NS}">{styles}</w:styles>')
        if numbering: z.writestr('word/numbering.xml',f'<w:numbering xmlns:w="{NS}">{numbering}</w:numbering>')
    return out.getvalue()


LEVELS='''<w:abstractNum w:abstractNumId="3">
<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>
<w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2"/></w:lvl>
</w:abstractNum><w:num w:numId="9"><w:abstractNumId w:val="3"/></w:num>'''


def parse(body, **kw):
    return namespace_parsed(parse_docx(archive(body, **kw)), 'v')


def test_native_numbering_resumes_resets_and_preserves_exact_source():
    body=numbered('  服务范围  ')+numbered('接口',1)+paragraph('接口说明')+numbered('费用')+numbered('结算',1)
    p=parse(body,numbering=LEVELS)
    assert [b['text'] for b in p['blocks']]==['  服务范围  ','接口','接口说明','费用','结算']
    assert [b['numbering']['label'] for b in p['blocks'] if b.get('numbering')]==['1.','1.1','2.','2.1']
    cs=p['clauses']
    assert cs[1]['parent_id']==cs[0]['id'] and cs[1]['block_ids']==['v:p2','v:p3']
    assert cs[2]['parent_id'] is None and cs[3]['parent_id']==cs[2]['id']
    assert p['structure_summary']['covered_blocks']==5


def test_style_inheritance_heading_override_and_numbering_suppression():
    styles='''<w:style w:type="paragraph" w:styleId="Base"><w:pPr><w:numPr><w:numId w:val="9"/></w:numPr></w:pPr></w:style>
    <w:style w:type="paragraph" w:styleId="Derived"><w:basedOn w:val="Base"/></w:style>
    <w:style w:type="paragraph" w:styleId="H"><w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style>'''
    p=parse(paragraph('范围','<w:pStyle w:val="Derived"/>')+paragraph('费用','<w:pStyle w:val="Derived"/>')+
            paragraph('非编号','<w:pStyle w:val="Derived"/><w:numPr><w:numId w:val="0"/></w:numPr>')+
            paragraph('标题','<w:pStyle w:val="H"/>')+
            paragraph('普通正文','<w:pStyle w:val="H"/><w:outlineLvl w:val="9"/>'),styles=styles,numbering=LEVELS)
    assert [b.get('numbering',{}).get('label') for b in p['blocks']]==['1.','2.',None,None,None]
    assert p['blocks'][3]['heading_level']==2 and 'heading_level' not in p['blocks'][4]


def test_heading_styles_build_parent_child_tree_without_text_number():
    styles=''.join(f'<w:style w:type="paragraph" w:styleId="H{n}"><w:pPr><w:outlineLvl w:val="{n-1}"/></w:pPr></w:style>' for n in [1,2])
    p=parse(paragraph('服务','<w:pStyle w:val="H1"/>')+paragraph('引导语')+paragraph('交付','<w:pStyle w:val="H2"/>')+paragraph('正文')+paragraph('费用','<w:pStyle w:val="H1"/>'),styles=styles)
    a,b,c=p['clauses']; assert b['parent_id']==a['id'] and c['parent_id'] is None
    assert a['block_ids']==['v:p1','v:p2'] and b['block_ids']==['v:p3','v:p4']


def test_start_override_and_never_restart():
    numbering=LEVELS.replace('<w:lvlText w:val="%1.%2"/>','<w:lvlText w:val="%1.%2"/><w:lvlRestart w:val="0"/>')
    numbering+='<w:num w:numId="10"><w:abstractNumId w:val="3"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="7"/></w:lvlOverride></w:num>'
    p=parse(numbered('A')+numbered('B',1)+numbered('C')+numbered('D',1)+numbered('E',num=10),numbering=numbering)
    assert [b['numbering']['label'] for b in p['blocks']]==['1.','1.1','2.','2.2','7.']


def test_linked_numbering_style_keeps_instance_override_and_cycles_fail_closed():
    styles='<w:style w:type="numbering" w:styleId="NumberStyle"><w:pPr><w:numPr><w:numId w:val="9"/></w:numPr></w:pPr></w:style>'
    numbering=LEVELS+'<w:abstractNum w:abstractNumId="4"><w:numStyleLink w:val="NumberStyle"/></w:abstractNum><w:num w:numId="10"><w:abstractNumId w:val="4"/><w:lvlOverride w:ilvl="0"><w:startOverride w:val="5"/></w:lvlOverride></w:num>'
    p=parse(numbered('编号',num=10),styles=styles,numbering=numbering)
    assert p['blocks'][0]['numbering']['label']=='5.'
    p=parse(numbered('编号',num=10),styles=styles.replace('val="9"','val="10"'),numbering=numbering)
    assert p['clauses'][0]['resolution_status']=='unresolved'


@pytest.mark.parametrize('n,fmt,label',[(10,'chineseCounting','十'),(101,'chineseCountingThousand','一百零一'),(21,'upperRoman','XXI'),(26,'lowerLetter','z'),(3,'decimalZero','03'),(101,'chineseCounting',None),(1,'ideographTraditional',None),(27,'lowerLetter',None)])
def test_native_counter_formats(n,fmt,label):
    assert format_counter(n,fmt)==label


def test_unsupported_numbering_is_visible_and_does_not_invent_label():
    p=parse(numbered('待核对'),numbering=LEVELS.replace('decimal','unknownFormat'))
    assert not p['blocks'][0]['numbering']['resolved']
    assert p['clauses'][0]['resolution_status']=='unresolved' and p['clauses'][0]['number'] is None


def test_table_and_continuation_stay_under_clause_attachment_resets_scope():
    table=f'<w:tbl><w:tr><w:tc>{paragraph("服务费")}</w:tc><w:tc>{paragraph("100元")}</w:tc></w:tr></w:tbl>'
    p=parse(paragraph('第一章 服务')+paragraph('第一条 范围')+paragraph('1.1 交付')+table+paragraph('上述费用按月结算。')+paragraph('附件一 技术要求')+paragraph('第一条 接口'))
    a,b,c,t,attachment,child=p['clauses']
    assert b['parent_id']==a['id'] and c['parent_id']==b['id'] and t['parent_id']==c['id']
    assert t['kind']=='table' and t['block_ids']==['v:p4','v:p5']
    assert c['block_ids']==['v:p3','v:p6']
    assert attachment['parent_id'] is None and child['parent_id']==attachment['id']
    assert b['id']!=child['id']


def test_unmatched_decimal_prefix_is_not_attached_to_wrong_article():
    p=parse(paragraph('第一章 服务')+paragraph('第一条 范围')+paragraph('2.1 交付'))
    assert p['clauses'][2]['parent_id']==p['clauses'][0]['id']
    assert p['clauses'][2]['resolution_status']=='unresolved'


def test_body_references_are_not_headings_and_multiple_clauses_in_one_paragraph_are_flagged():
    p=parse(paragraph('第一条 服务')+paragraph('第一条约定的费用应按期支付。')+paragraph('第二条 费用\n第三条 责任'))
    assert p['clauses'][0]['block_ids']==['v:p1','v:p2']
    assert p['clauses'][1]['resolution_status']=='unresolved'
    assert p['blocks'][2]['text']=='第二条 费用\n第三条 责任'


def test_native_list_peers_keep_enclosing_article():
    p=parse(paragraph('第一条 范围')+numbered('事项A')+numbered('细则',1)+numbered('事项B'),numbering=LEVELS)
    a,b,c,d=p['clauses']; assert b['parent_id']==a['id'] and c['parent_id']==b['id'] and d['parent_id']==a['id']


def test_skipped_numbering_level_has_explicit_gap():
    numbering=LEVELS.replace('</w:abstractNum>','<w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1.%2.%3"/></w:lvl></w:abstractNum>')
    p=parse(numbered('父项')+numbered('跳级子项',2),numbering=numbering)
    assert p['clauses'][1]['parent_id']==p['clauses'][0]['id']
    assert p['clauses'][1]['resolution_status']=='unresolved'


def test_tree_preserves_tracked_proposed_text_whitespace_and_duplicate_identity():
    revision='<w:p><w:r><w:t>应在</w:t></w:r><w:del><w:r><w:delText>十五</w:delText></w:r></w:del><w:ins><w:r><w:t>三十</w:t></w:r></w:ins><w:r><w:t>日内</w:t></w:r><w:moveFrom><w:r><w:t>旧位置</w:t></w:r></w:moveFrom><w:moveTo><w:r><w:t>付款</w:t></w:r></w:moveTo></w:p>'
    p=parse(paragraph('第一条 付款')+revision+paragraph('  重复段落😀  ')+paragraph('  重复段落😀  '))
    assert [b['text'] for b in p['blocks']][1:]==['应在三十日内付款','  重复段落😀  ','  重复段落😀  ']
    assert len({s['block_id'] for c in p['clauses'] for s in c['source_spans']})==4
    assert p['clauses'][0]['source_spans'][2]['end']==len('  重复段落😀  ')


def test_tree_validator_rejects_cycles_gaps_and_double_ownership():
    p=parse(paragraph('第一条 范围')+paragraph('1.1 事项'))
    for corrupt in ['cycle','gap','duplicate']:
        cs=deepcopy(p['clauses'])
        if corrupt=='cycle': cs[0]['parent_id']=cs[1]['id']
        elif corrupt=='gap': cs[0]['source_spans'][0]['end']-=1
        else: cs[1]['source_spans']+=cs[0]['source_spans']; cs[1]['block_ids']+=cs[0]['block_ids']
        with pytest.raises(ValueError): validate_tree(cs,p['blocks'])


def test_api_keeps_saved_structure_snapshot_and_raw_bytes(tmp_path,monkeypatch):
    path=tmp_path/'test.db'; client=TestClient(create_app(path))
    cid=client.post('/api/v1/contracts',json={'title':'结构测试','contract_type':'服务','our_party':'乙方'}).json()['id']
    data=archive(numbered('范围')+numbered('接口',1),numbering=LEVELS)
    response=client.post(f'/api/v1/contracts/{cid}/versions',files={'file':('test.docx',data)})
    assert response.status_code==201,response.text
    version=response.json()
    monkeypatch.setattr('app.clause_structure.build_clauses',lambda *a: (_ for _ in ()).throw(AssertionError('must not rebuild')))
    read=client.get('/api/v1/versions/'+version['id']); assert read.status_code==200,read.text
    assert read.json()['structure_version']=='clause-tree-v2'
    assert read.json()['clauses'][1]['parent_id']==version['clauses'][0]['id']
    assert client.get('/api/v1/versions/'+version['id']+'/file').content==data
    # Legacy snapshots remain legacy, even after the parser is upgraded.
    with sqlite3.connect(path) as db:
        parsed=json.loads(db.execute('select parsed from versions where id=?',(version['id'],)).fetchone()[0])
        parsed['clauses'][0]['title']='历史标题'; parsed.pop('structure_version'); parsed.pop('structure_summary')
        db.execute('update versions set parsed=? where id=?',(json.dumps(parsed),version['id']))
    old=client.get('/api/v1/versions/'+version['id']).json()
    assert old['clauses'][0]['title']=='历史标题' and old['structure_version']=='clause-tree-v1'
