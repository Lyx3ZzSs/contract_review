"""High-confidence textual reference index; no claims about actual received files.

This index supplements model recall for explicit names. Unknown names/roles remain
unknown. Payment normalization only handles an unambiguous two-instalment pattern.
"""
import re
from decimal import Decimal

TITLE=re.compile(r'《([^》\n]{1,100})》')
ANNEX_NAME=re.compile(r'附件|附表|报价|价目|授权(?:委托)?书|确认单|技术.*(?:规范|要求|方案)|服务清单')
BARE=re.compile(r'附件(?:[A-Z][A-Z0-9-]*|\d+|[一二三四五六七八九十]+)(?![A-Za-z0-9])')
UNAVAILABLE=re.compile(r'(?:未|尚未|没有|无法)(?:提供|上传|收到|取得|辨认|读取)|缺少|无法辨认|不可读')
RATE=r'(?:\d+(?:\.\d+)?\s*[%％]|(?:\d+(?:\.\d+)?|[一二三四五六七八九十])成(?![零一二三四五六七八九十半\d]))'
HEAD=re.compile(r'(?:首期|首付款|首付|预付款)[^。；，,\d一二三四五六七八九十]{0,12}('+RATE+r')')
TAIL=re.compile(r'(?:尾期|尾款)[^。；，,\d一二三四五六七八九十]{0,12}('+RATE+r')')
AMBIGUOUS_BASE=re.compile(r'剩余|余款|收益|违约|利息|当期|另行|基数|不含税')
SAME_BASE_PREFIX = re.compile(r'(?:为|按|以|支付|应付|占|比例|[:：=]|\s)*(?:(?:合同总价|合同价款|固定价款|总金额)的?)?')


def rate_value(token):
    token=token.replace(' ','')
    if token.endswith(('%','％')):return str(Decimal(token[:-1]))
    number=token[:-1]
    mapping={char:str(i+1) for i,char in enumerate('一二三四五六七八九十')}
    return str(Decimal(mapping.get(number,number))*10)


def index_references(sources,grounded_role,tech_pattern,price_pattern):
    by_name={};plans=[]
    for ref,block in sources.blocks.items():
        text=block['text']
        titles=[m.group(1) for m in TITLE.finditer(text) if ANNEX_NAME.search(m.group(1)) or re.search(r'附件[：: ]*$',text[max(0,m.start()-8):m.start()])]
        names=titles+[m.group(0) for m in BARE.finditer(text) if not any(m.group(0) in title for title in titles)]
        for name in dict.fromkeys(names):
            item=by_name.setdefault(name,{'name':name,'references':[],'technical_refs':[],'pricing_refs':[]})
            item['references'].append(ref)
            if grounded_role(name,text,tech_pattern):item['technical_refs'].append(ref)
            if grounded_role(name,text,price_pattern):item['pricing_refs'].append(ref)
        head,tail=HEAD.search(text),TAIL.search(text)
        if head and tail and re.search(r'(总价|年度费用|固定价款|固定价格|总金额|合同价款).{0,20}元',text) and not AMBIGUOUS_BASE.search(text) and not ('含税' in text and '未税' in text):
            # Extra rates/penalties could refer to a different calculation basis.
            prefixes = [text[m.start():m.start(1)] for m in (head, tail)]
            prefixes = [re.sub(r'^(?:首期|首付款|首付|预付款|尾期|尾款)', '', value) for value in prefixes]
            if len(re.findall(RATE,text))==2 and all(SAME_BASE_PREFIX.fullmatch(s) for s in prefixes):
                plans.append({'operation':'sum','operands':[rate_value(head.group(1)),rate_value(tail.group(1))],'stated_total':'100','refs':[ref],
                              'source_tokens':[head.group(1),tail.group(1)]})
    return list(by_name.values()),plans


def explicitly_unavailable(name,text):
    for sentence in re.split(r'[。；;\n]',text):
        if name not in sentence:continue
        clauses=re.split(r'[，,]',sentence)
        for clause in clauses:
            if name in clause and '已提供' not in clause and UNAVAILABLE.search(clause):return True
        named={m.group(1) for m in TITLE.finditer(sentence)}|set(BARE.findall(sentence))
        if named.issubset({name}):
            if any(re.fullmatch(r'(?:本次|目前|当前|该附件|附件)?(?:尚|暂)?未提供(?:该附件|附件)?',c.strip()) for c in clauses):return True
        if '已提供' not in sentence and re.search(r'(?:两个|两份|上述|全部|所有).{0,4}附件.{0,8}(?:未提供|未上传|不可读)',sentence):return True
    return False
