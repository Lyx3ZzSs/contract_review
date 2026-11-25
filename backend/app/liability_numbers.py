"""Resolve short identifiers to monetary amounts and percentages in the supplied text."""
import re
from typing import Literal

from pydantic import Field, ValidationError, create_model
from typing_extensions import TypeAliasType

from .liability_limit import LimitFacts, Number, Scenario
from .llm import ExtractionError
from .models import Model
from .structured_review import fail


ARABIC = r"(?:[0-9]{1,3}(?:[,，][0-9]{3})+|[0-9]+)(?:\.[0-9]+)?"
CHINESE = r"[零〇一二两三四五六七八九十百千]+"
NUMBER = re.compile(r"(?<![\d.．负万亿零〇一二两三四五六七八九十百千-])(?<!\d[,，])"
                    rf"(?P<value>【\s*{ARABIC}\s*】|{ARABIC}|{CHINESE})\s*(?P<unit>亿元|万元|元|[%％‰])")
NUMBER_PROMPT = ("number_catalog中每个编号对应[段落编号,逐字原文]。金额只选m编号，税率和比例只选p编号。"
                 "区分元/月与年度服务费、服务价款上限与违约责任上限、百分率与千分率。按日/按次的次数或实际退款基数未知时"
                 "components留空，不得用同段另一触发条件的费率或其他段的同额奖励替代。不得将月费视为全年费用。"
                 "只有金额和基数来自同一责任或有明示交叉引用时才使用。其他refs仍填写原文段落编号。")


def numeric_value(match):
    from decimal import Decimal
    from .clause_structure import article_number
    from .docx_structure import chinese
    value = match['value'].strip('【】 ').replace(',', '').replace('，', '')
    if re.fullmatch(CHINESE, value):
        normalized = value.replace('两', '二').replace('〇', '零')
        n = int(article_number(normalized))
        if chinese(n) != normalized:
            return None
        return Decimal(n)
    return Decimal(value)


def number_catalog(paragraphs):
    catalog = {}
    for ref, _, _, _, text in paragraphs:
        seen = set()
        for match in NUMBER.finditer(text):
            literal = match.group()
            if literal in seen or numeric_value(match) is None:
                continue
            seen.add(literal)
            prefix = 'p' if match['unit'] in ('%', '％', '‰') else 'm'
            catalog[prefix + str(len(catalog) + 1)] = (ref, literal)
    return catalog


def number_ids(catalog, prefix, name):
    keys = tuple(key for key in catalog if key.startswith(prefix))
    return TypeAliasType(name, Literal[keys]) if keys else type(None)


class LimitReader:
    def __init__(self, catalog, validate, *, clause_details=False, facts_only=False, validate_amounts=None):
        self.catalog = catalog
        self.validate = validate
        self.validate_amounts = validate_amounts
        money = number_ids(catalog, 'm', 'MoneyID')
        percent = number_ids(catalog, 'p', 'PercentageID')
        amount = create_model('IndexedAmount', __base__=Model,
                              money=(money, ...), rate=(percent | None, None),
                              obligation_ref=(str | None, None), obligation_quote=(str | None, None))
        scenario = create_model('IndexedScenario', __base__=Scenario,
                                components=(list[amount], Field()), cap=(amount | None, None))
        scenarios = Field(max_length=0) if money is type(None) else Field()
        from .liability_limit import ClauseExposure
        clause_fields = {'clause_exposures': (list[ClauseExposure], ...)} if clause_details else {}
        if facts_only:
            clause_fields = {'clause_exposures': (list[ClauseExposure], Field(default_factory=list,max_length=0)),
                            'candidate_refs': (list[str], ...)}
        self.wire_schema = create_model('IndexedLimitFacts', __base__=LimitFacts,
            tax=(percent | None, None), contract_total=(money | None, None), annual_fee=(money | None, None),
            aggregate_cap=(amount | None if money is not type(None) else type(None), None),
            scenarios=(list[scenario], scenarios), **clause_fields)

    def __call__(self, facts):
        return self.validate(facts)

    def number(self, key, kind):
        if key is None:
            return None
        if key not in self.catalog or not key.startswith(kind):
            raise fail('liability_limit_invalid_number_id')
        ref, literal = self.catalog[key]
        return Number(ref=ref, literal=literal)

    def amount(self, value):
        if value is None:
            return None
        return {'money': self.number(value.money, 'm'), 'rate': self.number(value.rate, 'p'),
                'obligation_ref': value.obligation_ref, 'obligation_quote': value.obligation_quote}

    def read(self, raw, repair, trace):
        try:
            indexed = self.wire_schema.model_validate(raw)
        except ValidationError as exc:
            error = fail('liability_limit_invalid_fields')
            error.diagnostics = [{'field': list(e['loc']), 'type': e['type'],
                                  'instruction': '数字字段只选其schema枚举中与原文对应的编号。'}
                                 for e in exc.errors(include_input=False)]
            raise error from None
        scenarios = [{**s.model_dump(), 'cap': self.amount(s.cap),
                      'components': [self.amount(c) for c in s.components]} for s in indexed.scenarios]
        facts = LimitFacts.model_validate({**indexed.model_dump(), 'scenarios': scenarios,
                    'tax': self.number(indexed.tax, 'p'), 'aggregate_cap': self.amount(indexed.aggregate_cap),
                    'annual_fee': self.number(indexed.annual_fee, 'm'),
                    'contract_total': self.number(indexed.contract_total, 'm')})
        result = self.validate(facts)
        if self.validate_amounts:
            try:
                self.validate_amounts(facts)
            except ExtractionError as exc:
                trace.append({'stage': 'liability_amounts', 'status': 'partial', 'unresolved': True,
                              'diagnostics': getattr(exc, 'diagnostics', [])})
        return facts, result
