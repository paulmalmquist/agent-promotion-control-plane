from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from promotion_control_plane.domain.enums import GateVerdict

ONE = Decimal("1")
ZERO = Decimal("0")
HUNDRED = Decimal("100")


class AggregationRule(StrEnum):
    SAMPLE_WEIGHTED_MEAN = "sample_weighted_mean"
    MEAN = "mean"
    MINIMUM = "minimum"
    MAXIMUM = "maximum"


class ComparisonOperator(StrEnum):
    GTE = "gte"
    GT = "gt"
    LTE = "lte"
    LT = "lt"
    EQ = "eq"


def safe_ratio(numerator: int | Decimal, denominator: int | Decimal) -> Decimal:
    denominator_decimal = Decimal(denominator)
    if denominator_decimal == ZERO:
        return ONE
    return Decimal(numerator) / denominator_decimal


def safe_mean(values: Iterable[Decimal]) -> Decimal:
    materialized = list(values)
    if not materialized:
        return ONE
    return sum(materialized, ZERO) / Decimal(len(materialized))


@dataclass(frozen=True, slots=True)
class Measurement:
    normalized_score: Decimal
    sample_count: int = 1

    def __post_init__(self) -> None:
        if not ZERO <= self.normalized_score <= ONE:
            raise ValueError("normalized_score must be between 0 and 1")
        if self.sample_count < 0:
            raise ValueError("sample_count cannot be negative")


def aggregate_measurements(
    measurements: Iterable[Measurement],
    rule: AggregationRule = AggregationRule.SAMPLE_WEIGHTED_MEAN,
) -> Decimal | None:
    items = list(measurements)
    if not items:
        return None
    if rule == AggregationRule.SAMPLE_WEIGHTED_MEAN:
        samples = sum(item.sample_count for item in items)
        if samples == 0:
            return safe_mean(item.normalized_score for item in items)
        return sum(
            (item.normalized_score * Decimal(item.sample_count) for item in items), ZERO
        ) / Decimal(samples)
    if rule == AggregationRule.MEAN:
        return safe_mean(item.normalized_score for item in items)
    if rule == AggregationRule.MINIMUM:
        return min(item.normalized_score for item in items)
    if rule == AggregationRule.MAXIMUM:
        return max(item.normalized_score for item in items)
    raise ValueError(f"Unsupported aggregation rule: {rule}")


@dataclass(frozen=True, slots=True)
class CriterionDefinition:
    code: str
    hard_gate: bool
    threshold: Decimal
    comparison_operator: ComparisonOperator = ComparisonOperator.GTE
    weight: Decimal | None = None
    minimum_samples: int = 0
    required_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.weight is not None and not ZERO <= self.weight <= ONE:
            raise ValueError("weight must be between 0 and 1")
        if self.minimum_samples < 0:
            raise ValueError("minimum_samples cannot be negative")


@dataclass(frozen=True, slots=True)
class CriterionEvaluation:
    definition: CriterionDefinition
    normalized_score: Decimal | None
    sample_count: int
    evidence_codes: frozenset[str] = frozenset()
    valid: bool = True
    stale: bool = False
    measurement_value: Decimal | None = None

    @property
    def has_valid_result(self) -> bool:
        return self.valid and not self.stale and self.normalized_score is not None

    @property
    def has_enough_samples(self) -> bool:
        return (
            self.definition.minimum_samples == 0
            or self.sample_count >= self.definition.minimum_samples
        )

    @property
    def has_required_evidence(self) -> bool:
        return set(self.definition.required_evidence).issubset(self.evidence_codes)

    @property
    def complete(self) -> bool:
        return self.has_valid_result and self.has_enough_samples and self.has_required_evidence

    @property
    def verdict(self) -> GateVerdict | None:
        if not self.definition.hard_gate:
            return None
        if not self.complete:
            return GateVerdict.REMAINING
        value = self.measurement_value
        if value is None:
            value = self.normalized_score
        assert value is not None
        threshold = self.definition.threshold
        operator = self.definition.comparison_operator
        passed = {
            ComparisonOperator.GTE: value >= threshold,
            ComparisonOperator.GT: value > threshold,
            ComparisonOperator.LTE: value <= threshold,
            ComparisonOperator.LT: value < threshold,
            ComparisonOperator.EQ: value == threshold,
        }[operator]
        if passed:
            return GateVerdict.PASSED
        return GateVerdict.FAILED


@dataclass(frozen=True, slots=True)
class GateSummary:
    hard_gate_readiness: Decimal
    weighted_score: Decimal | None
    weighted_readiness: Decimal
    sample_completeness: Decimal
    evaluation_completeness: Decimal
    readiness_percentage: Decimal
    promotion_evidence_eligible: bool
    gate_verdicts: dict[str, GateVerdict]


def validate_weight_configuration(
    criteria: Iterable[CriterionEvaluation], minimum_weighted_score: Decimal
) -> None:
    weighted = [item for item in criteria if item.definition.weight is not None]
    if not weighted:
        if minimum_weighted_score != ZERO:
            raise ValueError("A nonzero weighted threshold requires weighted criteria")
        return
    total = sum((item.definition.weight or ZERO for item in weighted), ZERO)
    if total != ONE:
        raise ValueError("Weighted criterion weights must total 1.0")


def calculate_readiness(
    criteria: Iterable[CriterionEvaluation], minimum_weighted_score: Decimal
) -> GateSummary:
    items = list(criteria)
    if not ZERO <= minimum_weighted_score <= HUNDRED:
        raise ValueError("minimum_weighted_score must be between 0 and 100")
    validate_weight_configuration(items, minimum_weighted_score)

    hard_gates = [item for item in items if item.definition.hard_gate]
    gate_verdicts = {item.definition.code: item.verdict for item in hard_gates}
    passed = sum(verdict == GateVerdict.PASSED for verdict in gate_verdicts.values())
    hard_gate_readiness = safe_ratio(passed, len(hard_gates))

    weighted = [item for item in items if item.definition.weight is not None]
    if weighted:
        weighted_score = HUNDRED * sum(
            (
                (item.definition.weight or ZERO)
                * (
                    item.normalized_score
                    if item.complete and item.normalized_score is not None
                    else ZERO
                )
                for item in weighted
            ),
            ZERO,
        )
        weighted_readiness = (
            ONE
            if minimum_weighted_score == ZERO
            else min(weighted_score / minimum_weighted_score, ONE)
        )
    else:
        weighted_score = None
        weighted_readiness = ONE

    sample_completeness = safe_mean(
        (
            ONE
            if item.definition.minimum_samples == 0
            else min(safe_ratio(item.sample_count, item.definition.minimum_samples), ONE)
        )
        for item in items
    )
    evaluation_completeness = safe_ratio(sum(item.complete for item in items), len(items))
    readiness_percentage = Decimal("25") * (
        hard_gate_readiness + weighted_readiness + sample_completeness + evaluation_completeness
    )
    hard_gates_pass = all(verdict == GateVerdict.PASSED for verdict in gate_verdicts.values())
    weighted_pass = weighted_score is None or weighted_score >= minimum_weighted_score
    return GateSummary(
        hard_gate_readiness=hard_gate_readiness,
        weighted_score=weighted_score,
        weighted_readiness=weighted_readiness,
        sample_completeness=sample_completeness,
        evaluation_completeness=evaluation_completeness,
        readiness_percentage=readiness_percentage,
        promotion_evidence_eligible=hard_gates_pass
        and weighted_pass
        and evaluation_completeness == ONE
        and sample_completeness == ONE,
        gate_verdicts={key: value for key, value in gate_verdicts.items() if value is not None},
    )
