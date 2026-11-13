"""Deterministic classification of model-extracted RL-05 observations.

The observations remain model candidates; quote validation is not human verification.
"""
from typing import Literal
from pydantic import Field
from .models import Model,Evidence


class FieldObservation(Model):
    name: str = Field(min_length=1,max_length=100)
    value_state: Literal['filled','blank','placeholder','unavailable']
    timing: Literal['current_required','future_template','signature_block','unknown']
    evidence: list[Evidence] = Field(min_length=1)
    requirement_evidence: list[Evidence] = Field(default_factory=list)


def classify_one(item):
    """The same deterministic rule for aggregate judgments and display observations."""
    name=f'字段“{item.name}”'
    if item.value_state=='filled':
        return 'no_flag_for_target_rule',name+'已有填写，不按空白处理。'
    if item.timing in ('future_template','signature_block'):
        return 'no_flag_for_target_rule',name+'位于未来模板或签署栏，当前不自动认定关键字段缺项。'
    # A blank administrative identifier alone does not establish a missing
    # contractual term. Keep the observation without inventing a duty to fill
    # it or a request for the user to prove that such a duty exists.
    if item.name.strip() in ('合同编号','合同号') and item.value_state in ('blank','placeholder') and not item.requirement_evidence:
        return 'no_flag_for_target_rule',name+'为空白或占位，但未见当前必须填写的依据；保留填写状态记录，不列为审查待办。'
    if item.value_state in ('blank','placeholder') and item.timing=='current_required' and item.requirement_evidence:
        return 'flag',name+'仍为空白或占位，且引用了当前填写要求，列为待人工核对的缺项。'
    return 'insufficient_evidence',name+'的内容或当前填写要求尚不能确认，需补证。'


def classify(observations):
    judgments=[classify_one(item) for item in observations]
    statuses=[status for status,_ in judgments]
    status='flag' if 'flag' in statuses else 'insufficient_evidence' if 'insufficient_evidence' in statuses else 'no_flag_for_target_rule'
    return status,''.join(note for _,note in judgments) or '本次已解析范围内未提取到关键字段的具体空白或占位证据。'
