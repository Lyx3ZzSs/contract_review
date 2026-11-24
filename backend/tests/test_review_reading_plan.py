from app.clause_structure import build_clauses
from app.parser import namespace_parsed

def test_common_heading_forms_and_versioned_mapping():
    headings=['第一条服务范围','一、服务范围','1. 服务范围','1.1服务范围','（一）服务范围']
    for title in headings:
        parsed=namespace_parsed({'blocks':[{'id':'p1','text':title},{'id':'p2','text':'正文内容。'}]},'v')
        assert parsed['clauses'][0]['kind']=='clause'
        assert parsed['clauses'][0]['block_ids']==['v:p1','v:p2']
        assert parsed['clauses'][0]['source_order']==0

def test_decimal_amount_is_not_a_numbered_clause():
    for value in ['100元费用','1.1万元费用','2026.11.13日期']:
        assert build_clauses('v',[{'id':'p','text':value}])[0]['kind']=='paragraph'


def test_table_and_unresolved_numbering_do_not_merge_into_previous_clause():
    blocks=[{'id':'a','text':'第一条服务范围'},{'id':'b','text':'自动列表内容','automatic_numbering':True},
            {'id':'c','text':'表格正文','table_location':{'table':1,'row':1,'cell':1}},{'id':'d','text':'表格外正文'}]
    units=build_clauses('v',blocks)
    assert [u['block_ids'] for u in units]==[['a'],['b'],['c'],['d']]
    assert units[1]['parse_gaps']==['自动编号未还原']
    assert units[2]['kind']=='table'
