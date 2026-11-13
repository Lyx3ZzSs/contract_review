import pytest
from app.structured_review import Sources
from app.fact_grounding import ground_number, validate_calculation


def src(text): return Sources([{'id':'v:p1','text':text}])
def calc(ops, total, quote, operation='sum'):
    return dict(operation=operation,operands=ops,stated_total=total,refs=['b1'],relation_quote=quote,
                operand_tokens=ops,total_token=total,relation_kind='explicit_formula')


def test_invented_numbers_rejected():
    s=src('承保100%，激励40%，考核60%。')
    assert validate_calculation(calc(['30','70'],'100',s.text(['b1'])),s)['reason']=='number_not_grounded'


def test_numbers_present_but_unrelated_are_not_a_formula():
    s=src('高于承保电价时按40%奖励，低于承保电价时按60%考核，承保100%。')
    assert validate_calculation(calc(['40','60'],'100',s.text(['b1'])),s)['state']=='unsupported'


def test_explicit_formula_validated_with_exact_tokens():
    s=src('同为人民币含税金额，分项合计：30+70=100元。')
    assert validate_calculation(calc(['30','70'],'100','30+70=100'),s)['state']=='verified'


def test_wrong_claimed_operation_rejected():
    s=src('30×70=2100元。')
    assert validate_calculation(calc(['30','70'],'2100','30×70=2100'),s)['state']=='unsupported'


def test_wrong_total_is_still_grounded_then_arithmetic_detects_difference():
    s=src('同口径合计30+70=110元。')
    assert validate_calculation(calc(['30','70'],'110','30+70=110'),s)['state']=='verified'


def test_untrusted_total_cannot_use_percentage_exception():
    s=src('服务价款30元，违约金70元。')
    assert validate_calculation(calc(['30','70'],'100',s.text(['b1'])),s)['state']=='unsupported'


@pytest.mark.parametrize('token,value', [('１，０００','1000'),('一成','10'),('30％','30')])
def test_normalized_number_retains_source(token,value):
    assert ground_number(token,value,'b1',src('金额或比例为'+token))['normalized']==value


def test_number_substring_cannot_be_a_different_number():
    with pytest.raises(ValueError):ground_number('30','30','b1',src('金额为1300元'))


def test_live_cross_cell_formula_is_excluded_by_schema():
    from pydantic import ValidationError
    from app.fact_grounding import GroundedCalculation
    # S02 live extraction invented a sentence by joining four separate cells.
    candidate=calc(['45','40','40'],'125','1 电力交易辅助决策支持系统V1.0 安徽 1 套 45；2 山东 1 套 40；3 辽宁 1 套 40；合计 人民币：125万元整')
    candidate['refs']=['b107','b112','b117','b119']
    with pytest.raises(ValidationError):GroundedCalculation.model_validate(candidate)


def test_live_unit_bearing_tokens_excluded_by_schema():
    from pydantic import ValidationError
    from app.fact_grounding import GroundedCalculation
    candidate=calc(['120000','6'],'113207.55','上述价格为含6%增值税价格')
    candidate['operand_tokens']=['120000元/年','6%'];candidate['total_token']='113207.55元'
    with pytest.raises(ValidationError):GroundedCalculation.model_validate(candidate)


def test_live_tax_conversion_and_invented_retention_percentage_stay_rejected():
    # These are genuine extraction errors, not valid calculations to whitelist.
    s=src('合计120000元，不含税金额113207.55元，上述价格为含6%增值税价格。')
    candidate=calc(['120000','6'],'113207.55',s.text(['b1']),'percentage')
    assert validate_calculation(candidate,s)['state']=='unsupported'
    s=src('质保款：甲方无息支付剩余 100% 质保款，即人民币12000.00元。')
    candidate=calc(['50','40','10'],'100',s.text(['b1']))
    candidate.update(operand_tokens=['50%','40%','100%'],relation_kind='instalment_percentages')
    assert validate_calculation(candidate,s)['state']=='unsupported'
