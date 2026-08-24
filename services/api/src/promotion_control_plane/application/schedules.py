from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from croniter import croniter
from sqlalchemy.orm import Session

from promotion_control_plane.application.events import emit_event
from promotion_control_plane.application.idempotency import prior_response, record_response
from promotion_control_plane.infrastructure.models import ScheduledJob, ScheduledJobRun


def next_expected_trigger(expression: str, timezone: str, after: datetime) -> datetime:
    """Return the next cron observation in UTC, respecting the owner's timezone and DST."""
    if after.tzinfo is None:
        raise ValueError("after must be timezone-aware")
    zone = ZoneInfo(timezone)
    local_after = after.astimezone(zone)
    next_local = croniter(expression, local_after).get_next(datetime)
    if next_local.tzinfo is None:
        next_local = next_local.replace(tzinfo=zone)
    return next_local.astimezone(UTC)


def connection_message(connection_state: str) -> str:
    if connection_state == "CONNECTED":
        return "The named owner can trigger this job. This control plane only observes each run."
    return "This job will not run automatically until its named trigger owner reconnects."


def enqueue_schedule_trigger(
    session: Session,
    job: ScheduledJob,
    *,
    idempotency_key: str,
    actor: str,
    trigger_source: str,
    payload: dict[str, Any],
    max_attempts: int,
    correlation_id: UUID | None = None,
) -> tuple[dict[str, Any], bool]:
    """Shared API/CLI schedule command with serialized idempotency and audit lineage."""
    request = {
        "actor": actor,
        "trigger_source": trigger_source,
        "payload": payload,
    }
    scope = f"schedule:{job.id}:trigger"
    prior = prior_response(session, scope, idempotency_key, request)
    if prior is not None:
        return prior[1], True
    correlation_id = correlation_id or uuid4()
    run = ScheduledJobRun(
        job_id=job.id,
        trigger_idempotency_key=idempotency_key,
        triggered_by=actor,
        trigger_source=trigger_source,
        status="QUEUED",
        correlation_id=correlation_id,
        max_attempts=max_attempts,
        payload=payload,
    )
    session.add(run)
    session.flush()
    queued_event = emit_event(
        session,
        "SCHEDULE_TRIGGER_QUEUED",
        actor,
        correlation_id,
        scheduled_job_run_id=run.id,
        payload={
            "job_id": str(job.id),
            "job_key": job.job_key,
            "trigger_owner": job.trigger_owner,
            "status": run.status,
            "headline": "External schedule work entered the worker queue.",
            "detail": "The worker will claim this named job when capacity is available.",
        },
    )
    run.causation_event_id = queued_event.id
    response = {
        "job_run_id": str(run.id),
        "status": "QUEUED",
        "correlation_id": str(correlation_id),
    }
    record_response(session, scope, idempotency_key, request, 202, response, correlation_id)
    return response, False
