import time
from datetime import UTC, datetime
from decimal import Decimal
from threading import Event, Thread
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from promotion_control_plane.adapters.protocols import RegistryPublication
from promotion_control_plane.api.app import create_app
from promotion_control_plane.application.demo import enqueue_demo_cycle
from promotion_control_plane.application.errors import ApplicationError
from promotion_control_plane.application.events import emit_event
from promotion_control_plane.application.promotion import (
    create_lifecycle_approval,
    project_promotion_eligibility,
    queue_promotion,
    retry_registry_operation,
)
from promotion_control_plane.application.readiness import calculate_candidate_readiness
from promotion_control_plane.domain.hashing import content_hash
from promotion_control_plane.domain.lifecycle import validate_lifecycle_transition
from promotion_control_plane.infrastructure.database import get_session_factory
from promotion_control_plane.infrastructure.models import (
    Blocker,
    Candidate,
    EvaluationPlan,
    EvaluationRun,
    EvidenceArtifact,
    Policy,
    PromotionEvent,
    RegistryOperation,
)
from promotion_control_plane.infrastructure.seed import advance_autonomous_cycle, seeded_uuid
from promotion_control_plane.settings import get_settings
from promotion_control_plane.worker.main import ProcessHealthHeartbeat
from promotion_control_plane.worker.service import (
    DeterministicPromotionRegistry,
    complete_registry_success,
    dead_letter_exhausted_work,
    default_evaluator_providers,
    process_evaluation_once,
    process_registry_once,
    process_schedule_once,
    read_worker_heartbeat,
)

pytestmark = pytest.mark.postgres


def test_missing_plan_cannot_become_eligible(db_session: Any) -> None:
    candidate = db_session.scalar(select(Candidate).where(Candidate.slug == "evidence-router"))
    assert candidate is not None
    candidate_id = candidate.id
    revision = candidate.revision
    assert calculate_candidate_readiness(db_session, candidate.id).readiness_percentage == 0
    db_session.close()

    response = TestClient(create_app()).post(
        f"/api/v1/candidates/{candidate_id}/promotion-check",
        headers={"Idempotency-Key": "missing-plan-check"},
        json={"expected_candidate_revision": revision, "actor": "safety-test"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "EVALUATION_PLAN_REQUIRED"
    with get_session_factory()() as session:
        unchanged = session.get(Candidate, candidate_id)
        assert unchanged is not None
        assert (unchanged.stage, unchanged.revision) == ("DISCOVERED", revision)


def test_empty_active_plan_uses_empty_set_semantics(db_session: Any) -> None:
    policy = Policy(
        policy_key="empty-contract",
        version="1.0.0",
        name="Empty contract",
        content_hash=content_hash({"policy": "empty-contract", "version": "1.0.0"}),
        minimum_weighted_score=Decimal(0),
        required_lifecycle_approvals=0,
        lifecycle_stages=["DISCOVERED", "EVALUATING", "ELIGIBLE", "PROMOTED"],
        configuration={},
    )
    db_session.add(policy)
    db_session.flush()
    candidate = Candidate(
        slug="empty-plan-candidate",
        name="Empty Plan Candidate",
        summary="Tests a genuinely empty active plan.",
        active_policy_id=policy.id,
        current_policy_version=policy.version,
    )
    db_session.add(candidate)
    db_session.flush()
    db_session.add(
        EvaluationPlan(
            candidate_id=candidate.id,
            policy_id=policy.id,
            version=1,
            content_hash=content_hash({"candidate": str(candidate.id), "items": []}),
            active=True,
            snapshot={"items": []},
        )
    )
    db_session.flush()
    summary = calculate_candidate_readiness(db_session, candidate.id)
    assert summary.readiness_percentage == Decimal(100)
    assert summary.promotion_evidence_eligible


def test_policy_mismatched_plan_is_rejected(db_session: Any) -> None:
    candidate = db_session.scalar(select(Candidate).where(Candidate.slug == "renewal-briefing"))
    assert candidate is not None
    plan = db_session.scalar(
        select(EvaluationPlan).where(EvaluationPlan.candidate_id == candidate.id)
    )
    assert plan is not None
    other_policy = Policy(
        policy_key="adversarial-policy",
        version="1.0.0",
        name="Adversarial policy",
        content_hash=content_hash({"policy": "adversarial"}),
        minimum_weighted_score=Decimal(0),
        required_lifecycle_approvals=0,
        lifecycle_stages=["DISCOVERED", "EVALUATING", "ELIGIBLE", "PROMOTED"],
        configuration={},
    )
    db_session.add(other_policy)
    db_session.flush()
    plan.policy_id = other_policy.id
    candidate_id = candidate.id
    revision = candidate.revision
    db_session.commit()
    response = TestClient(create_app()).post(
        f"/api/v1/candidates/{candidate_id}/promotion-check",
        headers={"Idempotency-Key": "mismatched-plan"},
        json={"expected_candidate_revision": revision, "actor": "safety-test"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "ACTIVE_PLAN_POLICY_MISMATCH"


def test_queue_and_retry_recompute_exact_snapshot(db_session: Any) -> None:
    candidate = db_session.scalar(select(Candidate).where(Candidate.slug == "renewal-briefing"))
    assert candidate is not None
    db_session.add(
        EvidenceArtifact(
            candidate_id=candidate.id,
            artifact_type="LATE_EVIDENCE",
            uri="demo://late-evidence.json",
            sha256=content_hash({"late": True}),
            media_type="application/json",
            sanitized=True,
            metadata_snapshot={},
        )
    )
    db_session.flush()
    with pytest.raises(ApplicationError) as stale_queue:
        queue_promotion(
            db_session,
            candidate.id,
            candidate.revision,
            "reviewer",
            "Queue the exact tested snapshot.",
            uuid4(),
        )
    assert stale_queue.value.code == "STALE_DECISION"
    db_session.rollback()

    candidate = db_session.scalar(select(Candidate).where(Candidate.slug == "renewal-briefing"))
    assert candidate is not None
    _, operation = queue_promotion(
        db_session,
        candidate.id,
        candidate.revision,
        "reviewer",
        "Queue a controlled terminal registry failure.",
        uuid4(),
    )
    operation.request_snapshot = {**operation.request_snapshot, "simulate_terminal_failure": True}
    db_session.commit()
    process_registry_once(
        get_session_factory(), DeterministicPromotionRegistry(), "snapshot-worker", 30
    )
    db_session.expire_all()
    operation = db_session.get(RegistryOperation, operation.id)
    candidate = db_session.get(Candidate, candidate.id)
    assert operation is not None and candidate is not None
    db_session.add(
        EvidenceArtifact(
            candidate_id=candidate.id,
            artifact_type="POST_APPROVAL_EVIDENCE",
            uri="demo://post-approval.json",
            sha256=content_hash({"post_approval": True}),
            media_type="application/json",
            sanitized=True,
            metadata_snapshot={},
        )
    )
    db_session.flush()
    with pytest.raises(ApplicationError) as stale_retry:
        retry_registry_operation(db_session, operation.id, candidate.revision, "reviewer", uuid4())
    assert stale_retry.value.code == "STALE_PROMOTION_SNAPSHOT"


def test_pending_candidate_rejects_evaluation_check_and_second_promotion(
    db_session: Any,
) -> None:
    candidate = db_session.scalar(select(Candidate).where(Candidate.slug == "renewal-briefing"))
    assert candidate is not None
    candidate, _ = queue_promotion(
        db_session,
        candidate.id,
        candidate.revision,
        "reviewer",
        "Queue this exact tested version for registry activation.",
        uuid4(),
    )
    candidate_id = candidate.id
    revision = candidate.revision
    db_session.commit()
    client = TestClient(create_app())
    for path in ("evaluate", "promotion-check"):
        response = client.post(
            f"/api/v1/candidates/{candidate_id}/{path}",
            headers={"Idempotency-Key": f"pending-{path}"},
            json={"expected_candidate_revision": revision, "actor": "safety-test"},
        )
        assert response.status_code == 409
        assert response.json()["code"] == "CANDIDATE_LIFECYCLE_LOCKED"
    second = client.post(
        f"/api/v1/candidates/{candidate_id}/promote",
        headers={"Idempotency-Key": "pending-second-promote"},
        json={
            "expected_candidate_revision": revision,
            "actor": "safety-test",
            "rationale": "Try to queue a duplicate registry activation operation.",
        },
    )
    assert second.status_code == 409
    assert second.json()["code"] == "PROMOTION_ALREADY_PENDING"


def test_approval_projection_uses_exact_binding_and_consumed_state(db_session: Any) -> None:
    candidate = db_session.scalar(select(Candidate).where(Candidate.slug == "renewal-briefing"))
    assert candidate is not None and candidate.active_policy_id is not None
    policy = db_session.get(Policy, candidate.active_policy_id)
    assert policy is not None
    policy.required_lifecycle_approvals = 1
    wrong_target = create_lifecycle_approval(
        db_session,
        candidate.id,
        "reviewer-a",
        "Approve only the shadow lifecycle stage for this exact evidence.",
        target_stage="SHADOW",
    )
    db_session.flush()
    required = project_promotion_eligibility(db_session, candidate)
    assert required.approval_state == "REQUIRED"
    assert required.available_approvals == 0
    assert wrong_target.target_stage == "SHADOW"

    create_lifecycle_approval(
        db_session,
        candidate.id,
        "reviewer-b",
        "Approve production selection for this exact tested evidence snapshot.",
    )
    db_session.flush()
    approved = project_promotion_eligibility(db_session, candidate)
    assert approved.approval_state == "APPROVED"
    assert approved.eligible

    blocker = Blocker(
        candidate_id=candidate.id,
        code="UNRELATED_OPERATOR_HOLD",
        category="LIFECYCLE",
        title="Operator hold remains active",
        explanation="An operator paused this lifecycle decision.",
        recovery="Clear the operator hold before promotion.",
        details={},
    )
    db_session.add(blocker)
    db_session.flush()
    assert not project_promotion_eligibility(db_session, candidate).eligible
    blocker.cleared_at = datetime.now(UTC)
    blocker.cleared_by = "reviewer-b"
    candidate, _ = queue_promotion(
        db_session,
        candidate.id,
        candidate.revision,
        "reviewer-b",
        "Queue registry publication for the approved evidence snapshot.",
        uuid4(),
    )
    db_session.commit()
    detail = TestClient(create_app()).get(f"/api/v1/candidates/{candidate.id}")
    assert detail.status_code == 200
    eligibility = detail.json()["promotion_eligibility"]
    assert eligibility["lifecycle_approval_state"] == "CONSUMED"
    assert eligibility["consumed_lifecycle_approvals"] == 1
    assert eligibility["eligible"] is False


def test_external_registry_success_state_mismatch_blocks_and_reuses_token(
    db_session: Any,
) -> None:
    candidate = db_session.scalar(select(Candidate).where(Candidate.slug == "renewal-briefing"))
    assert candidate is not None
    _, operation = queue_promotion(
        db_session,
        candidate.id,
        candidate.revision,
        "reviewer",
        "Queue registry publication before simulating local state drift.",
        uuid4(),
    )
    token = operation.publication_token
    db_session.commit()
    from promotion_control_plane.worker.service import claim_registry_operation

    claimed = claim_registry_operation(db_session, "mismatch-worker", 30)
    assert claimed is not None
    candidate = db_session.get(Candidate, candidate.id)
    assert candidate is not None
    candidate.status = "ACTIVE"
    db_session.commit()
    completed = complete_registry_success(
        db_session,
        operation.id,
        RegistryPublication("external-existing", {"deduplicated": True}),
        "mismatch-worker",
    )
    assert not completed
    db_session.expire_all()
    candidate = db_session.get(Candidate, candidate.id)
    operation = db_session.get(RegistryOperation, operation.id)
    assert candidate is not None and operation is not None
    assert (candidate.stage, candidate.status) == ("ELIGIBLE", "BLOCKED")
    assert operation.failure_code == "REGISTRY_COMPLETION_STATE_MISMATCH"
    assert db_session.scalar(
        select(Blocker).where(
            Blocker.candidate_id == candidate.id,
            Blocker.code == "REGISTRY_COMPLETION_STATE_MISMATCH",
            Blocker.cleared_at.is_(None),
        )
    )
    _, retried = retry_registry_operation(
        db_session, operation.id, candidate.revision, "reviewer", uuid4()
    )
    assert retried.publication_token == token
    assert retried.status == "QUEUED"


def test_registry_retry_rejects_unrelated_active_blocker(db_session: Any) -> None:
    candidate = db_session.scalar(select(Candidate).where(Candidate.slug == "renewal-briefing"))
    assert candidate is not None
    _, operation = queue_promotion(
        db_session,
        candidate.id,
        candidate.revision,
        "reviewer",
        "Queue a controlled registry failure before adding an authorization hold.",
        uuid4(),
    )
    operation.request_snapshot = {**operation.request_snapshot, "simulate_terminal_failure": True}
    db_session.commit()
    assert process_registry_once(
        get_session_factory(), DeterministicPromotionRegistry(), "blocker-worker", 30
    )
    db_session.expire_all()
    candidate = db_session.get(Candidate, candidate.id)
    operation = db_session.get(RegistryOperation, operation.id)
    assert candidate is not None and operation is not None
    db_session.add(
        Blocker(
            candidate_id=candidate.id,
            code="AUTHORIZATION_SCOPE_VIOLATION",
            category="AUTHORIZATION",
            title="Authorization boundary changed",
            explanation="The approved execution boundary no longer matches this version.",
            recovery="Restore and review the bounded authority envelope before retrying.",
            details={},
        )
    )
    db_session.flush()

    with pytest.raises(ApplicationError) as blocked_retry:
        retry_registry_operation(
            db_session, operation.id, candidate.revision, "reviewer", uuid4()
        )

    assert blocked_retry.value.code == "ACTIVE_BLOCKER_PREVENTS_REGISTRY_RETRY"
    assert "AUTHORIZATION_SCOPE_VIOLATION" in blocked_retry.value.extensions["blocker_codes"]
    assert operation.status == "FAILED"


def test_registry_retry_rejects_suspended_candidate(db_session: Any) -> None:
    candidate = db_session.scalar(select(Candidate).where(Candidate.slug == "renewal-briefing"))
    assert candidate is not None
    _, operation = queue_promotion(
        db_session,
        candidate.id,
        candidate.revision,
        "reviewer",
        "Queue a controlled registry failure before suspending the candidate.",
        uuid4(),
    )
    operation.request_snapshot = {**operation.request_snapshot, "simulate_terminal_failure": True}
    db_session.commit()
    assert process_registry_once(
        get_session_factory(), DeterministicPromotionRegistry(), "suspension-worker", 30
    )
    db_session.expire_all()
    candidate = db_session.get(Candidate, candidate.id)
    operation = db_session.get(RegistryOperation, operation.id)
    assert candidate is not None and operation is not None
    candidate.status = "SUSPENDED"
    candidate.revision += 1
    db_session.flush()

    with pytest.raises(ApplicationError) as suspended_retry:
        retry_registry_operation(
            db_session, operation.id, candidate.revision, "reviewer", uuid4()
        )

    assert suspended_retry.value.code == "REGISTRY_RETRY_STATE_INVALID"
    assert operation.status == "FAILED"


def test_openai_provider_registers_only_when_configured(monkeypatch: Any) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    get_settings.cache_clear()
    assert "openai-rubric" not in default_evaluator_providers()
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-key")
    get_settings.cache_clear()
    try:
        assert "openai-rubric" in default_evaluator_providers()
    finally:
        get_settings.cache_clear()


def test_dead_letter_sweep_is_single_writer_under_concurrent_workers(db_session: Any) -> None:
    candidate = db_session.scalar(
        select(Candidate).where(Candidate.slug == "invoice-reconciliation")
    )
    assert candidate is not None
    run = db_session.scalar(select(EvaluationRun).where(EvaluationRun.candidate_id == candidate.id))
    assert run is not None
    run.status = "QUEUED"
    run.attempt_count = 1
    run.max_attempts = 1
    correlation_id = run.correlation_id
    run_id = run.id
    candidate_id = candidate.id
    before_sequence = db_session.scalar(select(func.max(PromotionEvent.sequence))) or 0
    db_session.commit()
    db_session.close()

    changed: list[int] = []

    def sweep(worker_id: str) -> None:
        changed.append(dead_letter_exhausted_work(get_session_factory(), worker_id))

    first = Thread(target=sweep, args=("dead-letter-a",))
    second = Thread(target=sweep, args=("dead-letter-b",))
    first.start()
    second.start()
    first.join(10)
    second.join(10)
    assert not first.is_alive() and not second.is_alive()
    assert sum(changed) == 1
    with get_session_factory()() as session:
        exhausted = session.get(EvaluationRun, run_id)
        assert exhausted is not None and exhausted.status == "FAILED"
        assert (
            session.scalar(
                select(func.count(Blocker.id)).where(
                    Blocker.candidate_id == candidate_id,
                    Blocker.code == "EVALUATION_RETRIES_EXHAUSTED",
                    Blocker.cleared_at.is_(None),
                )
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count(PromotionEvent.sequence)).where(
                    PromotionEvent.correlation_id == correlation_id,
                    PromotionEvent.event_type == "EVALUATION_DEAD_LETTERED",
                    PromotionEvent.sequence > before_sequence,
                )
            )
            == 1
        )


def test_process_health_heartbeat_advances_during_long_work(tmp_path: Any) -> None:
    path = tmp_path / "worker-health"
    with ProcessHealthHeartbeat(path, interval_seconds=0.01):
        time.sleep(0.03)
        first = read_worker_heartbeat(path)
        time.sleep(0.03)
        second = read_worker_heartbeat(path)
    assert second > first


def test_autonomous_cycle_uses_real_leased_phases_and_one_lineage(db_session: Any) -> None:
    correlation_id = uuid4()
    runs = enqueue_demo_cycle(db_session, "worker-flow", "demo-test", correlation_id)
    db_session.commit()
    assert len(runs) == 6
    for _ in range(6):
        assert process_schedule_once(get_session_factory(), "schedule-worker", 30)

    db_session.expire_all()
    candidate = db_session.scalar(
        select(Candidate).where(Candidate.slug == "change-risk-coordinator")
    )
    assert candidate is not None
    assert candidate.stage == "EVALUATING"
    evaluation_run = db_session.scalar(
        select(EvaluationRun).where(EvaluationRun.candidate_id == candidate.id)
    )
    assert evaluation_run is not None and evaluation_run.status == "QUEUED"
    assert (
        db_session.scalar(
            select(RegistryOperation).where(RegistryOperation.candidate_id == candidate.id)
        )
        is None
    )

    assert process_evaluation_once(get_session_factory(), "evaluation-worker", 30)
    db_session.expire_all()
    operation = db_session.scalar(
        select(RegistryOperation).where(RegistryOperation.candidate_id == candidate.id)
    )
    assert operation is not None and operation.status == "QUEUED"
    assert process_registry_once(
        get_session_factory(), DeterministicPromotionRegistry(), "registry-worker", 30
    )
    db_session.expire_all()
    candidate = db_session.get(Candidate, candidate.id)
    assert candidate is not None
    assert (candidate.stage, candidate.status) == ("MONITORED", "ACTIVE")

    events = list(
        db_session.scalars(
            select(PromotionEvent)
            .where(
                PromotionEvent.candidate_id == candidate.id,
                PromotionEvent.correlation_id == correlation_id,
            )
            .order_by(PromotionEvent.sequence)
        )
    )
    types = [event.event_type for event in events]
    ordered = [
        "CANDIDATE_DISCOVERED",
        "EVALUATION_PLANNED",
        "EVALUATION_QUEUED",
        "EVALUATION_STARTED",
        "EVALUATION_COMPLETED",
        "ELIGIBILITY_DECIDED",
        "PROMOTION_APPROVED",
        "PROMOTION_REGISTRY_QUEUED",
        "PROMOTION_REGISTRY_ATTEMPT_STARTED",
        "PROMOTED",
        "POST_PROMOTION_MONITORING_OBSERVED",
    ]
    assert [event_type for event_type in types if event_type in ordered] == ordered
    assert {event.correlation_id for event in events} == {correlation_id}
    assert all(event.scheduled_job_run_id is not None for event in events)


def test_discovery_only_candidate_resumes_planning(db_session: Any) -> None:
    policy = db_session.scalar(select(Policy).where(Policy.policy_key == "default-demo-policy"))
    assert policy is not None
    correlation_id = uuid4()
    candidate = Candidate(
        id=seeded_uuid("candidate:change-risk-coordinator"),
        slug="change-risk-coordinator",
        name="Change Risk Coordinator",
        summary="A discovery phase committed before planning.",
        stage="DISCOVERED",
        status="ACTIVE",
        revision=1,
        active_policy_id=policy.id,
        current_policy_version=policy.version,
        source_metadata={"autonomous_cycle": True, "cycle_correlation_id": str(correlation_id)},
    )
    db_session.add(candidate)
    db_session.commit()
    resumed = advance_autonomous_cycle(db_session, correlation_id=correlation_id)
    assert resumed.stage == "EVALUATING"
    run = db_session.scalar(select(EvaluationRun).where(EvaluationRun.candidate_id == resumed.id))
    assert run is not None and run.status == "QUEUED"


def test_policy_driven_lifecycle_validator() -> None:
    stages = [
        "DISCOVERED",
        "CANDIDATE",
        "EVALUATING",
        "ELIGIBLE",
        "SHADOW",
        "PROMOTED",
        "MONITORED",
    ]
    validate_lifecycle_transition("DISCOVERED", "EVALUATING", stages)
    validate_lifecycle_transition("ELIGIBLE", "PROMOTED", stages)
    validate_lifecycle_transition("PROMOTED", "MONITORED", stages)
    with pytest.raises(ValueError):
        validate_lifecycle_transition("MONITORED", "PROMOTED", stages)
    with pytest.raises(ValueError):
        validate_lifecycle_transition("DISCOVERED", "ELIGIBLE", stages)


def test_event_sequences_cannot_commit_out_of_cursor_order(db_session: Any) -> None:
    del db_session
    first_correlation = uuid4()
    second_correlation = uuid4()
    first_allocated = Event()
    release_first = Event()
    second_committed = Event()

    def first_writer() -> None:
        with get_session_factory()() as session:
            emit_event(session, "CONCURRENT_FIRST", "test", first_correlation)
            first_allocated.set()
            assert release_first.wait(5)
            session.commit()

    def second_writer() -> None:
        assert first_allocated.wait(5)
        with get_session_factory()() as session:
            emit_event(session, "CONCURRENT_SECOND", "test", second_correlation)
            session.commit()
            second_committed.set()

    first_thread = Thread(target=first_writer)
    second_thread = Thread(target=second_writer)
    first_thread.start()
    second_thread.start()
    assert first_allocated.wait(5)
    time.sleep(0.1)
    assert not second_committed.is_set()
    release_first.set()
    first_thread.join(5)
    second_thread.join(5)
    assert second_committed.is_set()
    with get_session_factory()() as session:
        first = session.scalar(
            select(PromotionEvent).where(PromotionEvent.correlation_id == first_correlation)
        )
        second = session.scalar(
            select(PromotionEvent).where(PromotionEvent.correlation_id == second_correlation)
        )
        assert first is not None and second is not None
        assert first.sequence < second.sequence
