from decimal import Decimal

import pytest

from promotion_control_plane.domain.enums import GateVerdict
from promotion_control_plane.domain.readiness import (
    AggregationRule,
    ComparisonOperator,
    CriterionDefinition,
    CriterionEvaluation,
    Measurement,
    aggregate_measurements,
    calculate_readiness,
    safe_mean,
    safe_ratio,
)


def evaluation(
    code: str,
    *,
    score: str | None = "1",
    raw: str | None = None,
    hard: bool = False,
    threshold: str = "0.8",
    operator: ComparisonOperator = ComparisonOperator.GTE,
    weight: str | None = None,
    samples: int = 10,
    minimum_samples: int = 10,
    required_evidence: tuple[str, ...] = (),
    evidence: frozenset[str] = frozenset(),
    stale: bool = False,
) -> CriterionEvaluation:
    return CriterionEvaluation(
        CriterionDefinition(
            code,
            hard,
            Decimal(threshold),
            operator,
            Decimal(weight) if weight else None,
            minimum_samples,
            required_evidence,
        ),
        Decimal(score) if score is not None else None,
        samples,
        evidence,
        score is not None,
        stale,
        Decimal(raw) if raw is not None else None,
    )


def test_safe_empty_helpers_are_satisfied() -> None:
    assert safe_ratio(0, 0) == Decimal(1)
    assert safe_mean([]) == Decimal(1)


def test_empty_policy_is_fully_ready_and_not_weighted() -> None:
    summary = calculate_readiness([], Decimal(0))
    assert summary.readiness_percentage == Decimal(100)
    assert summary.hard_gate_readiness == Decimal(1)
    assert summary.sample_completeness == Decimal(1)
    assert summary.evaluation_completeness == Decimal(1)
    assert summary.weighted_score is None
    assert summary.weighted_readiness == Decimal(1)
    assert summary.promotion_evidence_eligible


def test_no_hard_gates_and_no_sample_requirements_are_satisfied() -> None:
    item = evaluation("quality", weight="1", minimum_samples=0, samples=0)
    summary = calculate_readiness([item], Decimal(80))
    assert summary.hard_gate_readiness == Decimal(1)
    assert summary.sample_completeness == Decimal(1)
    assert summary.readiness_percentage == Decimal(100)


def test_zero_minimum_samples_contributes_one_in_mixed_set() -> None:
    no_samples = evaluation("documentation", minimum_samples=0, samples=0)
    half_samples = evaluation("quality", minimum_samples=10, samples=5)
    summary = calculate_readiness([no_samples, half_samples], Decimal(0))
    assert summary.sample_completeness == Decimal("0.75")


def test_incomplete_weighted_criterion_contributes_zero() -> None:
    item = evaluation("quality", score=None, weight="1", samples=0)
    summary = calculate_readiness([item], Decimal(80))
    assert summary.weighted_score == Decimal(0)
    assert summary.weighted_readiness == Decimal(0)
    assert not summary.promotion_evidence_eligible


def test_required_weighted_score_zero_is_satisfied() -> None:
    item = evaluation("quality", score="0", weight="1", minimum_samples=0)
    summary = calculate_readiness([item], Decimal(0))
    assert summary.weighted_score == Decimal(0)
    assert summary.weighted_readiness == Decimal(1)


def test_hard_gate_failure_cannot_be_outscored() -> None:
    gate = evaluation("safety", score="0", raw="0", hard=True, threshold="1", minimum_samples=0)
    weighted = evaluation("quality", score="1", weight="1", minimum_samples=0)
    summary = calculate_readiness([gate, weighted], Decimal(90))
    assert summary.weighted_score == Decimal(100)
    assert summary.gate_verdicts["safety"] == GateVerdict.FAILED
    assert not summary.promotion_evidence_eligible


def test_remaining_hard_gate_blocks() -> None:
    gate = evaluation("authorization", score=None, hard=True, threshold="1", samples=0)
    summary = calculate_readiness([gate], Decimal(0))
    assert summary.gate_verdicts["authorization"] == GateVerdict.REMAINING
    assert not summary.promotion_evidence_eligible


@pytest.mark.parametrize(
    ("operator", "raw", "threshold", "expected"),
    [
        (ComparisonOperator.LTE, "2.4", "2.5", GateVerdict.PASSED),
        (ComparisonOperator.LTE, "2.6", "2.5", GateVerdict.FAILED),
        (ComparisonOperator.EQ, "1", "1", GateVerdict.PASSED),
        (ComparisonOperator.EQ, "0", "1", GateVerdict.FAILED),
        (ComparisonOperator.GT, "2", "1", GateVerdict.PASSED),
        (ComparisonOperator.LT, "1", "2", GateVerdict.PASSED),
    ],
)
def test_central_gate_engine_supports_raw_comparison_operators(
    operator: ComparisonOperator, raw: str, threshold: str, expected: GateVerdict
) -> None:
    item = evaluation(
        "raw-gate",
        raw=raw,
        hard=True,
        threshold=threshold,
        operator=operator,
        minimum_samples=0,
    )
    assert item.verdict == expected


def test_weight_configuration_is_strict_only_when_weighted_criteria_exist() -> None:
    with pytest.raises(ValueError, match="nonzero weighted threshold"):
        calculate_readiness([], Decimal(1))
    with pytest.raises(ValueError, match="total 1.0"):
        calculate_readiness([evaluation("quality", weight="0.8")], Decimal(80))


def test_all_aggregation_rules() -> None:
    values = [Measurement(Decimal("0.2"), 1), Measurement(Decimal("0.8"), 3)]
    assert aggregate_measurements(values) == Decimal("0.65")
    assert aggregate_measurements(values, AggregationRule.MEAN) == Decimal("0.5")
    assert aggregate_measurements(values, AggregationRule.MINIMUM) == Decimal("0.2")
    assert aggregate_measurements(values, AggregationRule.MAXIMUM) == Decimal("0.8")
    assert aggregate_measurements([]) is None


def test_required_evidence_and_staleness_affect_completeness() -> None:
    missing = evaluation("evidence", required_evidence=("trace",), evidence=frozenset())
    stale = evaluation("stale", stale=True)
    assert not missing.complete
    assert not stale.complete
    assert calculate_readiness([missing, stale], Decimal(0)).evaluation_completeness == 0
