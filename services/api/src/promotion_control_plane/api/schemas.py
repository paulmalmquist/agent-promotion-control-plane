from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MutationBase(BaseModel):
    expected_candidate_revision: int = Field(ge=1)


class PromoteRequest(MutationBase):
    actor: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=12, max_length=2000)


class RetryRequest(MutationBase):
    actor: str = Field(min_length=1, max_length=160)


class ApprovalRequest(MutationBase):
    actor: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=12, max_length=2000)
    target_stage: str = "PROMOTED"


class RevokeApprovalRequest(MutationBase):
    actor: str = Field(min_length=1, max_length=160)


class ActorRequest(BaseModel):
    actor: str = Field(default="demo-operator", min_length=1, max_length=160)


class EvaluateRequest(MutationBase):
    actor: str = Field(default="demo-operator", min_length=1, max_length=160)


class ScheduleTriggerRequest(BaseModel):
    actor: str = Field(default="external-scheduler", min_length=1, max_length=160)
    trigger_source: str = Field(default="API", min_length=1, max_length=80)
    payload: dict[str, Any] = {}


class ProblemDetails(BaseModel):
    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    correlation_id: UUID
    extensions: dict[str, Any] = {}


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class CandidateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    slug: str
    name: str
    summary: str
    candidate_type: str
    stage: str
    status: str
    revision: int
    proposed_capability: str
    confidence: float
    readiness_percentage: float
    current_policy_version: str | None
    discovered_at: datetime
    updated_at: datetime
    description: str | None = None
    surfaced_reason: str | None = None
    discovered_by: str | None = None
    discovery_source: str | None = None
    promotion_eligible: bool | None = None
    hard_gates_passed: int | None = None
    hard_gates_required: int | None = None
    weighted_score: float | None = None
    latest_evaluation_at: datetime | None = None
    lifecycle_approval_state: str | None = None
    blocker_summary: str | None = None
    blocker_titles: list[str] = Field(default_factory=list)


class CandidateListResponse(BaseModel):
    items: list[CandidateSummary]
    total: int


class BlockerView(BaseModel):
    id: UUID
    code: str
    category: str
    title: str
    explanation: str
    recovery: str
    details: dict[str, Any]
    created_at: datetime
    cleared_at: datetime | None


class ArtifactView(BaseModel):
    id: UUID
    candidate_id: UUID
    evaluation_run_id: UUID | None
    artifact_type: str
    uri: str
    sha256: str
    media_type: str
    sanitized: bool
    provider_metadata: dict[str, Any]
    created_at: datetime


class GateView(BaseModel):
    criterion_id: UUID
    criterion_key: str
    name: str
    category: str
    hard_gate: bool
    verdict: str
    comparison_operator: str
    threshold: float
    weight: float | None
    aggregation_rule: str
    measurement_value: float | None
    measurement_unit: str | None
    normalized_score: float | None
    sample_count: int
    minimum_samples: int
    evidence_codes: list[str]
    evaluator: str
    evaluator_version: str
    last_result_at: datetime | None


class ReadinessView(BaseModel):
    evaluation_readiness: float
    hard_gate_readiness: float
    weighted_score: float | None
    weighted_score_display: str
    weighted_readiness: float
    sample_completeness: float
    evaluation_completeness: float
    evaluation_evidence_eligible: bool
    promotion_eligible: bool
    registry_activation_state: str
    gate_verdicts: dict[str, str]
    required_weighted_score: float
    valid_result_count: int
    required_criterion_count: int


class PromotionEligibilityView(BaseModel):
    evidence_eligible: bool
    eligible: bool
    required_lifecycle_approvals: int
    available_lifecycle_approvals: int
    consumed_lifecycle_approvals: int = 0
    active_blocker_count: int = 0
    lifecycle_approval_state: str
    registry_activation_state: str


class EventView(BaseModel):
    id: UUID
    sequence: int
    event_type: str
    schema_version: int
    actor: str
    policy_hash: str | None
    correlation_id: UUID
    causation_id: UUID | None
    candidate_id: UUID | None
    evaluation_run_id: UUID | None
    scheduled_job_run_id: UUID | None
    registry_operation_id: UUID | None
    payload: dict[str, Any]
    occurred_at: datetime


class EventListResponse(BaseModel):
    items: list[EventView]
    next_after: int


class DecisionView(BaseModel):
    id: UUID
    decision_type: str | None = None
    outcome: str
    actor: str
    rationale: str
    policy_hash: str
    evaluation_snapshot_hash: str
    snapshot_hash: str
    snapshot: dict[str, Any] | None = None
    created_at: datetime


class RegistryOperationView(BaseModel):
    id: UUID
    candidate_id: UUID
    status: str
    activation_state: str
    publication_token: str
    attempt_count: int
    failure_code: str | None
    failure_message: str | None
    correlation_id: UUID
    created_at: datetime
    completed_at: datetime | None


class RegistryOperationListResponse(BaseModel):
    items: list[RegistryOperationView]
    total: int


class EvaluationResultView(BaseModel):
    id: UUID
    criterion_id: UUID
    measurement_type: str
    measurement_value: float
    measurement_unit: str | None
    normalized_score: float
    cost_usd: float | None = None
    latency_ms: float | None = None
    sample_count: int
    evidence_codes: list[str]
    valid: bool
    stale: bool
    provider: str | None = None
    model: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class SnapshotEvaluationResultView(BaseModel):
    id: UUID
    run_id: UUID
    criterion_id: UUID
    measurement_type: str
    measurement_value: float
    measurement_unit: str | None
    normalized_score: float
    cost_usd: float | None
    latency_ms: float | None
    sample_count: int
    valid: bool
    stale: bool
    evidence_codes: list[str]
    measurements: dict[str, Any]
    provider_metadata: dict[str, Any]
    created_at: datetime


class DetectorEvidenceView(BaseModel):
    id: UUID
    candidate_id: UUID | None = None
    signal_type: str
    score: float
    rank: int | None
    evidence: dict[str, Any]
    created_at: datetime


class CandidateDetail(CandidateSummary):
    detector_revision_id: UUID | None
    detector_lineage: dict[str, str | None]
    rationale: str
    policy_name: str | None
    policy_hash: str | None
    evaluation_snapshot_hash: str
    readiness: ReadinessView
    promotion_eligibility: PromotionEligibilityView
    blockers: list[BlockerView]
    gates: list[GateView]
    evaluation_results: list[SnapshotEvaluationResultView]
    evidence_artifacts: list[ArtifactView]
    detector_evidence: list[DetectorEvidenceView]
    timeline: list[EventView]
    decisions: list[DecisionView]
    latest_eligibility_decision: DecisionView | None
    registry_operation: RegistryOperationView | None


class ScheduleRunView(BaseModel):
    id: UUID
    status: str
    triggered_by: str
    trigger_source: str
    attempt_count: int
    started_at: datetime | None
    completed_at: datetime | None
    result: dict[str, Any] | None
    correlation_id: UUID


class ScheduleView(BaseModel):
    id: UUID
    key: str
    name: str
    description: str
    job_type: str
    enabled: bool
    trigger_owner: str
    trigger_mode: str
    owner_reference: str
    connection_state: str
    connection_message: str
    timezone: str
    schedule_expression: str
    last_observed_run_at: datetime | None
    next_expected_trigger_at: datetime | None
    grace_window_seconds: int
    run_count: int
    failure_count: int
    last_run_status: str | None
    current_activity: str | None
    last_duration_seconds: float | None
    history: list[ScheduleRunView]


class ScheduleSummaryView(BaseModel):
    id: UUID
    key: str
    name: str
    description: str
    job_type: str
    enabled: bool
    trigger_owner: str
    trigger_mode: str
    owner_reference: str
    connection_state: str
    connection_message: str
    timezone: str
    schedule_expression: str
    last_observed_run_at: datetime | None
    next_expected_trigger_at: datetime | None
    grace_window_seconds: int


class ScheduleListResponse(BaseModel):
    notice: str
    items: list[ScheduleView]
    total: int


class EvaluationRunView(BaseModel):
    id: UUID
    candidate_id: UUID
    plan_id: UUID
    status: str
    attempt_count: int
    max_attempts: int
    provider_names: list[str]
    planned_result_count: int
    result_count: int
    sample_count: int
    progress_percentage: float
    cost_usd: float
    latency_ms: float | None
    error: dict[str, Any] | None
    correlation_id: UUID
    heartbeat_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    artifacts: list[ArtifactView]
    results: list[EvaluationResultView] | None = None


class EvaluationListResponse(BaseModel):
    items: list[EvaluationRunView]


class RegistryVersionView(BaseModel):
    id: UUID
    candidate_id: UUID
    version: int
    external_version_id: str
    policy_hash: str
    evaluation_snapshot_hash: str
    publication_token: str
    promoted_at: datetime
    candidate_name: str | None = None
    candidate_slug: str | None = None
    stage: str | None = None
    status: str | None = None
    monitoring_state: str | None = None
    active: bool | None = None
    agent_id: UUID | None = None
    display_name: str | None = None
    registry_key: str | None = None
    is_active_version: bool | None = None


class RegistryVersionListResponse(BaseModel):
    items: list[RegistryVersionView]
    total: int


class RegistryAgentDetail(BaseModel):
    id: UUID
    candidate_id: UUID
    display_name: str
    registry_key: str
    active_version_id: UUID | None
    stage: str | None
    status: str | None
    monitoring_state: str
    health: str | None
    active: bool
    monitoring_run_count: int
    recent_monitoring_events: list[EventView]
    versions: list[RegistryVersionView]


class CriterionContractView(BaseModel):
    id: UUID
    policy_id: UUID
    key: str
    version: str
    name: str
    description: str
    proof_meaning: str
    category: str
    evaluator_type: str
    evaluator_key: str | None
    evaluator_version: str | None
    measurement_unit: str | None
    hard_gate: bool
    comparison_operator: str
    threshold: float
    weight: float | None
    minimum_samples: int
    required_evidence: list[str]
    aggregation_rule: str
    content_hash: str


class CriterionListResponse(BaseModel):
    items: list[CriterionContractView]
    total: int


class PolicyView(BaseModel):
    id: UUID
    key: str
    version: str
    name: str
    content_hash: str
    minimum_weighted_score: float
    required_lifecycle_approvals: int
    lifecycle_stages: list[str]
    criteria: list[CriterionContractView]


class PolicyListResponse(BaseModel):
    items: list[PolicyView]
    total: int


class DashboardCounts(BaseModel):
    stage: dict[str, int]
    status: dict[str, int]


class DashboardResponse(BaseModel):
    demo_mode: bool
    counts: DashboardCounts
    candidates: list[CandidateSummary]
    recent_events: list[EventView]
    jobs: list[ScheduleSummaryView]
    registry_versions: list[RegistryVersionView]
    generated_at: datetime


class PromotionAcceptedResponse(BaseModel):
    operation_id: UUID
    candidate_id: UUID
    candidate_revision: int
    correlation_id: UUID
    registry_activation_state: str
    stream_url: str


class EvaluationQueuedResponse(BaseModel):
    evaluation_run_id: UUID
    candidate_revision: int
    correlation_id: UUID


class PromotionCheckReadinessView(BaseModel):
    evaluation_readiness: float
    hard_gate_readiness: float
    weighted_score: float | None
    weighted_score_display: str
    weighted_readiness: float
    sample_completeness: float
    evaluation_completeness: float
    evaluation_evidence_eligible: bool
    promotion_eligible: bool
    registry_activation_state: str
    gate_verdicts: dict[str, str]


class PromotionCheckResponse(BaseModel):
    outcome: str
    candidate_revision: int
    readiness: PromotionCheckReadinessView
    correlation_id: UUID


class ApprovalCreatedResponse(BaseModel):
    approval_id: UUID
    candidate_revision: int
    locked: bool
    correlation_id: UUID


class ApprovalRevokedResponse(BaseModel):
    approval_id: UUID
    revoked: bool
    candidate_revision: int
    correlation_id: UUID


class ApprovalView(BaseModel):
    id: UUID
    candidate_id: UUID
    target_stage: str
    policy_hash: str
    evaluation_snapshot_hash: str
    decision_id: UUID
    actor: str
    rationale: str
    created_at: datetime
    revoked_at: datetime | None
    consumed_at: datetime | None


class ApprovalListResponse(BaseModel):
    items: list[ApprovalView]


class RegistryRetryAcceptedResponse(BaseModel):
    operation_id: UUID
    candidate_revision: int
    publication_token: str
    registry_activation_state: str
    correlation_id: UUID


class ScheduleTriggerResponse(BaseModel):
    job_run_id: UUID
    status: str
    correlation_id: UUID


class DemoResetResponse(BaseModel):
    status: str
    candidate_count: int
    correlation_id: UUID


class DemoCycleResponse(BaseModel):
    status: str
    job_run_ids: list[UUID]
    candidate_slug: str
    correlation_id: UUID
    stream_url: str


class EvidenceListResponse(BaseModel):
    items: list[ArtifactView]
    detector_evidence: list[DetectorEvidenceView]
