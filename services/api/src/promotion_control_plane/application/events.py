from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from promotion_control_plane.infrastructure.models import PromotionEvent


def emit_event(
    session: Session,
    event_type: str,
    actor: str,
    correlation_id: UUID,
    *,
    candidate_id: UUID | None = None,
    policy_hash: str | None = None,
    causation_id: UUID | None = None,
    evaluation_run_id: UUID | None = None,
    scheduled_job_run_id: UUID | None = None,
    registry_operation_id: UUID | None = None,
    payload: dict[str, Any] | None = None,
) -> PromotionEvent:
    # BIGSERIAL values are allocated before commit. Serialize event-producing
    # transactions so a replay cursor can never observe N+1 and later miss a
    # transaction that commits N. The transaction-scoped lock is released only
    # after the material state change and its events commit together.
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"),
        {"lock_id": 7_384_119_203_517},
    )
    event = PromotionEvent(
        id=uuid4(),
        event_type=event_type,
        schema_version=1,
        actor=actor,
        policy_hash=policy_hash,
        correlation_id=correlation_id,
        causation_id=causation_id,
        candidate_id=candidate_id,
        evaluation_run_id=evaluation_run_id,
        scheduled_job_run_id=scheduled_job_run_id,
        registry_operation_id=registry_operation_id,
        payload=payload or {},
    )
    session.add(event)
    session.flush()
    return event
