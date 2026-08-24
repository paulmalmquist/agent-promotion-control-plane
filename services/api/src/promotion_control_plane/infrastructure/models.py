from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Candidate(Base, TimestampMixin):
    __tablename__ = "candidates"
    __table_args__ = (
        Index("ix_candidates_stage_status", "stage", "status"),
        Index("ix_candidates_updated_at", "updated_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_type: Mapped[str] = mapped_column(
        String(80), nullable=False, default="AUTONOMOUS_AGENT"
    )
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    discovered_by: Mapped[str] = mapped_column(String(160), nullable=False, default="demo-detector")
    detector_revision_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("detector_revisions.id"), nullable=True
    )
    discovery_source: Mapped[str] = mapped_column(
        String(160), nullable=False, default="deterministic-signals"
    )
    proposed_capability: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False, default=Decimal("0"))
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="DISCOVERED")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="ACTIVE")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    active_policy_id: Mapped[UUID | None] = mapped_column(ForeignKey("policies.id"), nullable=True)
    current_policy_version: Mapped[str | None] = mapped_column(String(40))
    current_evaluation_snapshot_hash: Mapped[str | None] = mapped_column(String(64))
    readiness_percentage: Mapped[Decimal] = mapped_column(
        Numeric(6, 3), nullable=False, default=Decimal("0")
    )
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class CandidateComponent(Base):
    __tablename__ = "candidate_components"
    __table_args__ = (UniqueConstraint("candidate_id", "component_type", "version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    component_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DetectorRevision(Base):
    __tablename__ = "detector_revisions"
    __table_args__ = (UniqueConstraint("detector_key", "version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    detector_key: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvaluatorRevision(Base):
    __tablename__ = "evaluator_revisions"
    __table_args__ = (UniqueConstraint("evaluator_key", "version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    evaluator_key: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    evaluator_type: Mapped[str] = mapped_column(String(80), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DetectorRun(Base):
    __tablename__ = "detector_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    detector_revision_id: Mapped[UUID] = mapped_column(
        ForeignKey("detector_revisions.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signals_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class DetectorEvidence(Base):
    __tablename__ = "detector_evidence"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    detector_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("detector_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    signal_type: Mapped[str] = mapped_column(String(80), nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (UniqueConstraint("policy_key", "version"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    policy_key: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    minimum_weighted_score: Mapped[Decimal] = mapped_column(Numeric(6, 3), nullable=False)
    required_lifecycle_approvals: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lifecycle_stages: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Criterion(Base):
    __tablename__ = "criteria"
    __table_args__ = (UniqueConstraint("policy_id", "criterion_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("policies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    criterion_key: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False, default="1")
    category: Mapped[str] = mapped_column(String(80), nullable=False, default="quality")
    evaluator_type: Mapped[str] = mapped_column(
        String(120), nullable=False, default="deterministic-rule"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    hard_gate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    threshold: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    comparison_operator: Mapped[str] = mapped_column(String(8), nullable=False, default="gte")
    weight: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    minimum_samples: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    required_evidence: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    aggregation_rule: Mapped[str] = mapped_column(
        String(40), nullable=False, default="sample_weighted_mean"
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)


class PolicyAssignment(Base):
    __tablename__ = "policy_assignments"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    policy_id: Mapped[UUID] = mapped_column(ForeignKey("policies.id"), nullable=False, index=True)
    assigned_by: Mapped[str] = mapped_column(String(160), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationPlan(Base):
    __tablename__ = "evaluation_plans"
    __table_args__ = (
        UniqueConstraint("candidate_id", "version"),
        Index(
            "uq_evaluation_plans_one_active_candidate",
            "candidate_id",
            unique=True,
            postgresql_where=text("active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    policy_id: Mapped[UUID] = mapped_column(ForeignKey("policies.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvaluationPlanItem(Base):
    __tablename__ = "evaluation_plan_items"
    __table_args__ = (UniqueConstraint("plan_id", "criterion_id"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    criterion_id: Mapped[UUID] = mapped_column(ForeignKey("criteria.id"), nullable=False)
    evaluator_key: Mapped[str] = mapped_column(String(120), nullable=False)
    evaluator_version: Mapped[str] = mapped_column(String(40), nullable=False)
    evaluator_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        Index("ix_evaluation_runs_claim", "status", "available_at", "lease_expires_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    plan_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_plans.id"), nullable=False, index=True
    )
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="QUEUED")
    request_idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    causation_event_id: Mapped[UUID | None] = mapped_column(nullable=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    evaluation_run_id: Mapped[UUID] = mapped_column(
        ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    criterion_id: Mapped[UUID] = mapped_column(
        ForeignKey("criteria.id"), nullable=False, index=True
    )
    measurement_type: Mapped[str] = mapped_column(String(40), nullable=False, default="number")
    measurement_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    measurement_unit: Mapped[str | None] = mapped_column(String(40))
    normalized_score: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    latency_ms: Mapped[Decimal | None] = mapped_column(Numeric(18, 3))
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    measurements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    provider_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PromotionLifecycleApproval(Base):
    __tablename__ = "promotion_lifecycle_approvals"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    target_stage: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_id: Mapped[UUID] = mapped_column(ForeignKey("decisions.id"), nullable=False)
    actor: Mapped[str] = mapped_column(String(160), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Blocker(Base, TimestampMixin):
    __tablename__ = "blockers"
    __table_args__ = (Index("ix_blockers_active", "candidate_id", "cleared_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    recovery: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cleared_by: Mapped[str | None] = mapped_column(String(160))


class Decision(Base):
    __tablename__ = "decisions"
    __table_args__ = (Index("ix_decisions_candidate_created", "candidate_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    decision_type: Mapped[str] = mapped_column(String(40), nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(160), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PromotionEvent(Base):
    __tablename__ = "promotion_events"
    __table_args__ = (
        Index("ix_promotion_events_candidate_sequence", "candidate_id", "sequence"),
        Index("ix_promotion_events_correlation", "correlation_id"),
    )

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id: Mapped[UUID] = mapped_column(default=uuid4, unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    actor: Mapped[str] = mapped_column(String(160), nullable=False)
    policy_hash: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    causation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    candidate_id: Mapped[UUID | None] = mapped_column(nullable=True, index=True)
    evaluation_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    scheduled_job_run_id: Mapped[UUID | None] = mapped_column(nullable=True)
    registry_operation_id: Mapped[UUID | None] = mapped_column(nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ScheduledJob(Base, TimestampMixin):
    __tablename__ = "scheduled_jobs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_key: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    version: Mapped[str] = mapped_column(String(40), nullable=False, default="1.0.0")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False, default="OBSERVED_WORK")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    trigger_owner: Mapped[str] = mapped_column(String(160), nullable=False)
    trigger_mode: Mapped[str] = mapped_column(String(80), nullable=False)
    owner_reference: Mapped[str] = mapped_column(String(300), nullable=False)
    connection_state: Mapped[str] = mapped_column(String(40), nullable=False)
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="UTC")
    schedule_expression: Mapped[str] = mapped_column(String(120), nullable=False)
    last_observed_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_expected_trigger_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grace_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    metadata_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class ScheduledJobRun(Base):
    __tablename__ = "scheduled_job_runs"
    __table_args__ = (
        Index("ix_scheduled_job_runs_claim", "status", "available_at", "lease_expires_at"),
        UniqueConstraint("job_id", "trigger_idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("scheduled_jobs.id"), nullable=False, index=True
    )
    trigger_idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(160), nullable=False)
    trigger_source: Mapped[str] = mapped_column(String(80), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False, default=uuid4)
    causation_event_id: Mapped[UUID | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="QUEUED")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class EvidenceArtifact(Base):
    __tablename__ = "evidence_artifacts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    evaluation_run_id: Mapped[UUID | None] = mapped_column(ForeignKey("evaluation_runs.id"))
    artifact_type: Mapped[str] = mapped_column(String(80), nullable=False)
    uri: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    sanitized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RegistryOperation(Base, TimestampMixin):
    __tablename__ = "registry_operations"
    __table_args__ = (
        Index("ix_registry_operations_claim", "status", "available_at", "lease_expires_at"),
        Index(
            "uq_registry_operations_one_active_candidate",
            "candidate_id",
            unique=True,
            postgresql_where=text("status IN ('QUEUED', 'RUNNING')"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    decision_id: Mapped[UUID] = mapped_column(ForeignKey("decisions.id"), nullable=False)
    operation_type: Mapped[str] = mapped_column(String(40), nullable=False, default="PUBLISH")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="QUEUED")
    publication_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False)
    causation_event_id: Mapped[UUID | None] = mapped_column(nullable=True)
    request_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    lease_owner: Mapped[str | None] = mapped_column(String(160))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    failure_code: Mapped[str | None] = mapped_column(String(120))
    failure_message: Mapped[str | None] = mapped_column(Text)
    external_version_id: Mapped[str | None] = mapped_column(String(200))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PromotedAgent(Base, TimestampMixin):
    __tablename__ = "promoted_agents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, unique=True
    )
    registry_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    active_version_id: Mapped[UUID | None] = mapped_column(nullable=True)


class AgentVersion(Base):
    __tablename__ = "agent_versions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    promoted_agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("promoted_agents.id"), nullable=False, index=True
    )
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    registry_operation_id: Mapped[UUID] = mapped_column(
        ForeignKey("registry_operations.id"), nullable=False, unique=True
    )
    publication_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    external_version_id: Mapped[str] = mapped_column(String(200), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    promoted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExternalEventDelivery(Base, TimestampMixin):
    __tablename__ = "external_event_deliveries"
    __table_args__ = (UniqueConstraint("event_sequence", "sink_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    event_sequence: Mapped[int] = mapped_column(
        ForeignKey("promotion_events.sequence"), nullable=False, index=True
    )
    sink_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="QUEUED")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IdempotencyReceipt(Base):
    __tablename__ = "idempotency_receipts"
    __table_args__ = (UniqueConstraint("scope", "idempotency_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    scope: Mapped[str] = mapped_column(String(200), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
