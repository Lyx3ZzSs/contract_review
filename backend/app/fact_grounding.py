"""Verify numeric provenance and supported relations before arithmetic, not after it."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal
from pydantic import Field
from .structured_review import ContractFacts, Calculation


NumericToken = Annotated[str, Field(pattern=r'^(?:[0-9０-９]+(?:[,，][0-9０-９]{3})*(?:[.．][0-9０-９]+)?\s*[%％]?|[一二三四五六七八九十0-9０-９]+成)$')]


class GroundedCalculation(Calculation):
    refs: list[str] = Field(min_length=1,max_length=1, description='Exactly one source block containing the complete numeral equation; never combine table cells into a synthetic quote')
    operand_tokens: list[NumericToken] = Field(min_length=2,max_length=20)
    total_token: Annotated[str, Field(pattern=r'^(?:[0-9０-９]+(?:[,，][0-9０-９]{3})*(?:[.．][0-9０-９]+)?\s*[%％]?|[一二三四五六七八九十0-9０-９]+成)?$')]
    relation_quote: str = Field(min_length=1,max_length=1200)
    relation_kind: Literal['explicit_formula','instalment_percentages']


class GroundedFacts(ContractFacts):
    calculations: list[GroundedCalculation] = Field(max_length=50)


GROUNDING_PROMPT = '''
金额计算额外要求：每个operands对应operand_tokens原文数值词元，stated_total对应total_token，relation_quote为同一段内完整连续的计算依据原文，relation_kind为explicit_formula或instalment_percentages。
只有原文明确提供可比较的数字算式或同总价付款比例才列calculations。只有带变量的计费公式、不同触发条件的奖励/考核比例，不虚构数值算式。
instalment_percentages仅用于同基数首期/尾款比例，合计100为服务端推导，此时total_token可为空。绝不能复制提示中的示例数值。没有可比较数字算式时calculations=[]。
本schema仅能表达一个原文block中的数字等式，refs必须恰好一个；explicit_formula必须在该block中真的出现数字、运算符及等号（如原文含“+”“×”“=”），不能把表格的分项、合计或付款条件跨block拼成公式/连续quote。跨单元表格合计、含税转未税的除法、不同基数分期当前不属于此计算器支持范围，不列入calculations，也不得因此宣称已核验。
instalment_percentages只可逐字段使用normalized_instalment_candidates中已有候选；候选为空则不得自行生成分期合计。原文“剩余100%质保款”不代表合同总价10%，不能把100%归一化成10或自动求余。operand_tokens和total_token仅取数值词元（可含%/成），不含元、万元、年等单位；数值必须与原文精确一致。税率不是含税总价转未税总价的乘数，不能套percentage操作。
'''


def normalized_token(token):
    text=unicodedata.normalize('NFKC',token).replace(',','').replace(' ','')
    if text.endswith('成'):
        n=text[:-1];mapping={c:str(i+1) for i,c in enumerate('一二三四五六七八九十')}
        return Decimal(mapping.get(n,n))*10
    return Decimal(text.rstrip('%'))


def ground_number(token, normalized, ref, sources):
    text=sources.text([ref])
    if not token or token not in text:raise ValueError('number_not_grounded')
    for match in re.finditer(re.escape(token),text):
        before=text[match.start()-1:match.start()] if match.start() else ''
        after=text[match.end():match.end()+1]
        if (before and (before.isdigit() or before in '.,，．')) or (after and (after.isdigit() or after in '.,，．')):continue
        try:
            if normalized_token(token)!=Decimal(normalized):raise ValueError('number_normalization_mismatch')
        except (InvalidOperation,ValueError):raise ValueError('number_normalization_mismatch') from None
        return {'ref':ref,'token':token,'normalized':normalized,'start':match.start(),'end':match.end()}
    raise ValueError('number_not_grounded')


def validate_calculation(candidate, sources):
    c=candidate.model_dump() if hasattr(candidate,'model_dump') else candidate
    refs=c['refs'];quote=c.get('relation_quote','');tokens=c.get('operand_tokens',c['operands'])
    def reject(reason):return {'state':'unsupported','reason':reason}
    try:
        sources.evidence(refs)
        if len(tokens)!=len(c['operands']):return reject('number_not_grounded')
        grounded=[]
        for token,value in zip(tokens,c['operands']):
            found=None
            for ref in refs:
                try:found=ground_number(token,value,ref,sources);break
                except ValueError:pass
            if found is None:return reject('number_not_grounded')
            grounded.append(found)
        quote_refs=[r for r in refs if quote and sources.text([r]).count(quote)==1]
        if len(quote_refs)!=1:return reject('relation_not_grounded')
        ref=quote_refs[0]
        if any(x['ref']!=ref or x['token'] not in quote for x in grounded):return reject('relation_not_grounded')
        # Exact indexed same-base instalments are the only permitted derived 100.
        if c.get('relation_kind')=='instalment_percentages':
            from .reference_index import index_references
            from .structured_review import grounded_role,TECH,PRICE
            _,plans=index_references(sources,grounded_role,TECH,PRICE)
            match=next((p for p in plans if p['refs']==refs and p['operands']==c['operands'] and c['operation']=='sum' and c['stated_total']=='100'),None)
            return {'state':'verified','reason':None,'numbers':grounded,'derived_total':'same_base_instalments'} if match else reject('unsupported_relationship')
        total=ground_number(c.get('total_token',''),c['stated_total'],ref,sources)
        if total['token'] not in quote:return reject('number_not_grounded')
        # Only actual numeral equations are certified. Prose needs manual checking.
        q=unicodedata.normalize('NFKC',quote).replace(' ','').replace(',','')
        values=[re.escape(unicodedata.normalize('NFKC',t).replace(',','').replace(' ','')) for t in tokens]
        total_pattern=re.escape(unicodedata.normalize('NFKC',total['token']).replace(',','').replace(' ',''))
        op={'sum':r'\+','product':r'[×*]','percentage':r'[×*]'}[c['operation']]
        left=op.join(values)
        if c['operation']=='percentage' and not tokens[-1].endswith(('%','％')):left+=r'%'
        pattern=r'(?<![\d.])'+left+r'='+total_pattern+r'(?![\d.])'
        if not re.search(pattern,q):return reject('unsupported_relationship')
        context=sources.text([ref])
        if ('含税' in context and ('未税' in context or '不含税' in context)) or ('美元' in context and ('人民币' in context or '元' in context)):
            return reject('mixed_basis')
        return {'state':'verified','reason':None,'numbers':grounded+[total]}
    except (ValueError,KeyError):return reject('number_not_grounded')
