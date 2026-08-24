from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from promotion_control_plane.application.errors import unprocessable
from promotion_control_plane.domain.readiness import (
    AggregationRule,
    ComparisonOperator,
    CriterionDefinition,
    CriterionEvaluation,
    GateSummary,
    Measurement,
    aggregate_measurements,
    calculate_readiness,
)
from promotion_control_plane.infrastructure.models import (
    Candidate,
    Criterion,
    EvaluationPlan,
    EvaluationPlanItem,
    EvaluationResult,
    EvaluationRun,
    Policy,
)


def _missing_plan_summary() -> GateSummary:
    return GateSummary(
        hard_gate_readiness=Decimal(0),
        weighted_score=None,
        weighted_readiness=Decimal(0),
        sample_completeness=Decimal(0),
        evaluation_completeness=Decimal(0),
        readiness_percentage=Decimal(0),
        promotion_evidence_eligible=False,
        gate_verdicts={},
    )


def active_plan_for_candidate(session: Session, candidate_id: UUID) -> EvaluationPlan | None:
    """Return the active plan only when it is bound to the candidate's active policy.

    Detail/read models deliberately receive a zero-readiness result for missing or
    mismatched plans. Mutation paths call ``require_active_plan`` so they fail with
    a stable, typed error instead of advancing lifecycle state.
    """
    candidate = session.get(Candidate, candidate_id)
    if candidate is None or candidate.active_policy_id is None:
        return None
    plan = session.scalar(
        select(EvaluationPlan)
        .where(EvaluationPlan.candidate_id == candidate_id, EvaluationPlan.active.is_(True))
        .order_by(EvaluationPlan.version.desc())
        .limit(1)
    )
    if plan is None or plan.candidate_id != candidate.id:
        return None
    if plan.policy_id != candidate.active_policy_id:
        return None
    return plan


def require_active_plan(session: Session, candidate_id: UUID) -> EvaluationPlan:
    candidate = session.get(Candidate, candidate_id)
    if candidate is None or candidate.active_policy_id is None:
        raise unprocessable(
            "EVALUATION_PLAN_REQUIRED",
            "Assign an active policy and evaluation plan before checking promotion eligibility.",
        )
    plan = session.scalar(
        select(EvaluationPlan)
        .where(EvaluationPlan.candidate_id == candidate_id, EvaluationPlan.active.is_(True))
        .order_by(EvaluationPlan.version.desc())
        .limit(1)
    )
    if plan is None:
        raise unprocessable(
            "EVALUATION_PLAN_REQUIRED",
            "Create an active evaluation plan before checking promotion eligibility.",
        )
    if plan.candidate_id != candidate.id or plan.policy_id != candidate.active_policy_id:
        raise unprocessable(
            "ACTIVE_PLAN_POLICY_MISMATCH",
            "The active evaluation plan does not match the candidate's active policy.",
            active_policy_id=str(candidate.active_policy_id),
            plan_policy_id=str(plan.policy_id),
        )
    return plan


def calculate_candidate_readiness(session: Session, candidate_id: UUID) -> GateSummary:
    plan = active_plan_for_candidate(session, candidate_id)
    if plan is None:
        return _missing_plan_summary()
    policy = session.get(Policy, plan.policy_id)
    if policy is None:
        return _missing_plan_summary()
    run_ids = list(
        session.scalars(
            select(EvaluationRun.id).where(
                EvaluationRun.plan_id == plan.id, EvaluationRun.status == "SUCCEEDED"
            )
        )
    )
    results_by_criterion: dict[UUID, list[EvaluationResult]] = {}
    if run_ids:
        for result in session.scalars(
            select(EvaluationResult).where(
                EvaluationResult.evaluation_run_id.in_(run_ids),
                EvaluationResult.valid.is_(True),
                EvaluationResult.stale.is_(False),
            )
        ):
            results_by_criterion.setdefault(result.criterion_id, []).append(result)
    criteria = list(
        session.scalars(
            select(Criterion)
            .join(EvaluationPlanItem, EvaluationPlanItem.criterion_id == Criterion.id)
            .where(EvaluationPlanItem.plan_id == plan.id)
            .order_by(Criterion.ordinal)
        )
    )
    evaluated: list[CriterionEvaluation] = []
    for criterion in criteria:
        results = results_by_criterion.get(criterion.id, [])
        rule = AggregationRule(criterion.aggregation_rule)
        score = aggregate_measurements(
            [Measurement(result.normalized_score, result.sample_count) for result in results], rule
        )
        sample_count = sum(result.sample_count for result in results)
        evidence_codes = frozenset(code for result in results for code in result.evidence_codes)
        raw_value: Decimal | None = None
        if results:
            if rule == AggregationRule.SAMPLE_WEIGHTED_MEAN:
                if sample_count:
                    raw_value = sum(
                        result.measurement_value * Decimal(result.sample_count)
                        for result in results
                    ) / Decimal(sample_count)
                else:
                    raw_value = sum(result.measurement_value for result in results) / Decimal(
                        len(results)
                    )
            elif rule == AggregationRule.MEAN:
                raw_value = sum(result.measurement_value for result in results) / Decimal(
                    len(results)
                )
            elif rule == AggregationRule.MINIMUM:
                raw_value = min(result.measurement_value for result in results)
            else:
                raw_value = max(result.measurement_value for result in results)
        definition = CriterionDefinition(
            code=criterion.criterion_key,
            hard_gate=criterion.hard_gate,
            threshold=criterion.threshold,
            comparison_operator=ComparisonOperator(criterion.comparison_operator),
            weight=criterion.weight,
            minimum_samples=criterion.minimum_samples,
            required_evidence=tuple(criterion.required_evidence),
        )
        evaluated.append(
            CriterionEvaluation(
                definition=definition,
                normalized_score=score,
                measurement_value=raw_value,
                sample_count=sample_count,
                evidence_codes=evidence_codes,
                valid=bool(results),
                stale=False,
            )
        )
    return calculate_readiness(evaluated, policy.minimum_weighted_score)
