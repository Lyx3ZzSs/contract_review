"""Compute RL-02 from quoted model observations, without inventing tolerance."""
from decimal import Decimal,InvalidOperation,localcontext
from typing import Literal
from pydantic import Field,model_validator
from .models import Model,Evidence


class AmountObservation(Model):
    issue: Literal['calculation','missing_basis','payment_timing','no_comparison']
    operation: Literal['sum','product','percentage','none'] = 'none'
    operands: list[str] = Field(default_factory=list,max_length=20)
    stated_total: str | None = None
    basis: Literal['consistent','unknown'] = 'unknown'
    evidence: list[Evidence]

    @model_validator(mode='after')
    def numeric(self):
        if self.issue!='no_comparison' and not self.evidence:raise ValueError('evidence required for concrete observation')
        for text in self.operands+([self.stated_total] if self.stated_total is not None else []):
            if len(text)>60:raise ValueError('number too long')
            try:value=Decimal(text)
            except InvalidOperation:raise ValueError('invalid number')
            if not value.is_finite() or abs(value.as_tuple().exponent)>20 or value.adjusted()>30:raise ValueError('invalid magnitude')
        if self.issue=='calculation':
            if self.operation=='none' or len(self.operands)<2 or self.stated_total is None:raise ValueError('incomplete calculation')
            if self.operation in ('product','percentage') and len(self.operands)!=2:raise ValueError('two operands required')
        elif self.operation!='none' or self.operands or self.stated_total is not None:raise ValueError('unexpected calculation')
        return self


class LegacyAmountObservation(AmountObservation):
    evidence: list[Evidence] = Field(min_length=1)


def classify(observations):
    statuses=[];notes=[];calculations=[]
    for item in observations:
        if item.issue in ('payment_timing','no_comparison'):
            statuses.append('no_flag_for_target_rule')
            notes.append('付款时间安排不属于金额计算矛盾。' if item.issue=='payment_timing' else '本次引用内容未提供需要比较的金额矛盾。')
        elif item.issue=='missing_basis' or item.basis=='unknown':
            statuses.append('insufficient_evidence');notes.append('引用的计算基数或同口径条件不明，需补充后核算。')
        else:
            with localcontext() as ctx:
                ctx.prec=128
                values=[Decimal(x) for x in item.operands]
                computed=sum(values) if item.operation=='sum' else values[0]*values[1]/(100 if item.operation=='percentage' else 1)
                delta=computed-Decimal(item.stated_total)
            calculations.append({'operation':item.operation,'operands':item.operands,'stated_total':item.stated_total,'computed':str(computed),'difference':str(delta),'tolerance':None})
            if delta==0:
                statuses.append('no_flag_for_target_rule');notes.append(f'按抽取的同口径数值复算为{computed}，与对应列示值一致。')
            else:
                statuses.append('insufficient_evidence');notes.append(f'按抽取数值复算为{computed}，列示值{item.stated_total}，差额{delta}；容差和舍入口径未配置，需人工核实。')
    status='insufficient_evidence' if 'insufficient_evidence' in statuses else 'no_flag_for_target_rule'
    return status,''.join(notes) or '本次已解析范围内未提取到具体金额矛盾或计算口径缺失证据。',calculations
