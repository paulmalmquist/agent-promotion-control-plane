from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from promotion_control_plane.domain.hashing import content_hash
from promotion_control_plane.infrastructure.models import (
    Criterion,
    EvaluationPlan,
    EvaluationPlanItem,
    EvaluationResult,
    EvaluationRun,
    EvidenceArtifact,
    Policy,
)


def build_evaluation_snapshot(session: Session, candidate_id: UUID) -> tuple[dict[str, Any], str]:
    session.flush()
    snapshot: dict[str, Any]
    plan = session.scalar(
        select(EvaluationPlan)
        .where(EvaluationPlan.candidate_id == candidate_id, EvaluationPlan.active.is_(True))
        .order_by(EvaluationPlan.version.desc())
        .limit(1)
    )
    if plan is None:
        snapshot = {"candidate_id": str(candidate_id), "active_plan": None, "results": []}
        return snapshot, content_hash(snapshot)
    policy = session.get(Policy, plan.policy_id)
    items = list(
        session.scalars(
            select(EvaluationPlanItem)
            .where(EvaluationPlanItem.plan_id == plan.id)
            .order_by(EvaluationPlanItem.criterion_id)
        )
    )
    criteria = {
        criterion.id: criterion
        for criterion in session.scalars(
            select(Criterion).where(Criterion.policy_id == plan.policy_id)
        )
    }
    run_ids = list(
        session.scalars(
            select(EvaluationRun.id).where(
                EvaluationRun.plan_id == plan.id, EvaluationRun.status == "SUCCEEDED"
            )
        )
    )
    results = (
        list(
            session.scalars(
                select(EvaluationResult)
                .where(EvaluationResult.evaluation_run_id.in_(run_ids))
                .order_by(
                    EvaluationResult.criterion_id, EvaluationResult.created_at, EvaluationResult.id
                )
            )
        )
        if run_ids
        else []
    )
    artifacts = list(
        session.scalars(
            select(EvidenceArtifact)
            .where(EvidenceArtifact.candidate_id == candidate_id)
            .order_by(EvidenceArtifact.sha256, EvidenceArtifact.id)
        )
    )
    snapshot = {
        "candidate_id": str(candidate_id),
        "policy": {
            "id": str(policy.id) if policy else None,
            "version": policy.version if policy else None,
            "content_hash": policy.content_hash if policy else None,
        },
        "active_plan": {
            "id": str(plan.id),
            "version": plan.version,
            "content_hash": plan.content_hash,
            "items": [
                {
                    "criterion_id": str(item.criterion_id),
                    "criterion_hash": criteria[item.criterion_id].content_hash,
                    "evaluator_key": item.evaluator_key,
                    "evaluator_version": item.evaluator_version,
                    "evaluator_hash": item.evaluator_hash,
                    "configuration": item.configuration,
                }
                for item in items
            ],
        },
        "results": [
            {
                "id": str(result.id),
                "run_id": str(result.evaluation_run_id),
                "criterion_id": str(result.criterion_id),
                "measurement_type": result.measurement_type,
                "measurement_value": str(result.measurement_value),
                "measurement_unit": result.measurement_unit,
                "normalized_score": str(result.normalized_score),
                "cost_usd": str(result.cost_usd) if result.cost_usd is not None else None,
                "latency_ms": str(result.latency_ms) if result.latency_ms is not None else None,
                "sample_count": result.sample_count,
                "valid": result.valid,
                "stale": result.stale,
                "evidence_codes": sorted(result.evidence_codes),
                "measurements": result.measurements,
                "provider_metadata": result.provider_metadata,
                "created_at": result.created_at.isoformat(),
            }
            for result in results
        ],
        "artifacts": [
            {"id": str(artifact.id), "sha256": artifact.sha256, "sanitized": artifact.sanitized}
            for artifact in artifacts
        ],
    }
    return snapshot, content_hash(snapshot)
