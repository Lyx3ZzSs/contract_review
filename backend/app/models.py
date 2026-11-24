from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class ContractCreate(Model):
    data_purpose: Literal['business', 'test'] = 'business'
    client_metadata: dict = Field(default_factory=dict)
    title: str = Field(min_length=1, max_length=300)
    contract_type: str = Field(min_length=1, max_length=100)
    our_party: str = Field(min_length=1, max_length=100)
    stage: Literal['draft', 'pre_sign', 'signed', 'performance', 'unknown'] = 'unknown'


class Evidence(Model):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    block_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1)

    @model_validator(mode='after')
    def ordered(self):
        if self.end <= self.start:
            raise ValueError('end must be greater than start')
        return self


class Fact(Model):
    evidence: list[Evidence] = Field(min_length=1)


class Term(Fact):
    subject: str = Field(min_length=1)
    term_type: str = Field(min_length=1)
    start_event: str = Field(min_length=1)
    duration_months: int = Field(gt=0)
    # Must be explicitly resolved by the reviewer, including amendment priority.
    comparison_confirmed: bool = False


class Amount(Fact):
    components: list[Decimal] = Field(min_length=1, max_length=100)
    stated: Decimal
    currency: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    basis: str = Field(min_length=1)
    same_basis_confirmed: bool = False
    tolerance: Decimal | None = Field(default=None, ge=0)


class Transfer(Fact):
    party: Literal['customer', 'our_party', 'both', 'unknown']
    consent: Literal['required', 'not_required', 'unspecified']
    exceptions_resolved: bool = False


class Attachment(Fact):
    name: str = Field(min_length=1)
    state: Literal['provided', 'missing', 'unreadable', 'title_only', 'future']
    bundle_complete: bool = False
    required_now: bool | None = None


class RequiredField(Fact):
    name: str = Field(min_length=1)
    blank: bool
    required_now: bool | None = None


class FactFields(Model):
    terms: list[Term] = Field(default_factory=list, max_length=500)
    amounts: list[Amount] = Field(default_factory=list, max_length=500)
    transfers: list[Transfer] = Field(default_factory=list, max_length=500)
    attachments: list[Attachment] = Field(default_factory=list, max_length=500)
    fields: list[RequiredField] = Field(default_factory=list, max_length=500)


class Facts(FactFields):
    origin: Literal['manual_verified'] = 'manual_verified'
    verified_by: str = Field(min_length=1, max_length=100)


class RunCreate(Model):
    document_version_id: str
    idempotency_key: str = Field(min_length=1, max_length=100)
    facts: Facts | None = None
    extraction_id: str | None = None


class DecisionCreate(Model):
    action: Literal['acknowledged', 'ignored', 'needs_business_confirmation', 'false_positive', 'exception_recorded']
    note: str = Field(min_length=1, max_length=5000)
    actor: str | None = Field(default=None, min_length=1, max_length=100)


class CompletionFields(Model):
    opinion: str = Field(default="", max_length=10000)
    reservations: str = Field(default="", max_length=10000)
    reviewer: str | None = Field(default=None, min_length=1, max_length=100)
    editor_session_id: str | None = None


class Complete(CompletionFields):
    expected_document_version_id: str | None = None


class TableLocation(Model):
    table: int = Field(ge=1)
    row: int = Field(ge=1)
    cell: int = Field(ge=1)


class Block(Model):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=False)
    id: str
    text: str
    automatic_numbering: bool = False
    table_location: TableLocation | None = None
    style_id: str | None = None
    heading_level: int | None = Field(default=None, ge=1, le=9)
    numbering: dict | None = None


class ClauseSourceSpan(Model):
    block_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class ClauseNode(Model):
    id: str
    document_version_id: str
    parent_id: str | None = None
    kind: str
    number: str | None = None
    title: str
    block_ids: list[str]
    source_order: int
    extraction_method: str
    source_spans: list[ClauseSourceSpan] = Field(default_factory=list)
    structure_source: str | None = None
    resolution_status: str = 'legacy'
    parse_gaps: list[str] = Field(default_factory=list)
    table_location: TableLocation | None = None


class SourceDocument(Model):
    filename: str
    sha256: str
    format: Literal['doc']


class VersionView(Model):
    source_document: SourceDocument | None = None
    clauses: list[ClauseNode] = Field(default_factory=list)
    structure_version: str = 'clause-tree-v1'
    structure_summary: dict = Field(default_factory=dict)
    block_locations: dict = Field(default_factory=dict)
    image_block_ids: list[str] = Field(default_factory=list)
    id: str
    contract_id: str
    revision: int
    sha256: str
    filename: str
    created_at: str
    parser_version: str
    view: Literal['proposed']
    blocks: list[Block]
    limitations: list[str]
    tracked_changes_present: bool


class PresentationObservation(Model):
    name: str
    status: Literal['flag', 'insufficient_evidence', 'no_flag_for_target_rule']
    evidence: list[Evidence]
    requirement_evidence: list[Evidence]


class IssuePresentation(Model):
    version: Literal['issue-presentation-v1']
    title: str
    summary: str
    next_step: str
    observations: list[PresentationObservation]


class ReviewCardParagraph(Model):
    title: str | None = None
    status: Literal["flag","insufficient_evidence"] | None = None
    kind: Literal['daily', 'paid_refund', 'fee_forfeiture', 'stacked_remedies', 'repeat_deduction', 'other_liability'] | None = None
    direction: str | None = None
    text: str
    evidence: list[Evidence]


class ReviewCardContent(Model):
    version: Literal['review-card-v1'] = 'review-card-v1'
    risk_paragraphs: list[ReviewCardParagraph]
    modification_plan: str


class Finding(Model):
    review_category: Literal['transaction', 'procedure', 'wording', 'legality', 'other'] | None = None
    premise_check: dict | None = None
    revision_requirements: list[dict] | None = None
    revision_plan: dict | None = None
    card_content: ReviewCardContent | None = None
    review_state: Literal['preliminary','drafting','pending_reconciliation','reviewed','adjusted','merged','retracted','incomplete'] | None = None
    review_state_reason: str | None = None
    provenance: dict | None = None
    reconciliation: dict | None = None
    category: str | None = None
    source_refs: list[str] | None = None
    related_issue_key: str | None = None
    reconciliation_note: str | None = None
    event_id: str | None = None
    event_anchor: Evidence | None = None
    clause_number: str | None = None
    display_group: str | None = None
    mechanisms: list[str] | None = None
    applicability_state: str | None = None
    title: str | None = None
    execution_mode: str | None = None
    review_reason: str | None = None
    execution_state: str | None = None
    module: str | None = None
    numeric_grounding: dict | list | None = None
    policy_threshold: float | None = None
    presentation: IssuePresentation | None = None
    run_id: str | None = None
    subject_key: str | None = None
    kind: str | None = None
    ai_status: str | None = None
    clause_ids: list[str] = Field(default_factory=list)
    supersedes_issue_id: str | None = None
    attachment_name: str | None = None
    reference_name: str | None = None
    attachment_state: str | None = None
    match_state: str | None = None
    material_bundle_id: str | None = None
    reference_evidence: list[Evidence] = Field(default_factory=list)
    content_evidence: list[Evidence] = Field(default_factory=list)
    attachment_reference: dict | None = None
    attachment_checks: list[dict] | None = None
    attachment_references: list[dict] | None = None
    extraction_diagnostics: dict | None = None
    amount_checks: list[dict] | None = None
    computed_calculations: list[dict] | None = None
    field_checks: list[dict] | None = None
    model_proposed_status: str | None = None
    model_explanation: str | None = None
    id: str
    rule_id: Literal['RL-01', 'RL-02', 'RL-03', 'RL-04', 'RL-05', 'CR-01', 'CR-02', 'CR-03', 'CR-04', 'CR-05', 'CR-06', 'VL-01']
    document_version_id: str
    status: Literal['flag', 'no_flag_for_target_rule', 'insufficient_evidence', 'not_applicable']
    explanation: str
    evidence: list[Evidence]
    calculation: dict | None = None
    severity: str | None = None
    scope: Literal['submitted_verified_facts', 'not_evaluated', 'model_candidate']
    suggested_text: str | None = None


class DecisionView(DecisionCreate):
    actor: str
    actor_sub: str | None = None
    finding_id: str
    created_at: str


class RunView(Model):
    context_stale: bool = False
    execution_phases: dict | None = None
    recovery_count: int = 0
    final_verification: dict | None = None  # Historical runs only; new reviews do not grade drafts.
    analysis_artifacts: dict | None = None
    review_coverage: list[dict] | None = None
    case_guidance_snapshot: dict | None = None
    retrieval_snapshot: dict | None = None
    revision_proposals: list[dict] | None = None
    casebook_version: str | None = None
    module_errors: list[dict] | None = None
    diagnostics: dict | list | None = None
    result_schema_version: str | None = None
    material_bundle_id: str | None = None
    parent_run_id: str | None = None
    context_snapshot: dict | None = None
    rule_results: list[Finding] | None = None
    issues: list[Finding] | None = None
    attachment_checks: list[dict] | None = None
    review_facts_model: str | None = None
    review_implementation_sha256: str | None = None
    review_schema_sha256: str | None = None
    review_prompt_version: str | None = None
    review_prompt_sha256: str | None = None
    progress: str | None = None
    stage: str | None = None
    stage_updated_at: str | None = None
    started_at: str | None = None
    stage_history: list[dict] = Field(default_factory=list)
    model: str | None = None
    id: str
    contract_id: str
    document_version_id: str
    document_sha256: str
    created_at: str
    status: Literal['queued', 'running', 'completed', 'needs_input', 'failed']
    mode: Literal['development_verified_facts', 'model_review']
    rule_snapshot: dict
    request: RunCreate
    engine_version: str
    extraction_status: Literal['manual_verified', 'not_configured', 'pending', 'model_reviewed']
    coverage: Literal['submitted_facts_only', 'parsed_document_only', 'parsed_material_bundle']
    findings: list[Finding]
    error: dict | None = None
    finished_at: str | None = None
    stale: bool | None = None
    decisions: list[DecisionView] = Field(default_factory=list)


class ResultView(CompletionFields):
    reviewer: str
    reviewer_sub: str | None = None
    id: str
    run_id: str
    created_at: str
    document_version_id: str
    review_snapshot: RunView
    decisions: list[DecisionView]
    scope: Literal['human_record_of_partial_review_not_full_clearance', 'review_completion_record']


class ExtractionCreate(Model):
    document_version_id: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=100)
    model: Literal['DeepSeek-V4.1-Flash-1017', 'deepseek-flash', 'deepseek-v4-flash', 'glm-5.3-flash'] | None = None


class ExtractionView(Model):
    id: str
    document_version_id: str
    document_sha256: str
    model: str
    prompt_version: str
    status: Literal['running', 'needs_verification', 'failed']
    origin: Literal['model_extracted'] = 'model_extracted'
    created_at: str
    finished_at: str | None = None
    evidence_validation: Literal['not_checked', 'exact_quotes_verified'] = 'not_checked'
    facts: FactFields | None = None
    error: dict | None = None
    usage: dict | None = None
    input_sha256: str
    elapsed_seconds: float | None = None
    stale: bool = False
