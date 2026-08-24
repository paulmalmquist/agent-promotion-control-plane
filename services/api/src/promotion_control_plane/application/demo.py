from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from promotion_control_plane.application.events import emit_event
from promotion_control_plane.domain.hashing import content_hash
from promotion_control_plane.infrastructure.models import ScheduledJob, ScheduledJobRun


def enqueue_demo_cycle(
    session: Session,
    idempotency_key: str,
    actor: str,
    correlation_id: UUID | None = None,
) -> list[ScheduledJobRun]:
    correlation_id = correlation_id or uuid4()
    jobs = list(session.scalars(select(ScheduledJob).order_by(ScheduledJob.job_key)))
    runs: list[ScheduledJobRun] = []
    for job in jobs:
        run_key = content_hash(
            {
                "scope": "demo-cycle-job",
                "idempotency_key": idempotency_key,
                "job_key": job.job_key,
            }
        )
        run = session.scalar(
            select(ScheduledJobRun).where(
                ScheduledJobRun.job_id == job.id,
                ScheduledJobRun.trigger_idempotency_key == run_key,
            )
        )
        if run is None:
            run = ScheduledJobRun(
                job_id=job.id,
                trigger_idempotency_key=run_key,
                triggered_by=actor,
                trigger_source="DEMO_COMMAND",
                status="QUEUED",
                correlation_id=correlation_id,
                payload={"autonomous_cycle": job.job_key == "nightly-candidate-discovery"},
            )
            session.add(run)
            session.flush()
            queued = emit_event(
                session,
                "SCHEDULE_TRIGGER_QUEUED",
                actor,
                correlation_id,
                scheduled_job_run_id=run.id,
                payload={
                    "job_key": job.job_key,
                    "trigger_owner": job.trigger_owner,
                    "status": run.status,
                },
            )
            run.causation_event_id = queued.id
        runs.append(run)
    return runs
