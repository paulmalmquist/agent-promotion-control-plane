from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from promotion_control_plane.application.errors import conflict, not_found, unprocessable
from promotion_control_plane.application.events import emit_event
from promotion_control_plane.application.readiness import (
    active_plan_for_candidate,
    calculate_candidate_readiness,
    require_active_plan,
)
from promotion_control_plane.application.snapshots import build_evaluation_snapshot
from promotion_control_plane.domain.hashing import content_hash
from promotion_control_plane.infrastructure.models import (
    Blocker,
    Candidate,
    Decision,
    Policy,
    PromotionLifecycleApproval,
    RegistryOperation,
)


def _locked_candidate(session: Session, candidate_id: UUID) -> Candidate:
    candidate = session.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate is None:
        raise not_found("Candidate")
    return candidate


def _scheduled_job_run_id(candidate: Candidate) -> UUID | None:
    value = candidate.source_metadata.get("scheduled_job_run_id")
    return UUID(str(value)) if value else None


def _eligible_decision(session: Session, candidate: Candidate) -> Decision:
    decision = session.scalar(
        select(Decision)
        .where(
            Decision.candidate_id == candidate.id,
            Decision.decision_type == "ELIGIBILITY",
            Decision.outcome == "ELIGIBLE",
        )
        .order_by(Decision.created_at.desc())
        .limit(1)
    )
    if decision is None:
        raise unprocessable(
            "ELIGIBLE_DECISION_REQUIRED", "A current eligible decision is required."
        )
    if decision.evaluation_snapshot_hash != candidate.current_evaluation_snapshot_hash:
        raise conflict("STALE_DECISION", "Evaluation evidence changed after the eligible decision.")
    return decision


@dataclass(frozen=True, slots=True)
class PromotionEligibilityProjection:
    evidence_eligible: bool
    eligible: bool
    required_approvals: int
    available_approvals: int
    consumed_approvals: int
    approval_state: str
    active_blocker_count: int
    activation_state: str


def project_promotion_eligibility(
    session: Session,
    candidate: Candidate,
    *,
    evidence_eligible: bool | None = None,
    evaluation_snapshot_hash: str | None = None,
) -> PromotionEligibilityProjection:
    """Project the same exact snapshot, approval, blocker, and lease rules as promotion."""
    policy = session.get(Policy, candidate.active_policy_id) if candidate.active_policy_id else None
    required = policy.required_lifecycle_approvals if policy else 0
    plan = active_plan_for_candidate(session, candidate.id)
    if evidence_eligible is None:
        evidence_eligible = calculate_candidate_readiness(
            session, candidate.id
        ).promotion_evidence_eligible
    if evaluation_snapshot_hash is None:
        _, evaluation_snapshot_hash = build_evaluation_snapshot(session, candidate.id)
    decision = session.scalar(
        select(Decision)
        .where(
            Decision.candidate_id == candidate.id,
            Decision.decision_type == "ELIGIBILITY",
            Decision.outcome == "ELIGIBLE",
        )
        .order_by(Decision.created_at.desc(), Decision.id.desc())
        .limit(1)
    )
    snapshot_current = bool(
        policy
        and plan
        and plan.policy_id == policy.id
        and decision
        and decision.policy_hash == policy.content_hash
        and decision.evaluation_snapshot_hash == evaluation_snapshot_hash
        and candidate.current_evaluation_snapshot_hash == evaluation_snapshot_hash
    )
    approvals: list[PromotionLifecycleApproval] = []
    if snapshot_current and decision is not None and policy is not None:
        approvals = list(
            session.scalars(
                select(PromotionLifecycleApproval).where(
                    PromotionLifecycleApproval.candidate_id == candidate.id,
                    PromotionLifecycleApproval.target_stage == "PROMOTED",
                    PromotionLifecycleApproval.policy_hash == policy.content_hash,
                    PromotionLifecycleApproval.evaluation_snapshot_hash == evaluation_snapshot_hash,
                    PromotionLifecycleApproval.decision_id == decision.id,
                    PromotionLifecycleApproval.revoked_at.is_(None),
                )
            )
        )
    available = sum(item.consumed_at is None for item in approvals)
    consumed = sum(item.consumed_at is not None for item in approvals)
    approval_state = (
        "NOT_REQUIRED"
        if required == 0
        else "CONSUMED"
        if consumed >= required
        else "APPROVED"
        if available >= required
        else "REQUIRED"
    )
    blocker_count = int(
        session.scalar(
            select(func.count(Blocker.id)).where(
                Blocker.candidate_id == candidate.id, Blocker.cleared_at.is_(None)
            )
        )
        or 0
    )
    active_operation = session.scalar(
        select(RegistryOperation)
        .where(
            RegistryOperation.candidate_id == candidate.id,
            RegistryOperation.status.in_(["QUEUED", "RUNNING"]),
        )
        .order_by(RegistryOperation.created_at.desc())
        .limit(1)
    )
    activation_state = "PENDING" if active_operation is not None else "NOT_REQUESTED"
    latest_operation = active_operation or session.scalar(
        select(RegistryOperation)
        .where(RegistryOperation.candidate_id == candidate.id)
        .order_by(RegistryOperation.created_at.desc())
        .limit(1)
    )
    if active_operation is None and latest_operation is not None:
        activation_state = "SUCCEEDED" if latest_operation.status == "SUCCEEDED" else "FAILED"
    approval_satisfied = required == 0 or available >= required
    eligible = bool(
        evidence_eligible
        and snapshot_current
        and blocker_count == 0
        and candidate.stage in {"ELIGIBLE", "SHADOW"}
        and candidate.status != "PROMOTION_PENDING"
        and active_operation is None
        and approval_satisfied
    )
    return PromotionEligibilityProjection(
        evidence_eligible=bool(evidence_eligible and snapshot_current),
        eligible=eligible,
        required_approvals=required,
        available_approvals=available,
        consumed_approvals=consumed,
        approval_state=approval_state,
        active_blocker_count=blocker_count,
        activation_state=activation_state,
    )


def queue_promotion(
    session: Session,
    candidate_id: UUID,
    expected_revision: int,
    actor: str,
    rationale: str,
    correlation_id: UUID,
    causation_id: UUID | None = None,
    max_attempts: int = 3,
) -> tuple[Candidate, RegistryOperation]:
    candidate = _locked_candidate(session, candidate_id)
    if candidate.revision != expected_revision:
        raise conflict(
            "STALE_CANDIDATE_REVISION",
            "The candidate changed. Reload it before deciding.",
            expected_revision=expected_revision,
            current_revision=candidate.revision,
        )
    if candidate.stage not in {"ELIGIBLE", "SHADOW"}:
        raise unprocessable("CANDIDATE_NOT_ELIGIBLE", "Only an eligible candidate can be promoted.")
    if candidate.status == "PROMOTION_PENDING":
        raise conflict("PROMOTION_ALREADY_PENDING", "Registry activation is already pending.")
    active_operation = session.scalar(
        select(RegistryOperation)
        .where(
            RegistryOperation.candidate_id == candidate.id,
            RegistryOperation.status.in_(["QUEUED", "RUNNING"]),
        )
        .with_for_update()
        .limit(1)
    )
    if active_operation is not None:
        raise conflict(
            "PROMOTION_ALREADY_PENDING",
            "A registry publication already owns this candidate's activation slot.",
            operation_id=str(active_operation.id),
        )
    if candidate.active_policy_id is None:
        raise unprocessable("POLICY_REQUIRED", "The candidate has no active promotion policy.")
    policy = session.get(Policy, candidate.active_policy_id)
    if policy is None:
        raise unprocessable("POLICY_REQUIRED", "The active promotion policy is unavailable.")
    plan = require_active_plan(session, candidate.id)
    if plan.policy_id != policy.id:
        raise unprocessable(
            "ACTIVE_PLAN_POLICY_MISMATCH",
            "The active evaluation plan does not match the candidate's active policy.",
        )
    evaluation_snapshot, evaluation_snapshot_hash = build_evaluation_snapshot(session, candidate.id)
    eligible = _eligible_decision(session, candidate)
    if eligible.policy_hash != policy.content_hash:
        raise conflict("STALE_DECISION", "The policy changed after the eligible decision.")
    if (
        candidate.current_evaluation_snapshot_hash != evaluation_snapshot_hash
        or eligible.evaluation_snapshot_hash != evaluation_snapshot_hash
    ):
        raise conflict(
            "STALE_DECISION",
            "Evaluation results or evidence changed after the eligible decision.",
            expected_snapshot_hash=eligible.evaluation_snapshot_hash,
            current_snapshot_hash=evaluation_snapshot_hash,
        )
    active_blockers = session.scalar(
        select(Blocker.id)
        .where(Blocker.candidate_id == candidate.id, Blocker.cleared_at.is_(None))
        .limit(1)
    )
    if active_blockers is not None:
        raise unprocessable("ACTIVE_BLOCKERS", "Clear active blockers before promotion.")
    approvals = list(
        session.scalars(
            select(PromotionLifecycleApproval)
            .where(
                PromotionLifecycleApproval.candidate_id == candidate.id,
                PromotionLifecycleApproval.target_stage == "PROMOTED",
                PromotionLifecycleApproval.policy_hash == policy.content_hash,
                PromotionLifecycleApproval.evaluation_snapshot_hash
                == candidate.current_evaluation_snapshot_hash,
                PromotionLifecycleApproval.decision_id == eligible.id,
                PromotionLifecycleApproval.revoked_at.is_(None),
                PromotionLifecycleApproval.consumed_at.is_(None),
            )
            .order_by(PromotionLifecycleApproval.created_at)
            .with_for_update()
        )
    )
    if len(approvals) < policy.required_lifecycle_approvals:
        raise unprocessable(
            "LIFECYCLE_APPROVAL_REQUIRED",
            "The policy requires more promotion lifecycle approvals.",
            required=policy.required_lifecycle_approvals,
            available=len(approvals),
        )
    decision_snapshot = {
        "candidate_id": str(candidate.id),
        "candidate_revision": candidate.revision,
        "eligible_decision_id": str(eligible.id),
        "policy_hash": policy.content_hash,
        "evaluation_snapshot_hash": candidate.current_evaluation_snapshot_hash,
        "evaluation_snapshot": evaluation_snapshot,
        "approval_ids": [
            str(approval.id) for approval in approvals[: policy.required_lifecycle_approvals]
        ],
        "actor": actor,
        "rationale": rationale,
    }
    promotion_decision = Decision(
        candidate_id=candidate.id,
        decision_type="PROMOTION",
        outcome="APPROVED",
        actor=actor,
        rationale=rationale,
        policy_hash=policy.content_hash,
        evaluation_snapshot_hash=candidate.current_evaluation_snapshot_hash or "",
        snapshot_hash=content_hash(decision_snapshot),
        snapshot=decision_snapshot,
    )
    session.add(promotion_decision)
    session.flush()
    publication_token = content_hash(
        {"candidate_id": candidate.id, "eligible_decision_id": eligible.id, "target": "PROMOTED"}
    )
    operation = RegistryOperation(
        candidate_id=candidate.id,
        decision_id=promotion_decision.id,
        status="QUEUED",
        publication_token=publication_token,
        policy_hash=policy.content_hash,
        evaluation_snapshot_hash=candidate.current_evaluation_snapshot_hash or "",
        correlation_id=correlation_id,
        request_snapshot=decision_snapshot,
        max_attempts=max_attempts,
    )
    session.add(operation)
    session.flush()
    consumed_at = datetime.now(UTC)
    for approval in approvals[: policy.required_lifecycle_approvals]:
        approval.consumed_at = consumed_at
    candidate.stage = "ELIGIBLE"
    candidate.status = "PROMOTION_PENDING"
    candidate.revision += 1
    approved_event = emit_event(
        session,
        "PROMOTION_APPROVED",
        actor,
        correlation_id,
        candidate_id=candidate.id,
        policy_hash=policy.content_hash,
        registry_operation_id=operation.id,
        causation_id=causation_id,
        scheduled_job_run_id=_scheduled_job_run_id(candidate),
        payload={
            "decision_id": str(promotion_decision.id),
            "rationale": rationale,
            "stage": candidate.stage,
            "status": candidate.status,
            "candidate_revision": candidate.revision,
            "activation_state": "PENDING",
        },
    )
    queued_event = emit_event(
        session,
        "PROMOTION_REGISTRY_QUEUED",
        actor,
        correlation_id,
        candidate_id=candidate.id,
        policy_hash=policy.content_hash,
        causation_id=approved_event.id,
        registry_operation_id=operation.id,
        scheduled_job_run_id=_scheduled_job_run_id(candidate),
        payload={
            "activation_state": "PENDING",
            "stage": candidate.stage,
            "status": candidate.status,
            "candidate_revision": candidate.revision,
        },
    )
    operation.causation_event_id = queued_event.id
    return candidate, operation


def retry_registry_operation(
    session: Session,
    operation_id: UUID,
    expected_revision: int,
    actor: str,
    correlation_id: UUID,
) -> tuple[Candidate, RegistryOperation]:
    operation = session.scalar(
        select(RegistryOperation).where(RegistryOperation.id == operation_id).with_for_update()
    )
    if operation is None:
        raise not_found("Registry operation")
    candidate = _locked_candidate(session, operation.candidate_id)
    if candidate.revision != expected_revision:
        raise conflict(
            "STALE_CANDIDATE_REVISION", "The candidate changed. Reload it before retrying."
        )
    if operation.status != "FAILED":
        raise conflict(
            "REGISTRY_OPERATION_NOT_FAILED", "Only a failed registry operation can be retried."
        )
    if (
        candidate.current_evaluation_snapshot_hash != operation.evaluation_snapshot_hash
        or candidate.active_policy_id is None
    ):
        raise conflict(
            "STALE_PROMOTION_SNAPSHOT", "Policy or evaluation evidence changed after approval."
        )
    policy = session.get(Policy, candidate.active_policy_id)
    if policy is None or policy.content_hash != operation.policy_hash:
        raise conflict(
            "STALE_PROMOTION_SNAPSHOT", "Policy or evaluation evidence changed after approval."
        )
    plan = require_active_plan(session, candidate.id)
    if plan.policy_id != candidate.active_policy_id:
        raise conflict(
            "STALE_PROMOTION_SNAPSHOT", "The active plan no longer matches the approved policy."
        )
    evaluation_snapshot, evaluation_snapshot_hash = build_evaluation_snapshot(session, candidate.id)
    approved_snapshot = operation.request_snapshot.get("evaluation_snapshot")
    if (
        evaluation_snapshot_hash != operation.evaluation_snapshot_hash
        or evaluation_snapshot_hash != candidate.current_evaluation_snapshot_hash
        or approved_snapshot != evaluation_snapshot
    ):
        raise conflict(
            "STALE_PROMOTION_SNAPSHOT",
            "Evaluation results or evidence changed after approval.",
            approved_snapshot_hash=operation.evaluation_snapshot_hash,
            current_snapshot_hash=evaluation_snapshot_hash,
        )
    if candidate.stage != "ELIGIBLE" or candidate.status != "BLOCKED":
        raise conflict(
            "REGISTRY_RETRY_STATE_INVALID",
            "Registry retry requires an eligible candidate blocked by this failed operation.",
            stage=candidate.stage,
            status=candidate.status,
        )
    active_blockers = list(
        session.scalars(
            select(Blocker)
            .where(Blocker.candidate_id == candidate.id, Blocker.cleared_at.is_(None))
            .with_for_update()
        )
    )
    clearable_codes = {
        "REGISTRY_OPERATION_FAILED",
        "REGISTRY_RETRIES_EXHAUSTED",
        "REGISTRY_COMPLETION_STATE_MISMATCH",
    }

    def belongs_to_operation(blocker: Blocker) -> bool:
        linked_operation = blocker.details.get("operation_id") or blocker.details.get(
            "registry_operation_id"
        )
        return blocker.code in clearable_codes and str(linked_operation) == str(operation.id)

    unrelated_blockers = [
        blocker for blocker in active_blockers if not belongs_to_operation(blocker)
    ]
    if unrelated_blockers:
        raise conflict(
            "ACTIVE_BLOCKER_PREVENTS_REGISTRY_RETRY",
            "Clear every unrelated lifecycle, safety, and authorization blocker before retrying.",
            blocker_codes=sorted({blocker.code for blocker in unrelated_blockers}),
        )
    cleared_blockers = [blocker for blocker in active_blockers if belongs_to_operation(blocker)]
    operation.status = "QUEUED"
    operation.available_at = datetime.now(UTC)
    operation.lease_owner = None
    operation.lease_expires_at = None
    operation.failure_code = None
    operation.failure_message = None
    operation.attempt_count = 0
    operation.completed_at = None
    candidate.stage = "ELIGIBLE"
    candidate.status = "PROMOTION_PENDING"
    candidate.revision += 1
    for blocker in cleared_blockers:
        blocker.cleared_at = datetime.now(UTC)
        blocker.cleared_by = actor
    retry_event = emit_event(
        session,
        "PROMOTION_REGISTRY_RETRY_QUEUED",
        actor,
        correlation_id,
        candidate_id=candidate.id,
        policy_hash=operation.policy_hash,
        registry_operation_id=operation.id,
        scheduled_job_run_id=_scheduled_job_run_id(candidate),
        payload={
            "activation_state": "PENDING",
            "publication_token_reused": True,
            "stage": candidate.stage,
            "status": candidate.status,
            "candidate_revision": candidate.revision,
        },
    )
    operation.correlation_id = correlation_id
    operation.causation_event_id = retry_event.id
    for blocker in cleared_blockers:
        emit_event(
            session,
            "BLOCKER_CLEARED",
            actor,
            correlation_id,
            candidate_id=candidate.id,
            policy_hash=operation.policy_hash,
            causation_id=retry_event.id,
            registry_operation_id=operation.id,
            scheduled_job_run_id=_scheduled_job_run_id(candidate),
            payload={
                "code": blocker.code,
                "stage": candidate.stage,
                "status": candidate.status,
                "candidate_revision": candidate.revision,
            },
        )
    return candidate, operation


def create_lifecycle_approval(
    session: Session, candidate_id: UUID, actor: str, rationale: str, target_stage: str = "PROMOTED"
) -> PromotionLifecycleApproval:
    candidate = _locked_candidate(session, candidate_id)
    eligible = _eligible_decision(session, candidate)
    if candidate.active_policy_id is None:
        raise unprocessable("POLICY_REQUIRED", "The candidate has no active promotion policy.")
    policy = session.get(Policy, candidate.active_policy_id)
    if policy is None:
        raise unprocessable("POLICY_REQUIRED", "The active promotion policy is unavailable.")
    approval = PromotionLifecycleApproval(
        candidate_id=candidate.id,
        target_stage=target_stage,
        policy_hash=policy.content_hash,
        evaluation_snapshot_hash=candidate.current_evaluation_snapshot_hash or "",
        decision_id=eligible.id,
        actor=actor,
        rationale=rationale,
    )
    session.add(approval)
    return approval


def revoke_lifecycle_approval(
    session: Session, approval_id: UUID, actor: str
) -> PromotionLifecycleApproval:
    approval = session.scalar(
        select(PromotionLifecycleApproval)
        .where(PromotionLifecycleApproval.id == approval_id)
        .with_for_update()
    )
    if approval is None:
        raise not_found("Promotion lifecycle approval")
    if approval.consumed_at is not None:
        raise conflict(
            "APPROVAL_LOCKED",
            "Queued registry publication permanently locks this approval snapshot.",
        )
    if approval.revoked_at is not None:
        return approval
    approval.revoked_at = datetime.now(UTC)
    return approval
