from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from promotion_control_plane.adapters.protocols import RegistryPublication
from promotion_control_plane.api.app import create_app
from promotion_control_plane.api.sse import _read_events
from promotion_control_plane.application.promotion import queue_promotion, retry_registry_operation
from promotion_control_plane.application.readiness import calculate_candidate_readiness
from promotion_control_plane.cli.main import app as cli_app
from promotion_control_plane.infrastructure.database import get_session_factory
from promotion_control_plane.infrastructure.models import (
    AgentVersion,
    Blocker,
    Candidate,
    Policy,
    PromotionEvent,
    RegistryOperation,
    ScheduledJob,
    ScheduledJobRun,
)
from promotion_control_plane.infrastructure.seed import reset_demo, seeded_uuid
from promotion_control_plane.settings import get_settings
from promotion_control_plane.worker.service import (
    DeterministicPromotionRegistry,
    claim_registry_operation,
    dead_letter_exhausted_work,
    process_registry_once,
)

pytestmark = pytest.mark.postgres


def _candidate(session: Session, slug: str = "renewal-briefing") -> Candidate:
    candidate = session.scalar(select(Candidate).where(Candidate.slug == slug))
    assert candidate is not None
    return candidate


def test_promotion_is_pending_until_registry_worker_succeeds(db_session: Any) -> None:
    candidate = _candidate(db_session)
    correlation_id = uuid4()
    candidate, operation = queue_promotion(
        db_session,
        candidate.id,
        candidate.revision,
        "reviewer@example.test",
        "Activate this exact tested evidence snapshot after registry success.",
        correlation_id,
    )
    db_session.commit()
    assert candidate.stage == "ELIGIBLE"
    assert candidate.status == "PROMOTION_PENDING"
    assert operation.status == "QUEUED"
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(PromotionEvent)
            .where(
                PromotionEvent.event_type == "PROMOTED",
                PromotionEvent.candidate_id == candidate.id,
                PromotionEvent.registry_operation_id == operation.id,
            )
        )
        == 0
    )

    assert process_registry_once(
        get_session_factory(), DeterministicPromotionRegistry(), "test-worker", 30
    )
    db_session.expire_all()
    promoted = db_session.get(Candidate, candidate.id)
    assert promoted is not None
    assert (promoted.stage, promoted.status) == ("PROMOTED", "ACTIVE")
    event = db_session.scalar(
        select(PromotionEvent).where(
            PromotionEvent.event_type == "PROMOTED",
            PromotionEvent.candidate_id == candidate.id,
            PromotionEvent.registry_operation_id == operation.id,
        )
    )
    assert event is not None
    assert event.correlation_id == correlation_id
    assert event.causation_id == operation.causation_event_id


def test_terminal_registry_failure_returns_to_eligible_and_retry_reuses_token(
    db_session: Any,
) -> None:
    candidate = _candidate(db_session)
    candidate, operation = queue_promotion(
        db_session,
        candidate.id,
        candidate.revision,
        "reviewer@example.test",
        "Queue a deterministic terminal registry failure for the reference test.",
        uuid4(),
    )
    operation.request_snapshot = {**operation.request_snapshot, "simulate_terminal_failure": True}
    token = operation.publication_token
    db_session.commit()
    process_registry_once(
        get_session_factory(), DeterministicPromotionRegistry(), "test-worker", 30
    )
    db_session.expire_all()
    operation = db_session.get(RegistryOperation, operation.id)
    candidate = db_session.get(Candidate, candidate.id)
    assert operation is not None and candidate is not None
    assert operation.status == "FAILED"
    assert (candidate.stage, candidate.status) == ("ELIGIBLE", "BLOCKED")
    assert (
        db_session.scalar(
            select(Blocker).where(
                Blocker.candidate_id == candidate.id,
                Blocker.code == "REGISTRY_OPERATION_FAILED",
                Blocker.cleared_at.is_(None),
            )
        )
        is not None
    )

    candidate, operation = retry_registry_operation(
        db_session, operation.id, candidate.revision, "reviewer@example.test", uuid4()
    )
    assert operation.status == "QUEUED"
    assert operation.attempt_count == 0
    assert operation.publication_token == token
    assert candidate.status == "PROMOTION_PENDING"
    failed_event = db_session.scalar(
        select(PromotionEvent).where(
            PromotionEvent.registry_operation_id == operation.id,
            PromotionEvent.event_type == "PROMOTION_REGISTRY_FAILED",
        )
    )
    blocker_added = db_session.scalar(
        select(PromotionEvent).where(
            PromotionEvent.registry_operation_id == operation.id,
            PromotionEvent.event_type == "BLOCKER_ADDED",
        )
    )
    retry_event = db_session.scalar(
        select(PromotionEvent).where(
            PromotionEvent.registry_operation_id == operation.id,
            PromotionEvent.event_type == "PROMOTION_REGISTRY_RETRY_QUEUED",
        )
    )
    blocker_cleared = db_session.scalar(
        select(PromotionEvent).where(
            PromotionEvent.registry_operation_id == operation.id,
            PromotionEvent.event_type == "BLOCKER_CLEARED",
        )
    )
    assert failed_event is not None and blocker_added is not None
    assert retry_event is not None and blocker_cleared is not None
    assert blocker_added.causation_id == failed_event.id
    assert blocker_cleared.causation_id == retry_event.id
    db_session.commit()


class RecordingRegistry:
    def __init__(self) -> None:
        self.tokens: list[str] = []

    def publish(self, publication_token: str, snapshot: dict[str, Any]) -> RegistryPublication:
        self.tokens.append(publication_token)
        return RegistryPublication(f"external-{publication_token[:8]}", {"deduplicated": True})


def test_crash_after_external_success_recovers_without_duplicate_version(db_session: Any) -> None:
    candidate = _candidate(db_session)
    _, operation = queue_promotion(
        db_session,
        candidate.id,
        candidate.revision,
        "reviewer@example.test",
        "Test recovery after an external success and local worker interruption.",
        uuid4(),
    )
    db_session.commit()
    registry = RecordingRegistry()
    with get_session_factory()() as claim_session:
        claimed = claim_registry_operation(claim_session, "crashed-worker", 30)
    assert claimed is not None
    registry.publish(claimed.publication_token, claimed.request_snapshot)
    with get_session_factory()() as session:
        stranded = session.get(RegistryOperation, claimed.id)
        assert stranded is not None
        stranded.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    assert process_registry_once(get_session_factory(), registry, "recovery-worker", 30)
    assert registry.tokens == [operation.publication_token, operation.publication_token]
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(AgentVersion)
            .where(AgentVersion.publication_token == operation.publication_token)
        )
        == 1
    )


def test_explicit_retry_clears_exhausted_blocker_and_reuses_publication_token(
    db_session: Any,
) -> None:
    candidate = _candidate(db_session)
    _, operation = queue_promotion(
        db_session,
        candidate.id,
        candidate.revision,
        "reviewer@example.test",
        "Exercise bounded registry dead-letter recovery for this exact snapshot.",
        uuid4(),
    )
    token = operation.publication_token
    operation.attempt_count = operation.max_attempts
    db_session.commit()
    assert dead_letter_exhausted_work(get_session_factory(), "dead-letter-worker") == 1
    db_session.expire_all()
    candidate = db_session.get(Candidate, candidate.id)
    operation = db_session.get(RegistryOperation, operation.id)
    assert candidate is not None and operation is not None
    assert operation.failure_code == "REGISTRY_RETRIES_EXHAUSTED"
    _, retried = retry_registry_operation(
        db_session, operation.id, candidate.revision, "reviewer@example.test", uuid4()
    )
    db_session.commit()
    assert retried.publication_token == token
    assert retried.attempt_count == 0
    assert process_registry_once(
        get_session_factory(), DeterministicPromotionRegistry(), "recovery-worker", 30
    )
    db_session.expire_all()
    candidate = db_session.get(Candidate, candidate.id)
    assert candidate is not None and (candidate.stage, candidate.status) == (
        "PROMOTED",
        "ACTIVE",
    )
    assert (
        db_session.scalar(
            select(func.count(Blocker.id)).where(
                Blocker.candidate_id == candidate.id,
                Blocker.code == "REGISTRY_RETRIES_EXHAUSTED",
                Blocker.cleared_at.is_(None),
            )
        )
        == 0
    )


def test_database_trigger_rejects_event_update_and_delete(db_session: Any) -> None:
    event = db_session.scalar(select(PromotionEvent).order_by(PromotionEvent.sequence).limit(1))
    assert event is not None
    with pytest.raises(DBAPIError):
        db_session.execute(
            update(PromotionEvent)
            .where(PromotionEvent.sequence == event.sequence)
            .values(actor="tampered")
        )
        db_session.commit()
    db_session.rollback()
    with pytest.raises(DBAPIError):
        db_session.delete(event)
        db_session.commit()
    db_session.rollback()
    with pytest.raises(DBAPIError):
        db_session.execute(text("TRUNCATE TABLE promotion_events"))
        db_session.commit()
    db_session.rollback()


def test_event_replay_reads_after_sequence(db_session: Any) -> None:
    events = _read_events(0, None)
    assert events
    replay = _read_events(events[0].sequence, None)
    assert all(event.sequence > events[0].sequence for event in replay)


def test_sse_rejects_malformed_last_event_id_as_problem_details(db_session: Any) -> None:
    db_session.close()
    response = TestClient(create_app()).get(
        "/api/v1/events/stream", headers={"Last-Event-ID": "not-a-sequence"}
    )
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "INVALID_EVENT_CURSOR"


@pytest.mark.parametrize("path", ["/api/v1/demo/cycle", "/api/v1/demo/run-cycle"])
def test_demo_cycle_api_aliases_are_disabled_outside_demo_mode(
    path: str,
    db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.close()
    with monkeypatch.context() as scoped:
        scoped.setenv("DEMO_MODE", "false")
        get_settings.cache_clear()
        try:
            response = TestClient(create_app()).post(
                path,
                headers={"Idempotency-Key": f"disabled:{path}"},
                json={"actor": "production-test"},
            )
        finally:
            get_settings.cache_clear()

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "DEMO_MODE_DISABLED"


def test_dashboard_reports_demo_mode_as_typed_runtime_state(
    db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.close()
    with monkeypatch.context() as scoped:
        scoped.setenv("DEMO_MODE", "false")
        get_settings.cache_clear()
        try:
            response = TestClient(create_app()).get("/api/v1/dashboard")
        finally:
            get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json()["demo_mode"] is False


@pytest.mark.parametrize("arguments", [["run-demo-cycle"], ["demo", "cycle"]])
def test_demo_cycle_cli_aliases_are_disabled_outside_demo_mode(
    arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with monkeypatch.context() as scoped:
        scoped.setenv("DEMO_MODE", "false")
        get_settings.cache_clear()
        try:
            result = CliRunner().invoke(cli_app, arguments)
        finally:
            get_settings.cache_clear()

    assert result.exit_code == 2
    assert "DEMO_MODE_DISABLED" in result.stderr


def test_demo_cycle_api_accepts_and_replays_maximum_length_idempotency_key(
    db_session: Any,
) -> None:
    db_session.close()
    client = TestClient(create_app())
    key = "a" * 160
    first = client.post(
        "/api/v1/demo/cycle",
        headers={"Idempotency-Key": key},
        json={"actor": "max-key-api-test"},
    )
    second = client.post(
        "/api/v1/demo/run-cycle",
        headers={"Idempotency-Key": key},
        json={"actor": "max-key-api-test"},
    )

    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert len(first.json()["job_run_ids"]) == 6


def test_demo_cycle_cli_accepts_and_replays_maximum_length_idempotency_key(
    db_session: Any,
) -> None:
    db_session.close()
    arguments = ["run-demo-cycle", "--idempotency-key", "b" * 160]

    first = CliRunner().invoke(cli_app, arguments)
    second = CliRunner().invoke(cli_app, arguments)

    assert first.exit_code == second.exit_code == 0
    assert first.output == second.output
    assert len(first.output.strip().splitlines()[-1]) > 0


def test_demo_cycle_cli_rejects_oversized_idempotency_key() -> None:
    result = CliRunner().invoke(
        cli_app,
        ["run-demo-cycle", "--idempotency-key", "c" * 161],
    )

    assert result.exit_code == 2
    assert "1 to 160 characters" in result.output


def test_api_contract_and_promotion_check_are_runnable(db_session: Any) -> None:
    candidate = _candidate(db_session)
    candidate_id = str(candidate.id)
    revision = candidate.revision
    db_session.close()
    client = TestClient(create_app())
    detail = client.get(f"/api/v1/candidates/{candidate_id}")
    assert detail.status_code == 200
    assert {
        "policy_hash",
        "evaluation_snapshot_hash",
        "lifecycle_approval_state",
        "gates",
        "evaluation_results",
        "timeline",
    }.issubset(detail.json())
    assert detail.json()["blocker_summary"] is None
    checked = client.post(
        f"/api/v1/candidates/{candidate_id}/promotion-check",
        headers={"Idempotency-Key": "promotion-check-test"},
        json={"expected_candidate_revision": revision, "actor": "api-test"},
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["outcome"] == "ELIGIBLE"


def test_mutations_require_idempotency_and_errors_are_problem_details(db_session: Any) -> None:
    job = db_session.scalar(select(ScheduledJob).limit(1))
    assert job is not None
    db_session.close()
    client = TestClient(create_app())
    missing = client.post(
        f"/api/v1/schedules/{job.id}/trigger",
        json={"actor": "test", "trigger_source": "API", "payload": {}},
    )
    assert missing.status_code == 422
    assert missing.headers["content-type"].startswith("application/problem+json")
    assert missing.json()["code"] == "REQUEST_VALIDATION_FAILED"
    absent = client.get("/definitely-not-a-route")
    assert absent.status_code == 404
    assert absent.json()["code"] == "RESOURCE_NOT_FOUND"


def test_schedule_trigger_is_idempotent_and_audited(db_session: Any) -> None:
    job = db_session.scalar(select(ScheduledJob).limit(1))
    assert job is not None
    job_id = str(job.id)
    before = db_session.scalar(select(func.max(PromotionEvent.sequence))) or 0
    db_session.close()
    client = TestClient(create_app())
    key = f"schedule-once:{uuid4()}"
    payload = {"actor": "external-test", "trigger_source": "API", "payload": {}}
    first = client.post(
        f"/api/v1/schedules/{job_id}/trigger",
        headers={"Idempotency-Key": key},
        json=payload,
    )
    second = client.post(
        f"/api/v1/schedules/{job_id}/trigger",
        headers={"Idempotency-Key": key},
        json=payload,
    )
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    events = client.get(f"/api/v1/events?after={before}").json()["items"]
    assert any(event["event_type"] == "SCHEDULE_TRIGGER_QUEUED" for event in events)


def test_cli_and_api_share_schedule_idempotency_command(db_session: Any) -> None:
    job = db_session.scalar(select(ScheduledJob).limit(1))
    assert job is not None
    job_key = job.job_key
    job_id = job.id
    db_session.close()
    key = f"shared-cli-api:{uuid4()}"
    result = CliRunner().invoke(
        cli_app,
        [
            "trigger-schedule",
            job_key,
            "--idempotency-key",
            key,
            "--actor",
            "shared-scheduler",
        ],
    )
    assert result.exit_code == 0, result.output
    run_id = result.output.strip().splitlines()[-1]
    client = TestClient(create_app())
    replay = client.post(
        f"/api/v1/schedules/{job_id}/trigger",
        headers={"Idempotency-Key": key},
        json={
            "actor": "shared-scheduler",
            "trigger_source": "CLI",
            "payload": {"autonomous_cycle": False},
        },
    )
    assert replay.status_code == 202
    assert replay.json()["job_run_id"] == run_id
    changed = client.post(
        f"/api/v1/schedules/{job_id}/trigger",
        headers={"Idempotency-Key": key},
        json={
            "actor": "different-scheduler",
            "trigger_source": "CLI",
            "payload": {"autonomous_cycle": False},
        },
    )
    assert changed.status_code == 409
    assert changed.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_demo_reset_idempotency_rejects_changed_body(db_session: Any) -> None:
    db_session.close()
    client = TestClient(create_app())
    first = client.post(
        "/api/v1/demo/reset",
        headers={"Idempotency-Key": "reset-once"},
        json={"actor": "operator-a"},
    )
    same = client.post(
        "/api/v1/demo/reset",
        headers={"Idempotency-Key": "reset-once"},
        json={"actor": "operator-a"},
    )
    changed = client.post(
        "/api/v1/demo/reset",
        headers={"Idempotency-Key": "reset-once"},
        json={"actor": "operator-b"},
    )
    assert first.status_code == same.status_code == 200
    assert first.json() == same.json()
    assert changed.status_code == 409
    assert changed.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_demo_reset_preserves_receipts_and_event_cursor_across_a_b_a(db_session: Any) -> None:
    before = db_session.scalar(select(func.max(PromotionEvent.sequence))) or 0
    db_session.close()
    client = TestClient(create_app())
    key_prefix = f"reset-a-b-a:{uuid4()}"
    first_a = client.post(
        "/api/v1/demo/reset",
        headers={"Idempotency-Key": f"{key_prefix}:a"},
        json={"actor": "reset-a"},
    )
    reset_b = client.post(
        "/api/v1/demo/reset",
        headers={"Idempotency-Key": f"{key_prefix}:b"},
        json={"actor": "reset-b"},
    )
    replay_a = client.post(
        "/api/v1/demo/reset",
        headers={"Idempotency-Key": f"{key_prefix}:a"},
        json={"actor": "reset-a"},
    )
    assert first_a.status_code == reset_b.status_code == replay_a.status_code == 200
    assert replay_a.json() == first_a.json()
    assert reset_b.json()["correlation_id"] != first_a.json()["correlation_id"]
    replay = client.get(f"/api/v1/events?after={before}&limit=500").json()["items"]
    assert replay
    assert all(item["sequence"] > before for item in replay)
    assert any(item["event_type"] == "DEMO_RESET_COMPLETED" for item in replay)


def test_demo_reset_expires_cycle_receipts_that_reference_rebuilt_rows(db_session: Any) -> None:
    db_session.close()
    client = TestClient(create_app())
    cycle_key = f"cycle-reset-replay:{uuid4()}"

    first_cycle = client.post(
        "/api/v1/demo/run-cycle",
        headers={"Idempotency-Key": cycle_key},
        json={"actor": "cycle-before-reset"},
    )
    reset = client.post(
        "/api/v1/demo/reset",
        headers={"Idempotency-Key": f"reset:{uuid4()}"},
        json={"actor": "reset-between-cycles"},
    )
    second_cycle = client.post(
        "/api/v1/demo/run-cycle",
        headers={"Idempotency-Key": cycle_key},
        json={"actor": "cycle-before-reset"},
    )

    assert first_cycle.status_code == second_cycle.status_code == 202
    assert reset.status_code == 200
    first_ids = set(first_cycle.json()["job_run_ids"])
    second_ids = set(second_cycle.json()["job_run_ids"])
    assert first_ids.isdisjoint(second_ids)
    with get_session_factory()() as session:
        persisted_ids = {
            str(item)
            for item in session.scalars(
                select(ScheduledJobRun.id).where(
                    ScheduledJobRun.id.in_([UUID(item) for item in second_ids])
                )
            )
        }
    assert persisted_ids == second_ids


def test_demo_reset_preserves_material_fixture_identity_and_central_readiness(
    db_session: Any,
) -> None:
    def signature() -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]], list[tuple[Any, ...]]]:
        candidates = list(db_session.scalars(select(Candidate).order_by(Candidate.slug)))
        candidate_signature = [
            (
                item.slug,
                item.id,
                item.stage,
                item.status,
                item.revision,
                str(item.readiness_percentage),
                item.current_evaluation_snapshot_hash,
            )
            for item in candidates
        ]
        for item in candidates:
            assert item.readiness_percentage == calculate_candidate_readiness(
                db_session, item.id
            ).readiness_percentage.quantize(Decimal("0.001"))
        policy_signature = [
            (item.policy_key, item.version, item.id, item.content_hash)
            for item in db_session.scalars(
                select(Policy).order_by(Policy.policy_key, Policy.version)
            )
        ]
        operation_signature = [
            (item.id, item.candidate_id, item.publication_token, item.evaluation_snapshot_hash)
            for item in db_session.scalars(
                select(RegistryOperation).order_by(RegistryOperation.candidate_id)
            )
        ]
        return candidate_signature, policy_signature, operation_signature

    first = signature()
    reset_demo(db_session)
    second = signature()
    assert second == first


def test_seeded_digital_threads_have_causal_lineage_and_regression_blocker(
    db_session: Any,
) -> None:
    for slug in ("support-triage", "incident-summarizer", "vendor-risk-monitor"):
        candidate = _candidate(db_session, slug)
        correlation_id = seeded_uuid(f"correlation:{slug}")
        latest_root = db_session.scalar(
            select(func.max(PromotionEvent.sequence)).where(
                PromotionEvent.candidate_id == candidate.id,
                PromotionEvent.correlation_id == correlation_id,
                PromotionEvent.event_type == "CANDIDATE_DISCOVERED",
            )
        )
        assert latest_root is not None
        events = list(
            db_session.scalars(
                select(PromotionEvent)
                .where(
                    PromotionEvent.candidate_id == candidate.id,
                    PromotionEvent.correlation_id == correlation_id,
                    PromotionEvent.sequence >= latest_root,
                )
                .order_by(PromotionEvent.sequence)
            )
        )
        seen = {events[0].id}
        assert events[0].causation_id is None
        for event in events[1:]:
            assert event.causation_id in seen
            seen.add(event.id)
    vendor = _candidate(db_session, "vendor-risk-monitor")
    assert (vendor.stage, vendor.status) == ("MONITORED", "SUSPENDED")
    vendor_types = [
        item.event_type
        for item in db_session.scalars(
            select(PromotionEvent)
            .where(
                PromotionEvent.candidate_id == vendor.id,
                PromotionEvent.correlation_id == seeded_uuid("correlation:vendor-risk-monitor"),
            )
            .order_by(PromotionEvent.sequence)
        )
    ]
    assert "BLOCKER_ADDED" in vendor_types
    assert vendor_types.index("BLOCKER_ADDED") < vendor_types.index("CANDIDATE_SUSPENDED")
