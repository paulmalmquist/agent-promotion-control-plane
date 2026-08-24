from typing import Any

from promotion_control_plane.infrastructure.models import (
    AgentVersion,
    Blocker,
    Candidate,
    EvidenceArtifact,
    PromotedAgent,
    PromotionEvent,
    RegistryOperation,
    ScheduledJob,
)


def candidate_summary(candidate: Candidate) -> dict[str, Any]:
    return {
        "id": str(candidate.id),
        "slug": candidate.slug,
        "name": candidate.name,
        "summary": candidate.summary,
        "candidate_type": candidate.candidate_type,
        "stage": candidate.stage,
        "status": candidate.status,
        "revision": candidate.revision,
        "proposed_capability": candidate.proposed_capability,
        "confidence": float(candidate.confidence),
        "readiness_percentage": float(candidate.readiness_percentage),
        "current_policy_version": candidate.current_policy_version,
        "discovered_at": candidate.discovered_at.isoformat(),
        "updated_at": candidate.updated_at.isoformat(),
    }


def blocker_view(blocker: Blocker) -> dict[str, Any]:
    return {
        "id": str(blocker.id),
        "code": blocker.code,
        "category": blocker.category,
        "title": blocker.title,
        "explanation": blocker.explanation,
        "recovery": blocker.recovery,
        "details": blocker.details,
        "created_at": blocker.created_at.isoformat(),
        "cleared_at": blocker.cleared_at.isoformat() if blocker.cleared_at else None,
    }


def event_view(event: PromotionEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "sequence": event.sequence,
        "event_type": event.event_type,
        "schema_version": event.schema_version,
        "actor": event.actor,
        "policy_hash": event.policy_hash,
        "correlation_id": str(event.correlation_id),
        "causation_id": str(event.causation_id) if event.causation_id else None,
        "candidate_id": str(event.candidate_id) if event.candidate_id else None,
        "evaluation_run_id": str(event.evaluation_run_id) if event.evaluation_run_id else None,
        "scheduled_job_run_id": str(event.scheduled_job_run_id)
        if event.scheduled_job_run_id
        else None,
        "registry_operation_id": str(event.registry_operation_id)
        if event.registry_operation_id
        else None,
        "payload": event.payload,
        "occurred_at": event.occurred_at.isoformat(),
    }


def schedule_view(job: ScheduledJob) -> dict[str, Any]:
    connected = job.connection_state.upper() == "CONNECTED"
    return {
        "id": str(job.id),
        "key": job.job_key,
        "name": job.name,
        "description": job.description,
        "job_type": job.job_type,
        "enabled": job.enabled,
        "trigger_owner": job.trigger_owner,
        "trigger_mode": job.trigger_mode,
        "owner_reference": job.owner_reference,
        "connection_state": job.connection_state,
        "connection_message": (
            "The named owner can trigger this job. This control plane only observes each run."
            if connected
            else "This job will not run automatically until its named trigger owner reconnects."
        ),
        "timezone": job.timezone,
        "schedule_expression": job.schedule_expression,
        "last_observed_run_at": job.last_observed_run_at.isoformat()
        if job.last_observed_run_at
        else None,
        "next_expected_trigger_at": (
            job.next_expected_trigger_at.isoformat() if job.next_expected_trigger_at else None
        ),
        "grace_window_seconds": job.grace_window_seconds,
    }


def registry_operation_view(operation: RegistryOperation) -> dict[str, Any]:
    return {
        "id": str(operation.id),
        "candidate_id": str(operation.candidate_id),
        "status": operation.status,
        "activation_state": (
            "PENDING"
            if operation.status in {"QUEUED", "RUNNING"}
            else "SUCCEEDED"
            if operation.status == "SUCCEEDED"
            else "FAILED"
        ),
        "publication_token": operation.publication_token,
        "attempt_count": operation.attempt_count,
        "failure_code": operation.failure_code,
        "failure_message": operation.failure_message,
        "correlation_id": str(operation.correlation_id),
        "created_at": operation.created_at.isoformat(),
        "completed_at": operation.completed_at.isoformat() if operation.completed_at else None,
    }


def version_view(
    version: AgentVersion,
    candidate: Candidate | None = None,
    agent: PromotedAgent | None = None,
) -> dict[str, Any]:
    view = {
        "id": str(version.id),
        "candidate_id": str(version.candidate_id),
        "version": version.version,
        "external_version_id": version.external_version_id,
        "policy_hash": version.policy_hash,
        "evaluation_snapshot_hash": version.evaluation_snapshot_hash,
        "publication_token": version.publication_token,
        "promoted_at": version.promoted_at.isoformat(),
    }
    if candidate is not None:
        view.update(
            {
                "candidate_name": candidate.name,
                "candidate_slug": candidate.slug,
                "stage": candidate.stage,
                "status": candidate.status,
                "monitoring_state": (
                    "SUSPENDED"
                    if candidate.status == "SUSPENDED"
                    else "MONITORED"
                    if candidate.stage == "MONITORED"
                    else "AWAITING_MONITORING"
                ),
                "active": candidate.status == "ACTIVE"
                and candidate.stage in {"PROMOTED", "MONITORED"},
            }
        )
    if agent is not None:
        view.update(
            {
                "agent_id": str(agent.id),
                "display_name": agent.display_name,
                "registry_key": agent.registry_key,
                "is_active_version": agent.active_version_id == version.id,
            }
        )
    return view


def artifact_view(artifact: EvidenceArtifact) -> dict[str, Any]:
    return {
        "id": str(artifact.id),
        "candidate_id": str(artifact.candidate_id),
        "evaluation_run_id": (
            str(artifact.evaluation_run_id) if artifact.evaluation_run_id else None
        ),
        "artifact_type": artifact.artifact_type,
        "uri": artifact.uri,
        "sha256": artifact.sha256,
        "media_type": artifact.media_type,
        "sanitized": artifact.sanitized,
        "provider_metadata": artifact.metadata_snapshot,
        "created_at": artifact.created_at.isoformat(),
    }
