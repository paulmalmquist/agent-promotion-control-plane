import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import Event, Thread
from time import sleep
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from promotion_control_plane.adapters.evaluators import (
    DeterministicRuleEvaluator,
    OpenAIRubricEvaluator,
    SyntheticMetricEvaluator,
    TestSuiteEvaluator,
)
from promotion_control_plane.adapters.protocols import (
    EvaluationSource,
    EvaluatorProvider,
    PromotionRegistry,
    RegistryPublication,
    TypedMeasurement,
)
from promotion_control_plane.application.events import emit_event
from promotion_control_plane.application.lifecycle import DERIVED_EVALUATION_BLOCKER_CODES
from promotion_control_plane.application.promotion import queue_promotion
from promotion_control_plane.application.readiness import calculate_candidate_readiness
from promotion_control_plane.application.schedules import next_expected_trigger
from promotion_control_plane.application.snapshots import build_evaluation_snapshot
from promotion_control_plane.domain.enums import GateVerdict
from promotion_control_plane.domain.hashing import content_hash
from promotion_control_plane.domain.lifecycle import validate_lifecycle_transition
from promotion_control_plane.infrastructure.models import (
    AgentVersion,
    Blocker,
    Candidate,
    Decision,
    EvaluationPlan,
    EvaluationPlanItem,
    EvaluationResult,
    EvaluationRun,
    EvidenceArtifact,
    Policy,
    PromotedAgent,
    RegistryOperation,
    ScheduledJob,
    ScheduledJobRun,
)
from promotion_control_plane.settings import get_settings


class RegistryTerminalError(RuntimeError):
    code = "REGISTRY_OPERATION_FAILED"


class DeterministicPromotionRegistry:
    """Credential-free registry that deterministically deduplicates publication tokens."""

    def publish(self, publication_token: str, snapshot: dict[str, Any]) -> RegistryPublication:
        if snapshot.get("simulate_terminal_failure"):
            raise RegistryTerminalError(
                "The deterministic registry rejected this demo publication."
            )
        return RegistryPublication(
            external_version_id=f"demo-{publication_token[:16]}",
            metadata={"provider": "deterministic-demo", "deduplicated_by": "publication_token"},
        )


def default_evaluator_providers() -> dict[str, EvaluatorProvider]:
    providers: list[EvaluatorProvider] = [
        DeterministicRuleEvaluator(),
        SyntheticMetricEvaluator(),
        TestSuiteEvaluator(
            {
                "promotion-control-plane-fixture-suite": (
                    sys.executable,
                    "-c",
                    "raise SystemExit(0)",
                )
            }
        ),
    ]
    if get_settings().openai_api_key:
        providers.append(OpenAIRubricEvaluator())
    return {provider.key: provider for provider in providers}


def _scheduled_job_run_id(candidate: Candidate) -> UUID | None:
    raw = candidate.source_metadata.get("scheduled_job_run_id")
    return UUID(str(raw)) if raw else None


class LeaseHeartbeat:
    def __init__(
        self,
        session_factory: Any,
        model: Any,
        work_id: UUID,
        worker_id: str,
        lease_seconds: int,
    ) -> None:
        self.session_factory = session_factory
        self.model = model
        self.work_id = work_id
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.stop_event = Event()
        self.thread = Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        interval = max(self.lease_seconds / 3, 0.1)
        while not self.stop_event.wait(interval):
            with self.session_factory() as session:
                work = session.get(self.model, self.work_id)
                if work is None or work.lease_owner != self.worker_id or work.status != "RUNNING":
                    return
                work.heartbeat_at = datetime.now(UTC)
                work.lease_expires_at = _lease_deadline(self.lease_seconds)
                session.commit()

    def __enter__(self) -> "LeaseHeartbeat":
        self.thread.start()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.stop_event.set()
        self.thread.join(timeout=2)


def _lease_deadline(seconds: int) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=seconds)


def _acquire_worker_claim_guard(session: Session) -> None:
    session.execute(
        text("SELECT pg_advisory_xact_lock_shared(:lock_id)"), {"lock_id": 8_104_250_001}
    )


def claim_registry_operation(
    session: Session, worker_id: str, lease_seconds: int
) -> RegistryOperation | None:
    _acquire_worker_claim_guard(session)
    now = datetime.now(UTC)
    operation = session.scalar(
        select(RegistryOperation)
        .where(
            RegistryOperation.status.in_(["QUEUED", "RUNNING"]),
            RegistryOperation.attempt_count < RegistryOperation.max_attempts,
            RegistryOperation.available_at <= now,
            or_(
                RegistryOperation.lease_expires_at.is_(None),
                RegistryOperation.lease_expires_at < now,
            ),
        )
        .order_by(RegistryOperation.available_at, RegistryOperation.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if operation is None:
        return None
    operation.status = "RUNNING"
    operation.lease_owner = worker_id
    operation.lease_expires_at = _lease_deadline(lease_seconds)
    operation.heartbeat_at = now
    operation.attempt_count += 1
    candidate = session.get(Candidate, operation.candidate_id)
    started = emit_event(
        session,
        "PROMOTION_REGISTRY_ATTEMPT_STARTED",
        worker_id,
        operation.correlation_id,
        candidate_id=operation.candidate_id,
        policy_hash=operation.policy_hash,
        causation_id=operation.causation_event_id,
        registry_operation_id=operation.id,
        scheduled_job_run_id=_scheduled_job_run_id(candidate) if candidate else None,
        payload={
            "attempt": operation.attempt_count,
            "max_attempts": operation.max_attempts,
            "activation_state": "PENDING",
            "stage": candidate.stage if candidate else None,
            "status": candidate.status if candidate else None,
            "candidate_revision": candidate.revision if candidate else None,
        },
    )
    operation.causation_event_id = started.id
    session.commit()
    return operation


def complete_registry_success(
    session: Session,
    operation_id: UUID,
    publication: RegistryPublication,
    worker_id: str,
) -> bool:
    operation = session.scalar(
        select(RegistryOperation).where(RegistryOperation.id == operation_id).with_for_update()
    )
    if operation is None:
        return False
    if operation.status == "SUCCEEDED":
        return True
    if operation.lease_owner != worker_id:
        return False
    candidate = session.scalar(
        select(Candidate).where(Candidate.id == operation.candidate_id).with_for_update()
    )
    if candidate is None:
        raise RuntimeError("Registry operation candidate disappeared")
    policy = session.get(Policy, candidate.active_policy_id) if candidate.active_policy_id else None
    state_matches = (
        candidate.stage == "ELIGIBLE"
        and candidate.status == "PROMOTION_PENDING"
        and policy is not None
        and policy.content_hash == operation.policy_hash
        and candidate.current_evaluation_snapshot_hash == operation.evaluation_snapshot_hash
    )
    try:
        if policy is not None:
            validate_lifecycle_transition(candidate.stage, "PROMOTED", policy.lifecycle_stages)
    except ValueError:
        state_matches = False
    if not state_matches:
        operation.status = "FAILED"
        operation.failure_code = "REGISTRY_COMPLETION_STATE_MISMATCH"
        operation.failure_message = (
            "Candidate lifecycle, policy, or evidence changed before registry completion."
        )
        operation.completed_at = datetime.now(UTC)
        operation.lease_owner = None
        operation.lease_expires_at = None
        if candidate.stage in {"ELIGIBLE", "SHADOW"}:
            candidate.stage = "ELIGIBLE"
        candidate.status = "BLOCKED"
        candidate.revision += 1
        blocker = session.scalar(
            select(Blocker).where(
                Blocker.candidate_id == candidate.id,
                Blocker.code == "REGISTRY_COMPLETION_STATE_MISMATCH",
                Blocker.cleared_at.is_(None),
            )
        )
        if blocker is None:
            blocker = Blocker(
                candidate_id=candidate.id,
                code="REGISTRY_COMPLETION_STATE_MISMATCH",
                category="ACTIVATION",
                title="Registry completion needs reconciliation",
                explanation="The registry succeeded after the approved local state changed.",
                recovery="Restore the approved snapshot, then retry with the same publication token.",
                details={
                    "operation_id": str(operation.id),
                    "external_version_id": publication.external_version_id,
                },
            )
            session.add(blocker)
        rejected = emit_event(
            session,
            "PROMOTION_REGISTRY_COMPLETION_REJECTED",
            worker_id,
            operation.correlation_id,
            candidate_id=candidate.id,
            policy_hash=operation.policy_hash,
            causation_id=operation.causation_event_id,
            scheduled_job_run_id=_scheduled_job_run_id(candidate),
            registry_operation_id=operation.id,
            payload={
                "code": operation.failure_code,
                "stage": candidate.stage,
                "status": candidate.status,
                "candidate_revision": candidate.revision,
                "external_version_id": publication.external_version_id,
            },
        )
        emit_event(
            session,
            "BLOCKER_ADDED",
            worker_id,
            operation.correlation_id,
            candidate_id=candidate.id,
            policy_hash=operation.policy_hash,
            causation_id=rejected.id,
            scheduled_job_run_id=_scheduled_job_run_id(candidate),
            registry_operation_id=operation.id,
            payload={
                "code": "REGISTRY_COMPLETION_STATE_MISMATCH",
                "stage": candidate.stage,
                "status": candidate.status,
                "candidate_revision": candidate.revision,
            },
        )
        session.commit()
        return False
    existing_version = session.scalar(
        select(AgentVersion).where(AgentVersion.publication_token == operation.publication_token)
    )
    agent = session.scalar(
        select(PromotedAgent).where(PromotedAgent.candidate_id == candidate.id).with_for_update()
    )
    if agent is None:
        agent = PromotedAgent(
            candidate_id=candidate.id,
            registry_key=candidate.slug,
            display_name=candidate.name,
        )
        session.add(agent)
        session.flush()
    if existing_version is None:
        version_number = (
            session.scalar(
                select(func.count(AgentVersion.id)).where(
                    AgentVersion.promoted_agent_id == agent.id
                )
            )
            or 0
        )
        existing_version = AgentVersion(
            promoted_agent_id=agent.id,
            candidate_id=candidate.id,
            registry_operation_id=operation.id,
            publication_token=operation.publication_token,
            version=version_number + 1,
            policy_hash=operation.policy_hash,
            evaluation_snapshot_hash=operation.evaluation_snapshot_hash,
            external_version_id=publication.external_version_id,
            snapshot={**operation.request_snapshot, "registry": publication.metadata},
        )
        session.add(existing_version)
        session.flush()
    agent.active_version_id = existing_version.id
    candidate.stage = "PROMOTED"
    candidate.status = "ACTIVE"
    candidate.revision += 1
    operation.status = "SUCCEEDED"
    operation.external_version_id = publication.external_version_id
    operation.completed_at = datetime.now(UTC)
    operation.lease_owner = None
    operation.lease_expires_at = None
    promoted_event = emit_event(
        session,
        "PROMOTED",
        worker_id,
        operation.correlation_id,
        candidate_id=candidate.id,
        policy_hash=operation.policy_hash,
        causation_id=operation.causation_event_id,
        registry_operation_id=operation.id,
        scheduled_job_run_id=_scheduled_job_run_id(candidate),
        payload={
            "activation_state": "SUCCEEDED",
            "agent_version_id": str(existing_version.id),
            "external_version_id": publication.external_version_id,
            "stage": candidate.stage,
            "status": candidate.status,
            "candidate_revision": candidate.revision,
        },
    )
    if candidate.source_metadata.get("autonomous_cycle"):
        assert policy is not None
        validate_lifecycle_transition(candidate.stage, "MONITORED", policy.lifecycle_stages)
        candidate.stage = "MONITORED"
        candidate.revision += 1
        emit_event(
            session,
            "POST_PROMOTION_MONITORING_OBSERVED",
            worker_id,
            operation.correlation_id,
            candidate_id=candidate.id,
            policy_hash=operation.policy_hash,
            causation_id=promoted_event.id,
            scheduled_job_run_id=_scheduled_job_run_id(candidate),
            registry_operation_id=operation.id,
            payload={
                "observation": "Deterministic post-promotion checks are nominal.",
                "health": "NOMINAL",
                "stage": candidate.stage,
                "status": candidate.status,
                "candidate_revision": candidate.revision,
                "activation_state": "SUCCEEDED",
            },
        )
    session.commit()
    return True


def complete_registry_failure(
    session: Session,
    operation_id: UUID,
    worker_id: str,
    error: Exception,
    terminal: bool,
) -> None:
    operation = session.scalar(
        select(RegistryOperation).where(RegistryOperation.id == operation_id).with_for_update()
    )
    if operation is None or operation.lease_owner != worker_id:
        return
    candidate = session.scalar(
        select(Candidate).where(Candidate.id == operation.candidate_id).with_for_update()
    )
    if candidate is None:
        return
    terminal = terminal or operation.attempt_count >= operation.max_attempts
    if terminal:
        operation.status = "FAILED"
        operation.failure_code = "REGISTRY_OPERATION_FAILED"
        operation.failure_message = str(error)
        operation.completed_at = datetime.now(UTC)
        candidate.stage = "ELIGIBLE"
        candidate.status = "BLOCKED"
        candidate.revision += 1
        existing = session.scalar(
            select(Blocker).where(
                Blocker.candidate_id == candidate.id,
                Blocker.code == "REGISTRY_OPERATION_FAILED",
                Blocker.cleared_at.is_(None),
            )
        )
        if existing is None:
            session.add(
                Blocker(
                    candidate_id=candidate.id,
                    code="REGISTRY_OPERATION_FAILED",
                    category="ACTIVATION",
                    title="Registry activation failed",
                    explanation="The tested version was not activated. Existing production selection did not change.",
                    recovery="Review the registry response, then retry while this evidence snapshot remains current.",
                    details={"operation_id": str(operation.id)},
                )
            )
        failed = emit_event(
            session,
            "PROMOTION_REGISTRY_FAILED",
            worker_id,
            operation.correlation_id,
            candidate_id=candidate.id,
            policy_hash=operation.policy_hash,
            causation_id=operation.causation_event_id,
            scheduled_job_run_id=_scheduled_job_run_id(candidate),
            registry_operation_id=operation.id,
            payload={
                "activation_state": "FAILED",
                "code": operation.failure_code,
                "stage": candidate.stage,
                "status": candidate.status,
                "candidate_revision": candidate.revision,
            },
        )
        emit_event(
            session,
            "BLOCKER_ADDED",
            worker_id,
            failed.correlation_id,
            candidate_id=candidate.id,
            policy_hash=operation.policy_hash,
            causation_id=failed.id,
            registry_operation_id=operation.id,
            payload={"code": "REGISTRY_OPERATION_FAILED"},
        )
    else:
        operation.status = "QUEUED"
        operation.available_at = datetime.now(UTC) + timedelta(seconds=2**operation.attempt_count)
        retry_event = emit_event(
            session,
            "PROMOTION_REGISTRY_RETRY_SCHEDULED",
            worker_id,
            operation.correlation_id,
            candidate_id=candidate.id,
            policy_hash=operation.policy_hash,
            causation_id=operation.causation_event_id,
            scheduled_job_run_id=_scheduled_job_run_id(candidate),
            registry_operation_id=operation.id,
            payload={
                "code": "REGISTRY_TRANSIENT_ERROR",
                "message": str(error),
                "attempt": operation.attempt_count,
                "max_attempts": operation.max_attempts,
                "retry_at": operation.available_at.isoformat(),
                "stage": candidate.stage,
                "status": candidate.status,
                "candidate_revision": candidate.revision,
            },
        )
        operation.causation_event_id = retry_event.id
    operation.lease_owner = None
    operation.lease_expires_at = None
    session.commit()


def process_registry_once(
    session_factory: Any,
    registry: PromotionRegistry,
    worker_id: str,
    lease_seconds: int,
) -> bool:
    with session_factory() as session:
        operation = claim_registry_operation(session, worker_id, lease_seconds)
    if operation is None:
        return False
    try:
        with LeaseHeartbeat(
            session_factory, RegistryOperation, operation.id, worker_id, lease_seconds
        ):
            publication = registry.publish(operation.publication_token, operation.request_snapshot)
    except Exception as error:
        with session_factory() as session:
            complete_registry_failure(
                session, operation.id, worker_id, error, isinstance(error, RegistryTerminalError)
            )
    else:
        with session_factory() as session:
            complete_registry_success(session, operation.id, publication, worker_id)
    return True


def claim_evaluation_run(
    session: Session, worker_id: str, lease_seconds: int
) -> EvaluationRun | None:
    _acquire_worker_claim_guard(session)
    now = datetime.now(UTC)
    run = session.scalar(
        select(EvaluationRun)
        .where(
            EvaluationRun.status.in_(["QUEUED", "RUNNING"]),
            EvaluationRun.attempt_count < EvaluationRun.max_attempts,
            EvaluationRun.available_at <= now,
            or_(EvaluationRun.lease_expires_at.is_(None), EvaluationRun.lease_expires_at < now),
        )
        .order_by(EvaluationRun.available_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if run is None:
        return None
    run.status = "RUNNING"
    run.lease_owner = worker_id
    run.lease_expires_at = _lease_deadline(lease_seconds)
    run.heartbeat_at = now
    run.started_at = run.started_at or now
    run.attempt_count += 1
    candidate = session.get(Candidate, run.candidate_id)
    started = emit_event(
        session,
        "EVALUATION_STARTED",
        worker_id,
        run.correlation_id,
        candidate_id=run.candidate_id,
        causation_id=run.causation_event_id,
        evaluation_run_id=run.id,
        scheduled_job_run_id=_scheduled_job_run_id(candidate) if candidate else None,
        payload={
            "attempt": run.attempt_count,
            "max_attempts": run.max_attempts,
            "stage": candidate.stage if candidate else None,
            "status": candidate.status if candidate else None,
            "candidate_revision": candidate.revision if candidate else None,
        },
    )
    run.causation_event_id = started.id
    session.commit()
    return run


def _complete_evaluation_failure(
    session: Session,
    run_id: UUID,
    worker_id: str,
    error: Exception,
) -> None:
    run = session.scalar(select(EvaluationRun).where(EvaluationRun.id == run_id).with_for_update())
    if run is None or run.lease_owner != worker_id:
        return
    candidate = session.scalar(
        select(Candidate).where(Candidate.id == run.candidate_id).with_for_update()
    )
    terminal = run.attempt_count >= run.max_attempts
    error_code = (
        "ACTIVE_PLAN_POLICY_MISMATCH"
        if "active plan" in str(error).lower()
        else "EVALUATION_PROVIDER_FAILED"
    )
    if terminal:
        run.status = "FAILED"
        run.completed_at = datetime.now(UTC)
        run.error = {"code": error_code, "message": str(error), "terminal": True}
        if candidate is not None:
            candidate.stage = "EVALUATING"
            candidate.status = "BLOCKED"
            candidate.revision += 1
            blocker = session.scalar(
                select(Blocker).where(
                    Blocker.candidate_id == candidate.id,
                    Blocker.code == error_code,
                    Blocker.cleared_at.is_(None),
                )
            )
            if blocker is None:
                session.add(
                    Blocker(
                        candidate_id=candidate.id,
                        code=error_code,
                        category="EVIDENCE",
                        title="Evaluation work could not complete",
                        explanation="The active evaluation did not produce a complete result.",
                        recovery="Correct the provider or plan configuration, then queue a new evaluation.",
                        details={"evaluation_run_id": str(run.id), "error": str(error)},
                    )
                )
            failed = emit_event(
                session,
                "EVALUATION_FAILED",
                worker_id,
                run.correlation_id,
                candidate_id=candidate.id,
                causation_id=run.causation_event_id,
                evaluation_run_id=run.id,
                scheduled_job_run_id=_scheduled_job_run_id(candidate),
                payload={
                    "code": error_code,
                    "terminal": True,
                    "stage": candidate.stage,
                    "status": candidate.status,
                    "candidate_revision": candidate.revision,
                },
            )
            emit_event(
                session,
                "BLOCKER_ADDED",
                worker_id,
                run.correlation_id,
                candidate_id=candidate.id,
                causation_id=failed.id,
                evaluation_run_id=run.id,
                scheduled_job_run_id=_scheduled_job_run_id(candidate),
                payload={
                    "code": error_code,
                    "stage": candidate.stage,
                    "status": candidate.status,
                    "candidate_revision": candidate.revision,
                },
            )
    else:
        run.status = "QUEUED"
        run.available_at = datetime.now(UTC) + timedelta(seconds=2**run.attempt_count)
        retry = emit_event(
            session,
            "EVALUATION_RETRY_SCHEDULED",
            worker_id,
            run.correlation_id,
            candidate_id=run.candidate_id,
            causation_id=run.causation_event_id,
            evaluation_run_id=run.id,
            scheduled_job_run_id=_scheduled_job_run_id(candidate) if candidate else None,
            payload={
                "code": error_code,
                "attempt": run.attempt_count,
                "max_attempts": run.max_attempts,
                "retry_at": run.available_at.isoformat(),
            },
        )
        run.causation_event_id = retry.id
    run.lease_owner = None
    run.lease_expires_at = None
    session.commit()


def process_evaluation_once(
    session_factory: Any,
    worker_id: str,
    lease_seconds: int,
    evaluator_providers: dict[str, EvaluatorProvider] | None = None,
    evaluation_source: EvaluationSource | None = None,
) -> bool:
    with session_factory() as session:
        claimed = claim_evaluation_run(session, worker_id, lease_seconds)
    if claimed is None:
        return False
    providers = evaluator_providers or default_evaluator_providers()
    try:
        with session_factory() as session:
            run = session.get(EvaluationRun, claimed.id)
            if run is None or run.lease_owner != worker_id:
                return False
            plan = session.get(EvaluationPlan, run.plan_id)
            candidate = session.get(Candidate, run.candidate_id)
            if (
                plan is None
                or candidate is None
                or not plan.active
                or plan.candidate_id != candidate.id
                or plan.policy_id != candidate.active_policy_id
            ):
                raise RuntimeError("The active plan does not match the candidate and policy.")
            items = list(
                session.scalars(
                    select(EvaluationPlanItem).where(EvaluationPlanItem.plan_id == run.plan_id)
                )
            )
        measurements: list[tuple[EvaluationPlanItem, TypedMeasurement]] = []
        with LeaseHeartbeat(session_factory, EvaluationRun, claimed.id, worker_id, lease_seconds):
            for item in items:
                provider = providers.get(item.evaluator_key)
                if provider is None:
                    raise RuntimeError(
                        f"Evaluator provider is not configured: {item.evaluator_key}"
                    )
                inputs = dict(item.configuration.get("inputs", {}))
                if evaluation_source is not None:
                    source_configuration = dict(item.configuration.get("source_configuration", {}))
                    if source_configuration:
                        inputs = evaluation_source.load(claimed.candidate_id, source_configuration)
                configuration = dict(item.configuration.get("evaluator_configuration", {}))
                measurements.append((item, provider.evaluate(inputs, configuration)))
    except Exception as error:
        with session_factory() as session:
            _complete_evaluation_failure(session, claimed.id, worker_id, error)
        return True

    with session_factory() as session:
        run = session.scalar(
            select(EvaluationRun).where(EvaluationRun.id == claimed.id).with_for_update()
        )
        if run is None or run.lease_owner != worker_id:
            return False
        plan = session.get(EvaluationPlan, run.plan_id)
        candidate = session.scalar(
            select(Candidate).where(Candidate.id == run.candidate_id).with_for_update()
        )
        if (
            plan is None
            or candidate is None
            or not plan.active
            or plan.candidate_id != candidate.id
            or plan.policy_id != candidate.active_policy_id
        ):
            _complete_evaluation_failure(
                session,
                run.id,
                worker_id,
                RuntimeError("The active plan changed during evaluation."),
            )
            return True
        policy = session.get(Policy, plan.policy_id)
        if (
            policy is None
            or candidate.stage != "EVALUATING"
            or candidate.status in {"PROMOTION_PENDING", "SUSPENDED", "RETIRED", "REJECTED"}
        ):
            run.status = "FAILED"
            run.completed_at = datetime.now(UTC)
            run.error = {
                "code": "EVALUATION_COMPLETION_STATE_MISMATCH",
                "stage": candidate.stage,
                "status": candidate.status,
            }
            run.lease_owner = None
            run.lease_expires_at = None
            emit_event(
                session,
                "EVALUATION_COMPLETION_REJECTED",
                worker_id,
                run.correlation_id,
                candidate_id=candidate.id,
                causation_id=run.causation_event_id,
                evaluation_run_id=run.id,
                scheduled_job_run_id=_scheduled_job_run_id(candidate),
                payload={
                    "code": "EVALUATION_COMPLETION_STATE_MISMATCH",
                    "stage": candidate.stage,
                    "status": candidate.status,
                    "candidate_revision": candidate.revision,
                },
            )
            session.commit()
            return True
        for item, measurement in measurements:
            value = (
                measurement.measurement_value
                if measurement.measurement_value is not None
                else measurement.normalized_score
            )
            session.add(
                EvaluationResult(
                    evaluation_run_id=run.id,
                    criterion_id=item.criterion_id,
                    measurement_type=measurement.measurement_type,
                    measurement_value=value,
                    measurement_unit=measurement.measurement_unit,
                    normalized_score=measurement.normalized_score,
                    cost_usd=(
                        Decimal(str(measurement.metadata["cost_usd"]))
                        if measurement.metadata.get("cost_usd") is not None
                        else None
                    ),
                    latency_ms=(
                        Decimal(str(measurement.metadata["latency_ms"]))
                        if measurement.metadata.get("latency_ms") is not None
                        else None
                    ),
                    sample_count=measurement.sample_count,
                    valid=True,
                    stale=False,
                    evidence_codes=list(measurement.evidence_codes),
                    measurements={"metric": measurement.metric, "value": str(value)},
                    provider_metadata={"provider": item.evaluator_key, **measurement.metadata},
                )
            )
            artifact_payload = measurement.metadata.get("sanitized_artifact")
            if isinstance(artifact_payload, dict):
                artifact_sha = content_hash(artifact_payload)
                session.add(
                    EvidenceArtifact(
                        candidate_id=candidate.id,
                        evaluation_run_id=run.id,
                        artifact_type="SANITIZED_EVALUATOR_RESPONSE",
                        uri=f"artifact://sha256/{artifact_sha}",
                        sha256=artifact_sha,
                        media_type="application/json",
                        sanitized=True,
                        metadata_snapshot={
                            "provider": item.evaluator_key,
                            "usage": measurement.metadata.get("usage", {}),
                        },
                    )
                )
            else:
                artifact_uri = measurement.metadata.get("sanitized_artifact_uri")
                stored_artifact_sha = measurement.metadata.get("sanitized_artifact_sha256")
                if isinstance(artifact_uri, str) and isinstance(stored_artifact_sha, str):
                    session.add(
                        EvidenceArtifact(
                            candidate_id=candidate.id,
                            evaluation_run_id=run.id,
                            artifact_type="SANITIZED_EVALUATOR_RESPONSE",
                            uri=artifact_uri,
                            sha256=stored_artifact_sha,
                            media_type="application/json",
                            sanitized=True,
                            metadata_snapshot={
                                "provider": item.evaluator_key,
                                "model": measurement.metadata.get("model"),
                                "usage": measurement.metadata.get("usage", {}),
                                "input_hash": measurement.metadata.get("input_hash"),
                                "rubric_hash": measurement.metadata.get("rubric_hash"),
                            },
                        )
                    )
        run.status = "SUCCEEDED"
        run.completed_at = datetime.now(UTC)
        run.lease_owner = None
        run.lease_expires_at = None
        session.flush()
        summary = calculate_candidate_readiness(session, candidate.id)
        candidate.readiness_percentage = summary.readiness_percentage
        evidence_snapshot, evidence_snapshot_hash = build_evaluation_snapshot(session, candidate.id)
        candidate.current_evaluation_snapshot_hash = evidence_snapshot_hash
        target_stage = "ELIGIBLE" if summary.promotion_evidence_eligible else "EVALUATING"
        validate_lifecycle_transition(candidate.stage, target_stage, policy.lifecycle_stages)
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
            blocker.cleared_by = worker_id
        session.flush()
        unrelated_blocker_exists = (
            session.scalar(
                select(Blocker.id)
                .where(Blocker.candidate_id == candidate.id, Blocker.cleared_at.is_(None))
                .limit(1)
            )
            is not None
        )
        candidate.status = (
            "ACTIVE"
            if summary.promotion_evidence_eligible and not unrelated_blocker_exists
            else "BLOCKED"
        )
        candidate.revision += 1
        completed_event = emit_event(
            session,
            "EVALUATION_COMPLETED",
            worker_id,
            run.correlation_id,
            candidate_id=candidate.id,
            policy_hash=policy.content_hash,
            causation_id=run.causation_event_id,
            evaluation_run_id=run.id,
            scheduled_job_run_id=_scheduled_job_run_id(candidate),
            payload={
                "readiness_percentage": str(summary.readiness_percentage),
                "stage": candidate.stage,
                "status": candidate.status,
                "candidate_revision": candidate.revision,
            },
        )
        run.causation_event_id = completed_event.id
        decision_causation_id = completed_event.id
        for blocker in derived_blockers:
            cleared_event = emit_event(
                session,
                "BLOCKER_CLEARED",
                worker_id,
                run.correlation_id,
                candidate_id=candidate.id,
                policy_hash=policy.content_hash,
                causation_id=decision_causation_id,
                evaluation_run_id=run.id,
                scheduled_job_run_id=_scheduled_job_run_id(candidate),
                payload={
                    "code": blocker.code,
                    "stage": candidate.stage,
                    "status": candidate.status,
                    "candidate_revision": candidate.revision,
                },
            )
            decision_causation_id = cleared_event.id
        if summary.promotion_evidence_eligible and candidate.active_policy_id is not None:
            if policy is not None:
                snapshot = {
                    "candidate_id": str(candidate.id),
                    "evaluation_run_id": str(run.id),
                    "policy_hash": policy.content_hash,
                    "evaluation_snapshot_hash": candidate.current_evaluation_snapshot_hash,
                    "evaluation_snapshot": evidence_snapshot,
                }
                decision = Decision(
                    id=UUID(content_hash({"eligibility_decision": snapshot})[:32]),
                    candidate_id=candidate.id,
                    decision_type="ELIGIBILITY",
                    outcome="ELIGIBLE",
                    actor=worker_id,
                    rationale="All active-plan requirements passed.",
                    policy_hash=policy.content_hash,
                    evaluation_snapshot_hash=candidate.current_evaluation_snapshot_hash,
                    snapshot_hash=content_hash(snapshot),
                    snapshot=snapshot,
                )
                session.add(decision)
                session.flush()
                eligibility_event = emit_event(
                    session,
                    "ELIGIBILITY_DECIDED",
                    worker_id,
                    run.correlation_id,
                    candidate_id=candidate.id,
                    policy_hash=policy.content_hash,
                    causation_id=decision_causation_id,
                    evaluation_run_id=run.id,
                    scheduled_job_run_id=_scheduled_job_run_id(candidate),
                    payload={
                        "decision_id": str(decision.id),
                        "outcome": "ELIGIBLE",
                        "readiness_percentage": str(summary.readiness_percentage),
                        "stage": candidate.stage,
                        "status": candidate.status,
                        "candidate_revision": candidate.revision,
                    },
                )
                if (
                    candidate.source_metadata.get("autonomous_cycle")
                    and candidate.status == "ACTIVE"
                ):
                    queue_promotion(
                        session,
                        candidate.id,
                        expected_revision=candidate.revision,
                        actor=worker_id,
                        rationale=(
                            "Activate this tested version after deterministic registry "
                            "publication succeeds."
                        ),
                        correlation_id=run.correlation_id,
                        causation_id=eligibility_event.id,
                        max_attempts=run.max_attempts,
                    )
        else:
            hard_failed = any(
                verdict == GateVerdict.FAILED for verdict in summary.gate_verdicts.values()
            )
            code = "HARD_GATE_FAILED" if hard_failed else "EVALUATION_REQUIREMENTS_INCOMPLETE"
            existing = session.scalar(
                select(Blocker).where(
                    Blocker.candidate_id == candidate.id,
                    Blocker.code == code,
                    Blocker.cleared_at.is_(None),
                )
            )
            blocker_event_id = completed_event.id
            if existing is None:
                session.add(
                    Blocker(
                        candidate_id=candidate.id,
                        code=code,
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
                        recovery=(
                            "Run the active evaluation plan again after correcting the requirement."
                        ),
                        details={
                            "gate_verdicts": {
                                key: value.value for key, value in summary.gate_verdicts.items()
                            }
                        },
                    )
                )
                blocker_event = emit_event(
                    session,
                    "BLOCKER_ADDED",
                    worker_id,
                    run.correlation_id,
                    candidate_id=candidate.id,
                    causation_id=decision_causation_id,
                    evaluation_run_id=run.id,
                    scheduled_job_run_id=_scheduled_job_run_id(candidate),
                    payload={
                        "code": code,
                        "stage": candidate.stage,
                        "status": candidate.status,
                        "candidate_revision": candidate.revision,
                    },
                )
                blocker_event_id = blocker_event.id
            emit_event(
                session,
                "ELIGIBILITY_DECIDED",
                worker_id,
                run.correlation_id,
                candidate_id=candidate.id,
                causation_id=blocker_event_id,
                evaluation_run_id=run.id,
                scheduled_job_run_id=_scheduled_job_run_id(candidate),
                payload={
                    "outcome": "BLOCKED",
                    "readiness_percentage": str(summary.readiness_percentage),
                    "stage": candidate.stage,
                    "status": candidate.status,
                    "candidate_revision": candidate.revision,
                },
            )
        session.commit()
    return True


def claim_schedule_run(
    session: Session, worker_id: str, lease_seconds: int
) -> ScheduledJobRun | None:
    _acquire_worker_claim_guard(session)
    now = datetime.now(UTC)
    run = session.scalar(
        select(ScheduledJobRun)
        .where(
            ScheduledJobRun.status.in_(["QUEUED", "RUNNING"]),
            ScheduledJobRun.attempt_count < ScheduledJobRun.max_attempts,
            ScheduledJobRun.available_at <= now,
            or_(ScheduledJobRun.lease_expires_at.is_(None), ScheduledJobRun.lease_expires_at < now),
        )
        .order_by(ScheduledJobRun.available_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if run is None:
        return None
    run.status = "RUNNING"
    run.lease_owner = worker_id
    run.lease_expires_at = _lease_deadline(lease_seconds)
    run.heartbeat_at = now
    run.started_at = now
    run.attempt_count += 1
    job = session.get(ScheduledJob, run.job_id)
    started = emit_event(
        session,
        "SCHEDULE_RUN_STARTED",
        worker_id,
        run.correlation_id,
        causation_id=run.causation_event_id,
        scheduled_job_run_id=run.id,
        payload={
            "job_key": job.job_key if job else None,
            "attempt": run.attempt_count,
            "max_attempts": run.max_attempts,
            "status": run.status,
        },
    )
    run.causation_event_id = started.id
    session.commit()
    return run


def process_schedule_once(session_factory: Any, worker_id: str, lease_seconds: int) -> bool:
    with session_factory() as session:
        claimed = claim_schedule_run(session, worker_id, lease_seconds)
    if claimed is None:
        return False
    try:
        with LeaseHeartbeat(session_factory, ScheduledJobRun, claimed.id, worker_id, lease_seconds):
            if claimed.payload.get("autonomous_cycle"):
                from promotion_control_plane.infrastructure.seed import advance_autonomous_cycle

                with session_factory() as work_session:
                    advance_autonomous_cycle(
                        work_session,
                        worker_id,
                        correlation_id=claimed.correlation_id,
                        causation_id=claimed.causation_event_id,
                        scheduled_job_run_id=claimed.id,
                        worker_max_attempts=claimed.max_attempts,
                    )
    except Exception as error:
        with session_factory() as session:
            run = session.scalar(
                select(ScheduledJobRun).where(ScheduledJobRun.id == claimed.id).with_for_update()
            )
            if run is None or run.lease_owner != worker_id:
                return True
            terminal = run.attempt_count >= run.max_attempts
            if terminal:
                run.status = "FAILED"
                run.completed_at = datetime.now(UTC)
                run.result = {
                    "code": "SCHEDULE_WORK_FAILED",
                    "message": str(error),
                    "terminal": True,
                }
                event_type = "SCHEDULE_RUN_FAILED"
            else:
                run.status = "QUEUED"
                run.available_at = datetime.now(UTC) + timedelta(seconds=2**run.attempt_count)
                run.result = {"code": "SCHEDULE_TRANSIENT_ERROR", "message": str(error)}
                event_type = "SCHEDULE_RUN_RETRY_SCHEDULED"
            failure_event = emit_event(
                session,
                event_type,
                worker_id,
                run.correlation_id,
                causation_id=run.causation_event_id,
                scheduled_job_run_id=run.id,
                payload={
                    "code": run.result["code"],
                    "attempt": run.attempt_count,
                    "max_attempts": run.max_attempts,
                    "status": run.status,
                },
            )
            run.causation_event_id = failure_event.id
            run.lease_owner = None
            run.lease_expires_at = None
            session.commit()
        return True

    with session_factory() as session:
        run = session.scalar(
            select(ScheduledJobRun).where(ScheduledJobRun.id == claimed.id).with_for_update()
        )
        if run is None or run.lease_owner != worker_id:
            return False
        job = session.get(ScheduledJob, run.job_id)
        if job is None:
            return False
        now = datetime.now(UTC)
        run.status = "SUCCEEDED"
        run.completed_at = now
        run.result = {"observed": True, "job_key": job.job_key}
        run.lease_owner = None
        run.lease_expires_at = None
        job.last_observed_run_at = now
        job.next_expected_trigger_at = next_expected_trigger(
            job.schedule_expression, job.timezone, now
        )
        observed = emit_event(
            session,
            "SCHEDULE_RUN_OBSERVED",
            worker_id,
            run.correlation_id,
            causation_id=run.causation_event_id,
            scheduled_job_run_id=run.id,
            payload={"job_key": job.job_key, "trigger_owner": job.trigger_owner},
        )
        run.causation_event_id = observed.id
        session.commit()
    return True


def touch_worker_heartbeat(path: Path) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(datetime.now(UTC).isoformat(), encoding="utf-8")
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            sleep(0.01)


def read_worker_heartbeat(
    path: Path, *, attempts: int = 5, retry_delay_seconds: float = 0.01
) -> datetime:
    """Read an atomic heartbeat while tolerating a brief Windows replace window."""
    if attempts < 1:
        raise ValueError("attempts must be at least one")
    last_error: OSError | ValueError | None = None
    for attempt in range(attempts):
        try:
            return datetime.fromisoformat(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as error:
            last_error = error
            if attempt + 1 < attempts:
                sleep(retry_delay_seconds)
    assert last_error is not None
    raise last_error


def dead_letter_exhausted_work(session_factory: Any, worker_id: str) -> int:
    now = datetime.now(UTC)
    changed = 0
    with session_factory() as session:
        _acquire_worker_claim_guard(session)
        evaluations = list(
            session.scalars(
                select(EvaluationRun)
                .where(
                    EvaluationRun.status.in_(["QUEUED", "RUNNING"]),
                    EvaluationRun.attempt_count >= EvaluationRun.max_attempts,
                    or_(
                        EvaluationRun.lease_expires_at.is_(None),
                        EvaluationRun.lease_expires_at < now,
                    ),
                )
                .with_for_update(skip_locked=True)
            )
        )
        for run in evaluations:
            run.status = "FAILED"
            run.completed_at = now
            run.error = {"code": "EVALUATION_RETRIES_EXHAUSTED", "attempts": run.attempt_count}
            run.lease_owner = None
            run.lease_expires_at = None
            candidate = session.scalar(
                select(Candidate).where(Candidate.id == run.candidate_id).with_for_update()
            )
            blocker_created = False
            if candidate is not None:
                candidate.stage = "EVALUATING"
                candidate.status = "BLOCKED"
                candidate.revision += 1
                existing_blocker = session.scalar(
                    select(Blocker).where(
                        Blocker.candidate_id == candidate.id,
                        Blocker.code == "EVALUATION_RETRIES_EXHAUSTED",
                        Blocker.cleared_at.is_(None),
                    )
                )
                if existing_blocker is None:
                    session.add(
                        Blocker(
                            candidate_id=candidate.id,
                            code="EVALUATION_RETRIES_EXHAUSTED",
                            category="EVIDENCE",
                            title="Evaluation retries ended",
                            explanation="The worker exhausted the policy's bounded evaluation attempts.",
                            recovery="Correct the provider failure, then queue a new evaluation run.",
                            details={"evaluation_run_id": str(run.id)},
                        )
                    )
                    blocker_created = True
            dead_lettered = emit_event(
                session,
                "EVALUATION_DEAD_LETTERED",
                worker_id,
                run.correlation_id,
                candidate_id=run.candidate_id,
                causation_id=run.causation_event_id,
                evaluation_run_id=run.id,
                scheduled_job_run_id=_scheduled_job_run_id(candidate) if candidate else None,
                payload={
                    "code": "EVALUATION_RETRIES_EXHAUSTED",
                    "stage": candidate.stage if candidate else None,
                    "status": candidate.status if candidate else None,
                    "candidate_revision": candidate.revision if candidate else None,
                },
            )
            if candidate is not None and blocker_created:
                emit_event(
                    session,
                    "BLOCKER_ADDED",
                    worker_id,
                    run.correlation_id,
                    candidate_id=candidate.id,
                    causation_id=dead_lettered.id,
                    evaluation_run_id=run.id,
                    scheduled_job_run_id=_scheduled_job_run_id(candidate),
                    payload={
                        "code": "EVALUATION_RETRIES_EXHAUSTED",
                        "stage": candidate.stage,
                        "status": candidate.status,
                        "candidate_revision": candidate.revision,
                    },
                )
            changed += 1
        schedules = list(
            session.scalars(
                select(ScheduledJobRun)
                .where(
                    ScheduledJobRun.status.in_(["QUEUED", "RUNNING"]),
                    ScheduledJobRun.attempt_count >= ScheduledJobRun.max_attempts,
                    or_(
                        ScheduledJobRun.lease_expires_at.is_(None),
                        ScheduledJobRun.lease_expires_at < now,
                    ),
                )
                .with_for_update(skip_locked=True)
            )
        )
        for run in schedules:
            run.status = "FAILED"
            run.completed_at = now
            run.result = {"code": "SCHEDULE_RETRIES_EXHAUSTED", "attempts": run.attempt_count}
            run.lease_owner = None
            run.lease_expires_at = None
            emit_event(
                session,
                "SCHEDULE_RUN_DEAD_LETTERED",
                worker_id,
                run.correlation_id,
                causation_id=run.causation_event_id,
                scheduled_job_run_id=run.id,
                payload={"code": "SCHEDULE_RETRIES_EXHAUSTED"},
            )
            changed += 1
        registry_operations = list(
            session.scalars(
                select(RegistryOperation)
                .where(
                    RegistryOperation.status.in_(["QUEUED", "RUNNING"]),
                    RegistryOperation.attempt_count >= RegistryOperation.max_attempts,
                    or_(
                        RegistryOperation.lease_expires_at.is_(None),
                        RegistryOperation.lease_expires_at < now,
                    ),
                )
                .with_for_update(skip_locked=True)
            )
        )
        for operation in registry_operations:
            candidate = session.scalar(
                select(Candidate).where(Candidate.id == operation.candidate_id).with_for_update()
            )
            operation.status = "FAILED"
            operation.failure_code = "REGISTRY_RETRIES_EXHAUSTED"
            operation.failure_message = "The worker exhausted bounded registry attempts."
            operation.completed_at = now
            operation.lease_owner = None
            operation.lease_expires_at = None
            blocker_created = False
            if candidate is not None:
                candidate.stage = "ELIGIBLE"
                candidate.status = "BLOCKED"
                candidate.revision += 1
                existing_blocker = session.scalar(
                    select(Blocker).where(
                        Blocker.candidate_id == candidate.id,
                        Blocker.code == "REGISTRY_RETRIES_EXHAUSTED",
                        Blocker.cleared_at.is_(None),
                    )
                )
                if existing_blocker is None:
                    session.add(
                        Blocker(
                            candidate_id=candidate.id,
                            code="REGISTRY_RETRIES_EXHAUSTED",
                            category="ACTIVATION",
                            title="Registry retries ended",
                            explanation="The worker exhausted the bounded registry publication attempts.",
                            recovery="Review registry availability, then explicitly retry this snapshot.",
                            details={"registry_operation_id": str(operation.id)},
                        )
                    )
                    blocker_created = True
            dead_lettered = emit_event(
                session,
                "PROMOTION_REGISTRY_DEAD_LETTERED",
                worker_id,
                operation.correlation_id,
                candidate_id=operation.candidate_id,
                causation_id=operation.causation_event_id,
                registry_operation_id=operation.id,
                payload={
                    "code": "REGISTRY_RETRIES_EXHAUSTED",
                    "stage": candidate.stage if candidate else None,
                    "status": candidate.status if candidate else None,
                    "candidate_revision": candidate.revision if candidate else None,
                },
            )
            if candidate is not None and blocker_created:
                emit_event(
                    session,
                    "BLOCKER_ADDED",
                    worker_id,
                    operation.correlation_id,
                    candidate_id=candidate.id,
                    causation_id=dead_lettered.id,
                    registry_operation_id=operation.id,
                    scheduled_job_run_id=_scheduled_job_run_id(candidate),
                    payload={
                        "code": "REGISTRY_RETRIES_EXHAUSTED",
                        "stage": candidate.stage,
                        "status": candidate.status,
                        "candidate_revision": candidate.revision,
                    },
                )
            changed += 1
        session.commit()
    return changed
