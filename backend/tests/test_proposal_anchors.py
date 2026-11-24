import pytest
from app.proposal_anchors import AnchorError, relocate_anchor


def blocks(texts, version='old'):
    return [{'id':f'{version}:p{i}', 'text':t} for i,t in enumerate(texts)]


def resolve(old, new, index=1, **kwargs):
    value=kwargs.pop('expected_paragraph',None)
    expected=old[index] if value is None else value
    return relocate_anchor(blocks(old),blocks(new,'new'),f'old:p{index}',expected,0,len(expected),
                           expected_paragraph=value,**kwargs)


@pytest.mark.parametrize('new,index',[
    (['新增','前文','付款条款','尾文'],2),
    (['付款条款','尾文'],0),
    (['尾文','前文','付款条款'],2),
])
def test_unique_paragraph_survives_insert_delete_and_move(new,index):
    result=resolve(['前文','付款条款','尾文'],new)
    assert result['index']==index
    assert result['block']['id']==f'new:p{index}'
    assert result['method']=='unique_paragraph'


def test_repeated_paragraph_uses_ordered_surroundings_not_first_match():
    old=['第一条','相同正文','第二条','相同正文','尾文']
    new=['新增','第一条','相同正文','第二条','相同正文','尾文']
    result=resolve(old,new,3)
    assert result['index']==4
    assert result['method']=='ordered_context'


@pytest.mark.parametrize('index',[0,1])
def test_deleting_identical_duplicate_cannot_prove_which_survived(index):
    with pytest.raises(AnchorError,match='无法唯一定位') as error:
        resolve(['相同','相同'],['相同'],index)
    assert error.value.code=='ambiguous_anchor'


def test_adding_duplicate_with_no_context_is_ambiguous():
    with pytest.raises(AnchorError) as error:
        resolve(['相同'],['相同','相同'],0)
    assert error.value.code=='ambiguous_anchor'


def test_unchanged_order_can_locate_repeated_paragraphs():
    assert resolve(['相同','相同'],['相同','相同'],1)['index']==1


def test_changed_paragraph_is_rejected_even_when_original_quote_remains():
    with pytest.raises(AnchorError) as error:
        relocate_anchor(blocks(['甲方支付100元']),blocks(['甲方支付100元，但可免除'],'new'),
                        'old:p0','100元',4,8)
    assert error.value.code=='target_changed'


def test_unicode_offsets_are_codepoints_and_ids_are_not_reused():
    result=relocate_anchor(blocks(['甲😀付款100元']),blocks(['无关','甲😀付款100元'],'new'),
                           'old:p0','😀付款',1,4)
    assert result['start']==1 and result['end']==4
    assert result['block']['id']=='new:p1'


def test_completed_revision_can_be_relocated_for_a_comment():
    result=resolve(['前文','旧稿','尾文'],['新增','前文','新稿😀','尾文'],expected_paragraph='新稿😀')
    assert result['index']==2 and result['end']==3


def test_one_candidate_is_not_enough_when_source_can_be_skipped():
    with pytest.raises(AnchorError) as error:
        resolve(['相同','分隔','相同'],['分隔','相同'],0)
    assert error.value.code=='ambiguous_anchor'


@pytest.mark.parametrize('start,end,quote',[(True,2,'ab'),(0,5,'abc'),(0,2,'ac'),(1,1,'')])
def test_bad_offsets_never_rebase(start,end,quote):
    with pytest.raises(AnchorError) as error:
        relocate_anchor(blocks(['abc']),blocks(['abc'],'new'),'old:p0',quote,start,end)
    assert error.value.code=='invalid_anchor'


def test_duplicate_source_ids_are_rejected():
    source=blocks(['a','b']);source[1]['id']=source[0]['id']
    with pytest.raises(AnchorError) as error:
        relocate_anchor(source,blocks(['a'],'new'),'old:p0','a',0,1)
    assert error.value.code=='invalid_anchor'


def test_alignment_limit_is_explicit_without_truncating(monkeypatch):
    monkeypatch.setattr('app.proposal_anchors.MAX_ALIGNMENT_CELLS',8)
    with pytest.raises(AnchorError) as error:
        resolve(['相同','相同'],['相同','相同'],0)
    assert error.value.code=='anchor_scope_too_large'


def test_unique_path_does_not_pay_quadratic_alignment_cost(monkeypatch):
    monkeypatch.setattr('app.proposal_anchors.MAX_ALIGNMENT_CELLS',1)
    assert resolve(['a','b'],['x','a','b'])['index']==2
