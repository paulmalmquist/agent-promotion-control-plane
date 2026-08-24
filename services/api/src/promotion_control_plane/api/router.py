from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from promotion_control_plane.api.dependencies import IdempotencyKey, SessionDependency
from promotion_control_plane.api.schemas import (
    ActorRequest,
    ApprovalCreatedResponse,
    ApprovalListResponse,
    ApprovalRequest,
    ApprovalRevokedResponse,
    CandidateDetail,
    CandidateListResponse,
    CriterionListResponse,
    DashboardResponse,
    DemoCycleResponse,
    DemoResetResponse,
    EvaluateRequest,
    EvaluationListResponse,
    EvaluationQueuedResponse,
    EvaluationRunView,
    EventListResponse,
    EvidenceListResponse,
    HealthResponse,
    PolicyListResponse,
    ProblemDetails,
    PromoteRequest,
    PromotionAcceptedResponse,
    PromotionCheckResponse,
    RegistryAgentDetail,
    RegistryOperationListResponse,
    RegistryOperationView,
    RegistryRetryAcceptedResponse,
    RegistryVersionListResponse,
    RetryRequest,
    RevokeApprovalRequest,
    ScheduleListResponse,
    ScheduleTriggerRequest,
    ScheduleTriggerResponse,
)
from promotion_control_plane.api.serialization import (
    artifact_view,
    blocker_view,
    candidate_summary,
    event_view,
    registry_operation_view,
    schedule_view,
    version_view,
)
from promotion_control_plane.api.sse import create_sse_router
from promotion_control_plane.application.demo import enqueue_demo_cycle
from promotion_control_plane.application.errors import conflict, not_found
from promotion_control_plane.application.events import emit_event
from promotion_control_plane.application.idempotency import prior_response, record_response
from promotion_control_plane.application.lifecycle import (
    DERIVED_EVALUATION_BLOCKER_CODES,
    require_evaluation_mutable,
    require_transition,
)
from promotion_control_plane.application.promotion import (
    create_lifecycle_approval,
    project_promotion_eligibility,
    queue_promotion,
    retry_registry_operation,
    revoke_lifecycle_approval,
)
from promotion_control_plane.application.readiness import (
    calculate_candidate_readiness,
    require_active_plan,
)
from promotion_control_plane.application.schedules import enqueue_schedule_trigger
from promotion_control_plane.application.snapshots import build_evaluation_snapshot
from promotion_control_plane.domain.hashing import content_hash
from promotion_control_plane.infrastructure.models import (
    AgentVersion,
    Blocker,
    Candidate,
    Criterion,
    Decision,
    DetectorEvidence,
    EvaluationPlan,
    EvaluationPlanItem,
    EvaluationResult,
    EvaluationRun,
    EvidenceArtifact,
    Policy,
    PromotedAgent,
    PromotionEvent,
    PromotionLifecycleApproval,
    RegistryOperation,
    ScheduledJob,
    ScheduledJobRun,
)
from promotion_control_plane.infrastructure.seed import reset_demo
from promotion_control_plane.settings import get_settings


@dataclass(frozen=True, slots=True)
class RouterServices:
    queue_promotion: Callable[..., Any] = queue_promotion
    retry_registry_operation: Callable[..., Any] = retry_registry_operation
    create_lifecycle_approval: Callable[..., Any] = create_lifecycle_approval
    revoke_lifecycle_approval: Callable[..., Any] = revoke_lifecycle_approval
    calculate_candidate_readiness: Callable[..., Any] = calculate_candidate_readiness
    require_active_plan: Callable[..., Any] = require_active_plan
    build_evaluation_snapshot: Callable[..., Any] = build_evaluation_snapshot
    reset_demo: Callable[..., Any] = reset_demo
    enqueue_demo_cycle: Callable[..., Any] = enqueue_demo_cycle


def _readiness_view(summary: Any, activation_state: str) -> dict[str, Any]:
    return {
        "evaluation_readiness": round(float(summary.readiness_percentage), 3),
        "hard_gate_readiness": float(summary.hard_gate_readiness * 100),
        "weighted_score": float(summary.weighted_score)
        if summary.weighted_score is not None
        else None,
        "weighted_score_display": (
            f"{summary.weighted_score:.1f}"
            if summary.weighted_score is not None
            else "Not required"
        ),
        "weighted_readiness": float(summary.weighted_readiness * 100),
        "sample_completeness": float(summary.sample_completeness * 100),
        "evaluation_completeness": float(summary.evaluation_completeness * 100),
        "evaluation_evidence_eligible": summary.promotion_evidence_eligible,
        "promotion_eligible": summary.promotion_evidence_eligible,
        "registry_activation_state": activation_state,
        "gate_verdicts": {key: verdict.value for key, verdict in summary.gate_verdicts.items()},
    }


def _operation_state(operation: RegistryOperation | None) -> str:
    if operation is None:
        return "NOT_REQUESTED"
    if operation.status in {"QUEUED", "RUNNING"}:
        return "PENDING"
    return "SUCCEEDED" if operation.status == "SUCCEEDED" else "FAILED"


def _candidate_list_view(session: Any, candidate: Candidate) -> dict[str, Any]:
    blockers = list(
        session.scalars(
            select(Blocker).where(
                Blocker.candidate_id == candidate.id, Blocker.cleared_at.is_(None)
            )
        )
    )
    summary = calculate_candidate_readiness(session, candidate.id)
    latest_evaluation_at = session.scalar(
        select(EvaluationRun.completed_at)
        .where(
            EvaluationRun.candidate_id == candidate.id,
            EvaluationRun.status == "SUCCEEDED",
        )
        .order_by(EvaluationRun.completed_at.desc())
        .limit(1)
    )
    eligibility = project_promotion_eligibility(
        session,
        candidate,
        evidence_eligible=summary.promotion_evidence_eligible,
    )
    return {
        **candidate_summary(candidate),
        "description": candidate.summary,
        "surfaced_reason": candidate.rationale,
        "discovered_by": candidate.discovered_by,
        "discovery_source": candidate.discovery_source,
        "promotion_eligible": eligibility.eligible,
        "hard_gates_passed": sum(
            verdict.value == "PASSED" for verdict in summary.gate_verdicts.values()
        ),
        "hard_gates_required": len(summary.gate_verdicts),
        "weighted_score": float(summary.weighted_score)
        if summary.weighted_score is not None
        else None,
        "latest_evaluation_at": (
            latest_evaluation_at.isoformat() if latest_evaluation_at else None
        ),
        "lifecycle_approval_state": eligibility.approval_state,
        "blocker_summary": blockers[0].title if blockers else None,
        "blocker_titles": [blocker.title for blocker in blockers],
    }


def _aggregate_result_value(results: list[dict[str, Any]], field: str, rule: str) -> Decimal | None:
    if not results:
        return None
    values = [Decimal(str(item[field])) for item in results]
    if rule == "sample_weighted_mean":
        samples = sum(int(item["sample_count"]) for item in results)
        if samples:
            return sum(
                Decimal(str(item[field])) * Decimal(int(item["sample_count"])) for item in results
            ) / Decimal(samples)
        return sum(values) / Decimal(len(values))
    if rule == "mean":
        return sum(values) / Decimal(len(values))
    if rule == "minimum":
        return min(values)
    return max(values)


def _gate_views(
    session: Any, evidence_snapshot: dict[str, Any], summary: Any
) -> list[dict[str, Any]]:
    active_plan = evidence_snapshot.get("active_plan")
    if not active_plan:
        return []
    items = active_plan["items"]
    criterion_ids = [UUID(item["criterion_id"]) for item in items]
    criteria_by_id = {
        criterion.id: criterion
        for criterion in session.scalars(select(Criterion).where(Criterion.id.in_(criterion_ids)))
    }
    results = evidence_snapshot["results"]
    views: list[dict[str, Any]] = []
    for plan_item in items:
        criterion_id = UUID(plan_item["criterion_id"])
        criterion = criteria_by_id[criterion_id]
        criterion_results = [item for item in results if UUID(item["criterion_id"]) == criterion_id]
        raw_value = _aggregate_result_value(
            criterion_results, "measurement_value", criterion.aggregation_rule
        )
        normalized_score = _aggregate_result_value(
            criterion_results, "normalized_score", criterion.aggregation_rule
        )
        views.append(
            {
                "criterion_id": str(criterion.id),
                "criterion_key": criterion.criterion_key,
                "name": criterion.name,
                "category": criterion.category,
                "hard_gate": criterion.hard_gate,
                "verdict": (
                    summary.gate_verdicts[criterion.criterion_key].value
                    if criterion.criterion_key in summary.gate_verdicts
                    else "NOT_APPLICABLE"
                ),
                "comparison_operator": criterion.comparison_operator,
                "threshold": float(criterion.threshold),
                "weight": float(criterion.weight) if criterion.weight is not None else None,
                "aggregation_rule": criterion.aggregation_rule,
                "measurement_value": float(raw_value) if raw_value is not None else None,
                "measurement_unit": (
                    criterion_results[-1]["measurement_unit"] if criterion_results else None
                ),
                "normalized_score": (
                    float(normalized_score) if normalized_score is not None else None
                ),
                "sample_count": sum(int(item["sample_count"]) for item in criterion_results),
                "minimum_samples": criterion.minimum_samples,
                "evidence_codes": sorted(
                    {code for item in criterion_results for code in item["evidence_codes"]}
                ),
                "evaluator": plan_item["evaluator_key"],
                "evaluator_version": plan_item["evaluator_version"],
                "last_result_at": max(
                    (item["created_at"] for item in criterion_results), default=None
                ),
            }
        )
    return views


def _evaluation_view(session: Any, run: EvaluationRun, *, include_results: bool) -> dict[str, Any]:
    results = list(
        session.scalars(
            select(EvaluationResult)
            .where(EvaluationResult.evaluation_run_id == run.id)
            .order_by(EvaluationResult.created_at, EvaluationResult.id)
        )
    )
    artifacts = list(
        session.scalars(
            select(EvidenceArtifact)
            .where(EvidenceArtifact.evaluation_run_id == run.id)
            .order_by(EvidenceArtifact.created_at, EvidenceArtifact.id)
        )
    )
    planned_count = (
        session.scalar(
            select(func.count(EvaluationPlanItem.id)).where(
                EvaluationPlanItem.plan_id == run.plan_id
            )
        )
        or 0
    )
    result_views = [
        {
            "id": str(item.id),
            "criterion_id": str(item.criterion_id),
            "measurement_type": item.measurement_type,
            "measurement_value": float(item.measurement_value),
            "measurement_unit": item.measurement_unit,
            "normalized_score": float(item.normalized_score),
            "cost_usd": float(item.cost_usd) if item.cost_usd is not None else None,
            "latency_ms": float(item.latency_ms) if item.latency_ms is not None else None,
            "sample_count": item.sample_count,
            "evidence_codes": item.evidence_codes,
            "valid": item.valid,
            "stale": item.stale,
            "provider": item.provider_metadata.get("provider"),
            "model": item.provider_metadata.get("model"),
            "provider_metadata": item.provider_metadata,
            "created_at": item.created_at.isoformat(),
        }
        for item in results
    ]
    view: dict[str, Any] = {
        "id": str(run.id),
        "candidate_id": str(run.candidate_id),
        "plan_id": str(run.plan_id),
        "status": run.status,
        "attempt_count": run.attempt_count,
        "max_attempts": run.max_attempts,
        "provider_names": sorted(
            {
                str(item.provider_metadata.get("provider"))
                for item in results
                if item.provider_metadata.get("provider")
            }
        ),
        "planned_result_count": planned_count,
        "result_count": len(results),
        "sample_count": sum(item.sample_count for item in results),
        "progress_percentage": 100.0 if planned_count == 0 else 100 * len(results) / planned_count,
        "cost_usd": float(sum((item.cost_usd or Decimal(0) for item in results), Decimal(0))),
        "latency_ms": max(
            (float(item.latency_ms) for item in results if item.latency_ms is not None),
            default=None,
        ),
        "error": run.error,
        "correlation_id": str(run.correlation_id),
        "heartbeat_at": run.heartbeat_at.isoformat() if run.heartbeat_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "artifacts": [artifact_view(item) for item in artifacts],
    }
    if include_results:
        view["results"] = result_views
    return view


def _criterion_contract_view(session: Any, criterion: Criterion) -> dict[str, Any]:
    plan_item = session.scalar(
        select(EvaluationPlanItem)
        .where(EvaluationPlanItem.criterion_id == criterion.id)
        .order_by(EvaluationPlanItem.id.desc())
        .limit(1)
    )
    latest_result = session.scalar(
        select(EvaluationResult)
        .where(EvaluationResult.criterion_id == criterion.id)
        .order_by(EvaluationResult.created_at.desc(), EvaluationResult.id.desc())
        .limit(1)
    )
    return {
        "id": str(criterion.id),
        "policy_id": str(criterion.policy_id),
        "key": criterion.criterion_key,
        "version": criterion.version,
        "name": criterion.name,
        "description": criterion.description,
        "proof_meaning": criterion.description,
        "category": criterion.category,
        "evaluator_type": criterion.evaluator_type,
        "evaluator_key": plan_item.evaluator_key if plan_item else None,
        "evaluator_version": plan_item.evaluator_version if plan_item else None,
        "measurement_unit": latest_result.measurement_unit if latest_result else None,
        "hard_gate": criterion.hard_gate,
        "comparison_operator": criterion.comparison_operator,
        "threshold": float(criterion.threshold),
        "weight": float(criterion.weight) if criterion.weight is not None else None,
        "minimum_samples": criterion.minimum_samples,
        "required_evidence": criterion.required_evidence,
        "aggregation_rule": criterion.aggregation_rule,
        "content_hash": criterion.content_hash,
    }


def create_router(
    *,
    services: RouterServices | None = None,
    dependency_overrides_provider: Any | None = None,
    event_session_factory: Callable[[], Any] | None = None,
    prefix: str = "/api/v1",
) -> APIRouter:
    """Create a reusable router with host-provided FastAPI dependency overrides."""
    service_set = services or RouterServices()
    problem_schema = ProblemDetails.model_json_schema()
    problem_responses: dict[int | str, dict[str, Any]] = {
        code: {
            "description": description,
            "content": {"application/problem+json": {"schema": problem_schema}},
        }
        for code, description in {
            400: "Invalid request",
            404: "Resource not found",
            409: "State or idempotency conflict",
            422: "Request cannot be completed",
            500: "Unexpected internal failure",
            503: "Database unavailable",
        }.items()
    }
    router = APIRouter(
        prefix=prefix,
        dependency_overrides_provider=dependency_overrides_provider,
        responses=problem_responses,
    )

    @router.get("/health", response_model=HealthResponse)
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "agent-promotion-control-plane", "version": "0.1.0"}

    @router.get("/dashboard", response_model=DashboardResponse)
    def dashboard(session: SessionDependency) -> dict[str, Any]:
        stage_counts: dict[str, int] = {
            stage: count
            for stage, count in session.execute(
                select(Candidate.stage, func.count()).group_by(Candidate.stage)
            )
        }
        status_counts: dict[str, int] = {
            candidate_status: count
            for candidate_status, count in session.execute(
                select(Candidate.status, func.count()).group_by(Candidate.status)
            )
        }
        events = list(
            session.scalars(
                select(PromotionEvent).order_by(PromotionEvent.sequence.desc()).limit(12)
            )
        )
        jobs = list(session.scalars(select(ScheduledJob).order_by(ScheduledJob.name)))
        versions = list(
            session.scalars(select(AgentVersion).order_by(AgentVersion.promoted_at.desc()).limit(8))
        )
        candidates = list(
            session.scalars(select(Candidate).order_by(Candidate.updated_at.desc()).limit(8))
        )
        return {
            "demo_mode": get_settings().demo_mode,
            "counts": {"stage": stage_counts, "status": status_counts},
            "candidates": [_candidate_list_view(session, candidate) for candidate in candidates],
            "recent_events": [event_view(event) for event in reversed(events)],
            "jobs": [schedule_view(job) for job in jobs],
            "registry_versions": [version_view(version) for version in versions],
            "generated_at": datetime.now(UTC).isoformat(),
        }

    @router.get("/candidates", response_model=CandidateListResponse)
    def candidates(
        session: SessionDependency,
        stage: str | None = None,
        candidate_status: str | None = Query(default=None, alias="status"),
    ) -> dict[str, Any]:
        statement = select(Candidate)
        if stage:
            statement = statement.where(Candidate.stage == stage)
        if candidate_status:
            statement = statement.where(Candidate.status == candidate_status)
        items = list(
            session.scalars(statement.order_by(Candidate.updated_at.desc(), Candidate.name))
        )
        return {
            "items": [_candidate_list_view(session, item) for item in items],
            "total": len(items),
        }

    @router.get("/candidates/{candidate_id}", response_model=CandidateDetail)
    def candidate_detail(candidate_id: UUID, session: SessionDependency) -> dict[str, Any]:
        candidate = session.get(Candidate, candidate_id)
        if candidate is None:
            raise not_found("Candidate")
        blockers = list(
            session.scalars(
                select(Blocker)
                .where(Blocker.candidate_id == candidate.id, Blocker.cleared_at.is_(None))
                .order_by(Blocker.created_at.desc())
            )
        )
        operation = session.scalar(
            select(RegistryOperation)
            .where(RegistryOperation.candidate_id == candidate.id)
            .order_by(RegistryOperation.created_at.desc())
            .limit(1)
        )
        evidence = list(
            session.scalars(
                select(DetectorEvidence)
                .where(DetectorEvidence.candidate_id == candidate.id)
                .order_by(DetectorEvidence.created_at.desc())
            )
        )
        artifacts = list(
            session.scalars(
                select(EvidenceArtifact)
                .where(EvidenceArtifact.candidate_id == candidate.id)
                .order_by(EvidenceArtifact.created_at.desc(), EvidenceArtifact.id)
            )
        )
        decisions = list(
            session.scalars(
                select(Decision)
                .where(Decision.candidate_id == candidate.id)
                .order_by(Decision.created_at.desc(), Decision.id)
            )
        )
        summary = service_set.calculate_candidate_readiness(session, candidate.id)
        evidence_snapshot, evidence_snapshot_hash = service_set.build_evaluation_snapshot(
            session, candidate.id
        )
        policy = (
            session.get(Policy, candidate.active_policy_id) if candidate.active_policy_id else None
        )
        events = list(
            session.scalars(
                select(PromotionEvent)
                .where(PromotionEvent.candidate_id == candidate.id)
                .order_by(PromotionEvent.sequence.desc())
                .limit(40)
            )
        )
        eligibility = project_promotion_eligibility(
            session,
            candidate,
            evidence_eligible=summary.promotion_evidence_eligible,
            evaluation_snapshot_hash=evidence_snapshot_hash,
        )
        readiness = _readiness_view(summary, _operation_state(operation))
        readiness.update(
            {
                "promotion_eligible": eligibility.eligible,
                "required_weighted_score": (
                    float(policy.minimum_weighted_score) if policy else 0.0
                ),
                "valid_result_count": sum(
                    item["valid"] and not item["stale"] for item in evidence_snapshot["results"]
                ),
                "required_criterion_count": len(evidence_snapshot["active_plan"]["items"])
                if evidence_snapshot["active_plan"]
                else 0,
            }
        )
        return {
            **candidate_summary(candidate),
            "description": candidate.summary,
            "surfaced_reason": candidate.rationale,
            "discovered_by": candidate.discovered_by,
            "discovery_source": candidate.discovery_source,
            "detector_revision_id": (
                str(candidate.detector_revision_id) if candidate.detector_revision_id else None
            ),
            "detector_lineage": {
                "discovered_by": candidate.discovered_by,
                "revision_id": (
                    str(candidate.detector_revision_id) if candidate.detector_revision_id else None
                ),
                "source": candidate.discovery_source,
            },
            "rationale": candidate.rationale,
            "policy_name": policy.name if policy else None,
            "policy_hash": policy.content_hash if policy else None,
            "evaluation_snapshot_hash": evidence_snapshot_hash,
            "readiness": readiness,
            "promotion_eligibility": {
                "evidence_eligible": eligibility.evidence_eligible,
                "eligible": eligibility.eligible,
                "required_lifecycle_approvals": eligibility.required_approvals,
                "available_lifecycle_approvals": eligibility.available_approvals,
                "consumed_lifecycle_approvals": eligibility.consumed_approvals,
                "active_blocker_count": eligibility.active_blocker_count,
                "lifecycle_approval_state": eligibility.approval_state,
                "registry_activation_state": eligibility.activation_state,
            },
            "lifecycle_approval_state": eligibility.approval_state,
            "blockers": [blocker_view(item) for item in blockers],
            "blocker_summary": blockers[0].title if blockers else None,
            "blocker_titles": [item.title for item in blockers],
            "gates": _gate_views(session, evidence_snapshot, summary),
            "evaluation_results": evidence_snapshot["results"],
            "evidence_artifacts": [artifact_view(item) for item in artifacts],
            "detector_evidence": [
                {
                    "id": str(item.id),
                    "signal_type": item.signal_type,
                    "score": float(item.score),
                    "rank": item.rank,
                    "evidence": item.evidence,
                    "created_at": item.created_at.isoformat(),
                }
                for item in evidence
            ],
            "timeline": [event_view(item) for item in reversed(events)],
            "decisions": [
                {
                    "id": str(item.id),
                    "decision_type": item.decision_type,
                    "outcome": item.outcome,
                    "actor": item.actor,
                    "rationale": item.rationale,
                    "policy_hash": item.policy_hash,
                    "evaluation_snapshot_hash": item.evaluation_snapshot_hash,
                    "snapshot_hash": item.snapshot_hash,
                    "snapshot": item.snapshot,
                    "created_at": item.created_at.isoformat(),
                }
                for item in decisions
            ],
            "latest_eligibility_decision": next(
                (
                    {
                        "id": str(item.id),
                        "outcome": item.outcome,
                        "actor": item.actor,
                        "rationale": item.rationale,
                        "policy_hash": item.policy_hash,
                        "evaluation_snapshot_hash": item.evaluation_snapshot_hash,
                        "snapshot_hash": item.snapshot_hash,
                        "created_at": item.created_at.isoformat(),
                    }
                    for item in decisions
                    if item.decision_type == "ELIGIBILITY"
                ),
                None,
            ),
            "registry_operation": registry_operation_view(operation) if operation else None,
        }

    @router.get("/candidates/{candidate_id}/timeline", response_model=EventListResponse)
    def candidate_timeline(
        candidate_id: UUID, session: SessionDependency, after: int = Query(default=0, ge=0)
    ) -> dict[str, Any]:
        events = list(
            session.scalars(
                select(PromotionEvent)
                .where(PromotionEvent.candidate_id == candidate_id, PromotionEvent.sequence > after)
                .order_by(PromotionEvent.sequence)
            )
        )
        return {
            "items": [event_view(event) for event in events],
            "next_after": events[-1].sequence if events else after,
        }

    @router.post(
        "/candidates/{candidate_id}/promote",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=PromotionAcceptedResponse,
    )
    def promote(
        candidate_id: UUID,
        body: PromoteRequest,
        session: SessionDependency,
        idempotency_key: IdempotencyKey,
    ) -> Response:
        request = body.model_dump(mode="json")
        scope = f"candidate:{candidate_id}:promote"
        prior = prior_response(session, scope, idempotency_key, request)
        if prior:
            return JSONResponse(prior[1], status_code=prior[0])
        correlation_id = uuid4()
        candidate, operation = service_set.queue_promotion(
            session,
            candidate_id,
            body.expected_candidate_revision,
            body.actor,
            body.rationale,
            correlation_id,
            max_attempts=get_settings().worker_max_attempts,
        )
        response = {
            "operation_id": str(operation.id),
            "candidate_id": str(candidate.id),
            "candidate_revision": candidate.revision,
            "correlation_id": str(correlation_id),
            "registry_activation_state": "PENDING",
            "stream_url": f"/api/v1/events/stream?candidate_id={candidate.id}",
        }
        record_response(session, scope, idempotency_key, request, 202, response, correlation_id)
        session.commit()
        return JSONResponse(response, status_code=202)

    @router.post(
        "/candidates/{candidate_id}/evaluate",
        status_code=status.HTTP_202_ACCEPTED,
        response_model=EvaluationQueuedResponse,
    )
    def evaluate_candidate(
        candidate_id: UUID,
        body: EvaluateRequest,
        session: SessionDependency,
        idempotency_key: IdempotencyKey,
    ) -> Response:
        request = body.model_dump(mode="json")
        scope = f"candidate:{candidate_id}:evaluate"
        prior = prior_response(session, scope, idempotency_key, request)
        if prior:
            return JSONResponse(prior[1], status_code=prior[0])
        candidate = session.scalar(
            select(Candidate).where(Candidate.id == candidate_id).with_for_update()
        )
        if candidate is None:
            raise not_found("Candidate")
        if candidate.revision != body.expected_candidate_revision:
            raise conflict(
                "STALE_CANDIDATE_REVISION", "The candidate changed. Reload it before evaluating."
            )
        require_evaluation_mutable(candidate)
        plan = session.scalar(
            select(EvaluationPlan)
            .where(EvaluationPlan.candidate_id == candidate.id, EvaluationPlan.active.is_(True))
            .order_by(EvaluationPlan.version.desc())
            .limit(1)
        )
        if plan is None:
            raise conflict(
                "EVALUATION_PLAN_REQUIRED", "Create an active evaluation plan before evaluating."
            )
        if plan.policy_id != candidate.active_policy_id:
            raise conflict(
                "ACTIVE_PLAN_POLICY_MISMATCH",
                "The active evaluation plan does not match the candidate's active policy.",
            )
        policy = session.get(Policy, plan.policy_id)
        if policy is None:
            raise conflict("POLICY_REQUIRED", "The active promotion policy is unavailable.")
        require_transition(candidate, policy, "EVALUATING")
        correlation_id = uuid4()
        run = EvaluationRun(
            plan_id=plan.id,
            candidate_id=candidate.id,
            status="QUEUED",
            request_idempotency_key=(
                f"api:{candidate.id}:{content_hash({'idempotency_key': idempotency_key})}"
            ),
            correlation_id=correlation_id,
            max_attempts=get_settings().worker_max_attempts,
        )
        session.add(run)
        session.flush()
        candidate.stage = "EVALUATING"
        candidate.status = "ACTIVE"
        candidate.revision += 1
        queued_event = emit_event(
            session,
            "EVALUATION_QUEUED",
            body.actor,
            correlation_id,
            candidate_id=candidate.id,
            evaluation_run_id=run.id,
            payload={
                "plan_id": str(plan.id),
                "stage": candidate.stage,
                "status": candidate.status,
                "candidate_revision": candidate.revision,
            },
        )
        run.causation_event_id = queued_event.id
        response = {
            "evaluation_run_id": str(run.id),
            "candidate_revision": candidate.revision,
            "correlation_id": str(correlation_id),
        }
        record_response(session, scope, idempotency_key, request, 202, response, correlation_id)
        session.commit()
        return JSONResponse(response, status_code=202)

    @router.post(
        "/candidates/{candidate_id}/promotion-check", response_model=PromotionCheckResponse
    )
    def promotion_check(
        candidate_id: UUID,
        body: EvaluateRequest,
        session: SessionDependency,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any] | Response:
        request = body.model_dump(mode="json")
        scope = f"candidate:{candidate_id}:promotion-check"
        prior = prior_response(session, scope, idempotency_key, request)
        if prior:
            return JSONResponse(prior[1], status_code=prior[0])
        candidate = session.scalar(
            select(Candidate).where(Candidate.id == candidate_id).with_for_update()
        )
        if candidate is None:
            raise not_found("Candidate")
        if candidate.revision != body.expected_candidate_revision:
            raise conflict(
                "STALE_CANDIDATE_REVISION", "The candidate changed. Reload it before checking."
            )
        require_evaluation_mutable(candidate)
        service_set.require_active_plan(session, candidate.id)
        summary = service_set.calculate_candidate_readiness(session, candidate.id)
        evidence_snapshot, evidence_snapshot_hash = service_set.build_evaluation_snapshot(
            session, candidate.id
        )
        policy = (
            session.get(Policy, candidate.active_policy_id) if candidate.active_policy_id else None
        )
        if policy is None:
            raise conflict("POLICY_REQUIRED", "The candidate has no active promotion policy.")
        target_stage = "ELIGIBLE" if summary.promotion_evidence_eligible else "EVALUATING"
        require_transition(candidate, policy, target_stage)
        candidate.readiness_percentage = summary.readiness_percentage
        candidate.current_evaluation_snapshot_hash = evidence_snapshot_hash
        candidate.stage = target_stage
        derived_blockers = list(
            session.scalars(
                select(Blocker).where(
                    Blocker.candidate_id == candidate.id,
                    Blocker.code.in_(DERIVED_EVALUATION_BLOCKER_CODES),
                    Blocker.cleared_at.is_(None),
                )
            )
        )
        cleared_at = datetime.now(UTC)
        for blocker in derived_blockers:
            blocker.cleared_at = cleared_at
            blocker.cleared_by = body.actor
        new_blocker: Blocker | None = None
        if not summary.promotion_evidence_eligible:
            hard_failed = any(
                verdict.value == "FAILED" for verdict in summary.gate_verdicts.values()
            )
            blocker_code = (
                "HARD_GATE_FAILED" if hard_failed else "EVALUATION_REQUIREMENTS_INCOMPLETE"
            )
            new_blocker = Blocker(
                candidate_id=candidate.id,
                code=blocker_code,
                category="SAFETY" if hard_failed else "EVIDENCE",
                title=(
                    "A required hard gate failed"
                    if hard_failed
                    else "Evaluation requirements remain incomplete"
                ),
                explanation=(
                    "A required gate failed. Weighted results cannot offset this stop."
                    if hard_failed
                    else "The active plan still lacks required samples, evidence, or results."
                ),
                recovery="Correct the requirement, then run the active evaluation plan again.",
                details={
                    "gate_verdicts": {
                        key: verdict.value for key, verdict in summary.gate_verdicts.items()
                    }
                },
            )
            session.add(new_blocker)
        session.flush()
        remaining_blockers = list(
            session.scalars(
                select(Blocker).where(
                    Blocker.candidate_id == candidate.id, Blocker.cleared_at.is_(None)
                )
            )
        )
        candidate.status = (
            "ACTIVE"
            if summary.promotion_evidence_eligible and not remaining_blockers
            else "BLOCKED"
        )
        candidate.revision += 1
        outcome = "ELIGIBLE" if summary.promotion_evidence_eligible else "BLOCKED"
        snapshot = {
            "candidate_id": str(candidate.id),
            "policy_hash": policy.content_hash,
            "evaluation_snapshot_hash": candidate.current_evaluation_snapshot_hash,
            "evaluation_snapshot": evidence_snapshot,
            "readiness": _readiness_view(summary, "NOT_REQUESTED"),
            "blockers": [
                {
                    "id": str(blocker.id),
                    "code": blocker.code,
                    "category": blocker.category,
                    "title": blocker.title,
                    "recovery": blocker.recovery,
                }
                for blocker in remaining_blockers
            ],
        }
        decision = Decision(
            candidate_id=candidate.id,
            decision_type="ELIGIBILITY",
            outcome=outcome,
            actor=body.actor,
            rationale="The gate engine recomputed the active evidence snapshot.",
            policy_hash=policy.content_hash,
            evaluation_snapshot_hash=candidate.current_evaluation_snapshot_hash or "",
            snapshot_hash=content_hash(snapshot),
            snapshot=snapshot,
        )
        session.add(decision)
        session.flush()
        correlation_id = uuid4()
        decision_causation_id: UUID | None = None
        for blocker in derived_blockers:
            cleared_event = emit_event(
                session,
                "BLOCKER_CLEARED",
                body.actor,
                correlation_id,
                candidate_id=candidate.id,
                policy_hash=policy.content_hash,
                causation_id=decision_causation_id,
                payload={
                    "code": blocker.code,
                    "stage": candidate.stage,
                    "status": candidate.status,
                    "candidate_revision": candidate.revision,
                },
            )
            decision_causation_id = cleared_event.id
        if new_blocker is not None:
            blocker_event = emit_event(
                session,
                "BLOCKER_ADDED",
                body.actor,
                correlation_id,
                candidate_id=candidate.id,
                policy_hash=policy.content_hash,
                causation_id=decision_causation_id,
                payload={
                    "code": new_blocker.code,
                    "stage": candidate.stage,
                    "status": candidate.status,
                    "candidate_revision": candidate.revision,
                },
            )
            decision_causation_id = blocker_event.id
        emit_event(
            session,
            "ELIGIBILITY_DECIDED",
            body.actor,
            correlation_id,
            candidate_id=candidate.id,
            policy_hash=policy.content_hash,
            causation_id=decision_causation_id,
            payload={
                "decision_id": str(decision.id),
                "outcome": outcome,
                "readiness_percentage": str(summary.readiness_percentage),
                "stage": candidate.stage,
                "status": candidate.status,
                "candidate_revision": candidate.revision,
            },
        )
        response = {
            "outcome": outcome,
            "candidate_revision": candidate.revision,
            "readiness": snapshot["readiness"],
            "correlation_id": str(correlation_id),
        }
        record_response(session, scope, idempotency_key, request, 200, response, correlation_id)
        session.commit()
        return response

    @router.post(
        "/candidates/{candidate_id}/approvals",
        status_code=201,
        response_model=ApprovalCreatedResponse,
    )
    def create_approval(
        candidate_id: UUID,
        body: ApprovalRequest,
        session: SessionDependency,
        idempotency_key: IdempotencyKey,
    ) -> Response:
        request = body.model_dump(mode="json")
        scope = f"candidate:{candidate_id}:lifecycle-approval"
        prior = prior_response(session, scope, idempotency_key, request)
        if prior:
            return JSONResponse(prior[1], status_code=prior[0])
        candidate = session.scalar(
            select(Candidate).where(Candidate.id == candidate_id).with_for_update()
        )
        if candidate is None:
            raise not_found("Candidate")
        if candidate.revision != body.expected_candidate_revision:
            raise conflict(
                "STALE_CANDIDATE_REVISION", "The candidate changed. Reload it before approving."
            )
        approval = service_set.create_lifecycle_approval(
            session, candidate_id, body.actor, body.rationale, body.target_stage
        )
        candidate.revision += 1
        correlation_id = uuid4()
        session.flush()
        emit_event(
            session,
            "PROMOTION_LIFECYCLE_APPROVAL_RECORDED",
            body.actor,
            correlation_id,
            candidate_id=candidate.id,
            policy_hash=approval.policy_hash,
            payload={
                "approval_id": str(approval.id),
                "target_stage": approval.target_stage,
                "stage": candidate.stage,
                "status": candidate.status,
                "candidate_revision": candidate.revision,
            },
        )
        response = {
            "approval_id": str(approval.id),
            "candidate_revision": candidate.revision,
            "locked": False,
            "correlation_id": str(correlation_id),
        }
        record_response(session, scope, idempotency_key, request, 201, response, correlation_id)
        session.commit()
        return JSONResponse(response, status_code=201)

    @router.delete("/approvals/{approval_id}", response_model=ApprovalRevokedResponse)
    def revoke_approval(
        approval_id: UUID,
        body: RevokeApprovalRequest,
        session: SessionDependency,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any] | Response:
        request = body.model_dump(mode="json")
        scope = f"approval:{approval_id}:revoke"
        prior = prior_response(session, scope, idempotency_key, request)
        if prior:
            return JSONResponse(prior[1], status_code=prior[0])
        approval = session.get(PromotionLifecycleApproval, approval_id)
        if approval is None:
            raise not_found("Promotion lifecycle approval")
        candidate = session.scalar(
            select(Candidate).where(Candidate.id == approval.candidate_id).with_for_update()
        )
        if candidate is None or candidate.revision != body.expected_candidate_revision:
            raise conflict(
                "STALE_CANDIDATE_REVISION", "The candidate changed. Reload it before revoking."
            )
        service_set.revoke_lifecycle_approval(session, approval_id, body.actor)
        candidate.revision += 1
        correlation_id = uuid4()
        emit_event(
            session,
            "PROMOTION_LIFECYCLE_APPROVAL_REVOKED",
            body.actor,
            correlation_id,
            candidate_id=candidate.id,
            policy_hash=approval.policy_hash,
            payload={
                "approval_id": str(approval.id),
                "stage": candidate.stage,
                "status": candidate.status,
                "candidate_revision": candidate.revision,
            },
        )
        response = {
            "approval_id": str(approval_id),
            "revoked": True,
            "candidate_revision": candidate.revision,
            "correlation_id": str(correlation_id),
        }
        record_response(session, scope, idempotency_key, request, 200, response, correlation_id)
        session.commit()
        return response

    @router.get("/approvals", response_model=ApprovalListResponse)
    def approvals(session: SessionDependency, candidate_id: UUID | None = None) -> dict[str, Any]:
        statement = select(PromotionLifecycleApproval)
        if candidate_id:
            statement = statement.where(PromotionLifecycleApproval.candidate_id == candidate_id)
        items = list(
            session.scalars(statement.order_by(PromotionLifecycleApproval.created_at.desc()))
        )
        return {
            "items": [
                {
                    "id": str(item.id),
                    "candidate_id": str(item.candidate_id),
                    "target_stage": item.target_stage,
                    "policy_hash": item.policy_hash,
                    "evaluation_snapshot_hash": item.evaluation_snapshot_hash,
                    "decision_id": str(item.decision_id),
                    "actor": item.actor,
                    "rationale": item.rationale,
                    "created_at": item.created_at.isoformat(),
                    "revoked_at": item.revoked_at.isoformat() if item.revoked_at else None,
                    "consumed_at": item.consumed_at.isoformat() if item.consumed_at else None,
                }
                for item in items
            ]
        }

    @router.post(
        "/promotion-operations/{operation_id}/retry",
        status_code=202,
        response_model=RegistryRetryAcceptedResponse,
    )
    def retry_operation(
        operation_id: UUID,
        body: RetryRequest,
        session: SessionDependency,
        idempotency_key: IdempotencyKey,
    ) -> Response:
        request = body.model_dump(mode="json")
        scope = f"registry-operation:{operation_id}:retry"
        prior = prior_response(session, scope, idempotency_key, request)
        if prior:
            return JSONResponse(prior[1], status_code=prior[0])
        correlation_id = uuid4()
        candidate, operation = service_set.retry_registry_operation(
            session, operation_id, body.expected_candidate_revision, body.actor, correlation_id
        )
        response = {
            "operation_id": str(operation.id),
            "candidate_revision": candidate.revision,
            "publication_token": operation.publication_token,
            "registry_activation_state": "PENDING",
            "correlation_id": str(correlation_id),
        }
        record_response(session, scope, idempotency_key, request, 202, response, correlation_id)
        session.commit()
        return JSONResponse(response, status_code=202)

    @router.get("/registry/operations", response_model=RegistryOperationListResponse)
    @router.get("/promotion-operations", response_model=RegistryOperationListResponse)
    def registry_operations(session: SessionDependency) -> dict[str, Any]:
        items = list(
            session.scalars(select(RegistryOperation).order_by(RegistryOperation.created_at.desc()))
        )
        return {"items": [registry_operation_view(item) for item in items], "total": len(items)}

    @router.get("/registry/operations/{operation_id}", response_model=RegistryOperationView)
    @router.get("/promotion-operations/{operation_id}", response_model=RegistryOperationView)
    def registry_operation(operation_id: UUID, session: SessionDependency) -> dict[str, Any]:
        operation = session.get(RegistryOperation, operation_id)
        if operation is None:
            raise not_found("Registry operation")
        return registry_operation_view(operation)

    @router.get("/registry/agents", response_model=RegistryVersionListResponse)
    def registry_agents(session: SessionDependency) -> dict[str, Any]:
        versions = list(
            session.scalars(select(AgentVersion).order_by(AgentVersion.promoted_at.desc()))
        )
        return {
            "items": [
                version_view(
                    item,
                    session.get(Candidate, item.candidate_id),
                    session.get(PromotedAgent, item.promoted_agent_id),
                )
                for item in versions
            ],
            "total": len(versions),
        }

    @router.get("/registry/agents/{agent_id}", response_model=RegistryAgentDetail)
    def registry_agent(agent_id: UUID, session: SessionDependency) -> dict[str, Any]:
        agent = session.get(PromotedAgent, agent_id)
        if agent is None:
            raise not_found("Promoted agent")
        candidate = session.get(Candidate, agent.candidate_id)
        versions = list(
            session.scalars(
                select(AgentVersion)
                .where(AgentVersion.promoted_agent_id == agent.id)
                .order_by(AgentVersion.version.desc())
            )
        )
        monitoring_events = list(
            session.scalars(
                select(PromotionEvent)
                .where(
                    PromotionEvent.candidate_id == agent.candidate_id,
                    PromotionEvent.event_type == "POST_PROMOTION_MONITORING_OBSERVED",
                )
                .order_by(PromotionEvent.sequence.desc())
                .limit(12)
            )
        )
        return {
            "id": str(agent.id),
            "candidate_id": str(agent.candidate_id),
            "display_name": agent.display_name,
            "registry_key": agent.registry_key,
            "active_version_id": str(agent.active_version_id) if agent.active_version_id else None,
            "stage": candidate.stage if candidate else None,
            "status": candidate.status if candidate else None,
            "monitoring_state": (
                "SUSPENDED"
                if candidate and candidate.status == "SUSPENDED"
                else "MONITORED"
                if candidate and candidate.stage == "MONITORED"
                else "AWAITING_MONITORING"
            ),
            "health": monitoring_events[0].payload.get("health") if monitoring_events else None,
            "active": bool(
                candidate
                and candidate.status == "ACTIVE"
                and candidate.stage in {"PROMOTED", "MONITORED"}
            ),
            "monitoring_run_count": session.scalar(
                select(func.count(PromotionEvent.sequence)).where(
                    PromotionEvent.candidate_id == agent.candidate_id,
                    PromotionEvent.event_type == "POST_PROMOTION_MONITORING_OBSERVED",
                )
            )
            or 0,
            "recent_monitoring_events": [event_view(item) for item in reversed(monitoring_events)],
            "versions": [version_view(item, candidate, agent) for item in versions],
        }

    @router.get("/events", response_model=EventListResponse)
    def events(
        session: SessionDependency,
        after: int = Query(default=0, ge=0),
        candidate_id: UUID | None = None,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        statement = select(PromotionEvent).where(PromotionEvent.sequence > after)
        if candidate_id:
            statement = statement.where(PromotionEvent.candidate_id == candidate_id)
        items = list(session.scalars(statement.order_by(PromotionEvent.sequence).limit(limit)))
        return {
            "items": [event_view(item) for item in items],
            "next_after": items[-1].sequence if items else after,
        }

    @router.get("/schedules", response_model=ScheduleListResponse)
    def schedules(session: SessionDependency) -> dict[str, Any]:
        items = list(session.scalars(select(ScheduledJob).order_by(ScheduledJob.name)))
        all_runs = list(
            session.scalars(
                select(ScheduledJobRun).order_by(
                    ScheduledJobRun.started_at.desc().nullslast(), ScheduledJobRun.id
                )
            )
        )
        runs_by_job: dict[UUID, list[ScheduledJobRun]] = {}
        for run in all_runs:
            runs_by_job.setdefault(run.job_id, []).append(run)

        def schedule_with_history(job: ScheduledJob) -> dict[str, Any]:
            runs = runs_by_job.get(job.id, [])
            latest = runs[0] if runs else None
            return {
                **schedule_view(job),
                "run_count": len(runs),
                "failure_count": sum(run.status == "FAILED" for run in runs),
                "last_run_status": latest.status if latest else None,
                "current_activity": next(
                    (run.status for run in runs if run.status in {"QUEUED", "RUNNING"}), None
                ),
                "last_duration_seconds": (
                    (latest.completed_at - latest.started_at).total_seconds()
                    if latest and latest.completed_at and latest.started_at
                    else None
                ),
                "history": [
                    {
                        "id": str(run.id),
                        "status": run.status,
                        "triggered_by": run.triggered_by,
                        "trigger_source": run.trigger_source,
                        "attempt_count": run.attempt_count,
                        "started_at": run.started_at.isoformat() if run.started_at else None,
                        "completed_at": (
                            run.completed_at.isoformat() if run.completed_at else None
                        ),
                        "result": run.result,
                        "correlation_id": str(run.correlation_id),
                    }
                    for run in runs[:6]
                ],
            }

        return {
            "notice": "This control plane does not execute cron. The demo command, CLI/API, or named external scheduler triggers each job.",
            "items": [schedule_with_history(item) for item in items],
            "total": len(items),
        }

    @router.post(
        "/schedules/{job_id}/trigger",
        status_code=202,
        response_model=ScheduleTriggerResponse,
    )
    def trigger_schedule(
        job_id: UUID,
        body: ScheduleTriggerRequest,
        session: SessionDependency,
        idempotency_key: IdempotencyKey,
    ) -> Response:
        job = session.get(ScheduledJob, job_id)
        if job is None:
            raise not_found("Scheduled job")
        response, _ = enqueue_schedule_trigger(
            session,
            job,
            idempotency_key=idempotency_key,
            actor=body.actor,
            trigger_source=body.trigger_source,
            payload=body.payload,
            max_attempts=get_settings().worker_max_attempts,
        )
        session.commit()
        return JSONResponse(response, status_code=202)

    @router.get("/policies", response_model=PolicyListResponse)
    def policies(session: SessionDependency) -> dict[str, Any]:
        items = list(session.scalars(select(Policy).order_by(Policy.policy_key, Policy.version)))
        return {
            "items": [
                {
                    "id": str(item.id),
                    "key": item.policy_key,
                    "version": item.version,
                    "name": item.name,
                    "content_hash": item.content_hash,
                    "minimum_weighted_score": float(item.minimum_weighted_score),
                    "required_lifecycle_approvals": item.required_lifecycle_approvals,
                    "lifecycle_stages": item.lifecycle_stages,
                    "criteria": [
                        _criterion_contract_view(session, criterion)
                        for criterion in session.scalars(
                            select(Criterion)
                            .where(Criterion.policy_id == item.id)
                            .order_by(Criterion.ordinal)
                        )
                    ],
                }
                for item in items
            ],
            "total": len(items),
        }

    @router.get("/criteria", response_model=CriterionListResponse)
    def criteria(session: SessionDependency, policy_id: UUID | None = None) -> dict[str, Any]:
        statement = select(Criterion)
        if policy_id:
            statement = statement.where(Criterion.policy_id == policy_id)
        items = list(session.scalars(statement.order_by(Criterion.ordinal)))
        return {
            "items": [_criterion_contract_view(session, item) for item in items],
            "total": len(items),
        }

    @router.get("/evaluations", response_model=EvaluationListResponse)
    def evaluations(session: SessionDependency, candidate_id: UUID | None = None) -> dict[str, Any]:
        statement = select(EvaluationRun)
        if candidate_id:
            statement = statement.where(EvaluationRun.candidate_id == candidate_id)
        runs = list(session.scalars(statement.order_by(EvaluationRun.available_at.desc())))
        return {"items": [_evaluation_view(session, run, include_results=False) for run in runs]}

    @router.get("/evaluations/{run_id}", response_model=EvaluationRunView)
    def evaluation_detail(run_id: UUID, session: SessionDependency) -> dict[str, Any]:
        run = session.get(EvaluationRun, run_id)
        if run is None:
            raise not_found("Evaluation run")
        return _evaluation_view(session, run, include_results=True)

    @router.get("/evidence", response_model=EvidenceListResponse)
    def evidence(session: SessionDependency, candidate_id: UUID | None = None) -> dict[str, Any]:
        statement = select(EvidenceArtifact)
        if candidate_id:
            statement = statement.where(EvidenceArtifact.candidate_id == candidate_id)
        items = list(session.scalars(statement.order_by(EvidenceArtifact.created_at.desc())))
        detector_statement = select(DetectorEvidence)
        if candidate_id:
            detector_statement = detector_statement.where(
                DetectorEvidence.candidate_id == candidate_id
            )
        detector_items = list(
            session.scalars(detector_statement.order_by(DetectorEvidence.created_at.desc()))
        )
        return {
            "items": [artifact_view(item) for item in items],
            "detector_evidence": [
                {
                    "id": str(item.id),
                    "candidate_id": str(item.candidate_id),
                    "signal_type": item.signal_type,
                    "score": float(item.score),
                    "rank": item.rank,
                    "evidence": item.evidence,
                    "created_at": item.created_at.isoformat(),
                }
                for item in detector_items
            ],
        }

    @router.post("/demo/reset", response_model=DemoResetResponse)
    def demo_reset(
        body: ActorRequest,
        session: SessionDependency,
        idempotency_key: IdempotencyKey,
    ) -> dict[str, Any]:
        if not get_settings().demo_mode:
            raise conflict("DEMO_MODE_DISABLED", "Demo reset is disabled in this environment.")
        request = body.model_dump(mode="json")
        prior = prior_response(session, "demo:reset", idempotency_key, request)
        if prior:
            return JSONResponse(prior[1], status_code=prior[0])  # type: ignore[return-value]
        correlation_id = uuid4()
        service_set.reset_demo(
            session,
            commit=False,
            actor=body.actor,
            correlation_id=correlation_id,
        )
        response = {"status": "RESET", "candidate_count": 8, "correlation_id": str(correlation_id)}
        record_response(
            session, "demo:reset", idempotency_key, request, 200, response, correlation_id
        )
        session.commit()
        return response

    @router.post("/demo/run-cycle", status_code=202, response_model=DemoCycleResponse)
    @router.post("/demo/cycle", status_code=202, response_model=DemoCycleResponse)
    def demo_cycle(
        body: ActorRequest,
        session: SessionDependency,
        idempotency_key: IdempotencyKey,
    ) -> Response:
        if not get_settings().demo_mode:
            raise conflict("DEMO_MODE_DISABLED", "Demo cycle is disabled in this environment.")
        request = body.model_dump(mode="json")
        prior = prior_response(session, "demo:run-cycle", idempotency_key, request)
        if prior:
            return JSONResponse(prior[1], status_code=prior[0])
        correlation_id = uuid4()
        runs = service_set.enqueue_demo_cycle(
            session, idempotency_key, body.actor, correlation_id=correlation_id
        )
        response = {
            "status": "QUEUED",
            "job_run_ids": [str(run.id) for run in runs],
            "candidate_slug": "change-risk-coordinator",
            "correlation_id": str(correlation_id),
            "stream_url": "/api/v1/events/stream",
        }
        record_response(
            session, "demo:run-cycle", idempotency_key, request, 202, response, correlation_id
        )
        session.commit()
        return JSONResponse(response, status_code=202)

    router.include_router(create_sse_router(session_factory=event_session_factory))
    return router
