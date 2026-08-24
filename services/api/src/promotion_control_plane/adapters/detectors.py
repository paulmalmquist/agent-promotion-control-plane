from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class DeterministicSignalDetector:
    key: str
    signal_type: str
    field: str
    threshold: Decimal

    def detect(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        for signal in signals:
            score = Decimal(str(signal.get(self.field, 0)))
            if score >= self.threshold:
                found.append(
                    {
                        "signal_type": self.signal_type,
                        "score": str(score),
                        "source_id": signal.get("id"),
                        "evidence": {self.field: signal.get(self.field)},
                    }
                )
        return found


DETERMINISTIC_DETECTORS = (
    DeterministicSignalDetector(
        "repeated-skill-success",
        "REPEATED_SUCCESSFUL_SKILL_USAGE",
        "successful_skill_uses",
        Decimal("5"),
    ),
    DeterministicSignalDetector(
        "recurring-multi-skill", "RECURRING_MULTI_SKILL_WORKFLOW", "multi_skill_runs", Decimal("3")
    ),
    DeterministicSignalDetector(
        "manual-invocation", "HIGH_MANUAL_INVOCATION_FREQUENCY", "manual_invocations", Decimal("8")
    ),
    DeterministicSignalDetector(
        "human-workaround", "REPEATED_HUMAN_WORKAROUND", "workaround_count", Decimal("3")
    ),
    DeterministicSignalDetector(
        "evaluation-history", "STRONG_EVALUATION_HISTORY", "evaluation_pass_rate", Decimal("0.9")
    ),
    DeterministicSignalDetector(
        "coverage-gap", "CAPABILITY_COVERAGE_GAP", "coverage_gap_score", Decimal("0.7")
    ),
    DeterministicSignalDetector(
        "operational-trigger",
        "RECURRING_OPERATIONAL_TRIGGER",
        "recurring_trigger_count",
        Decimal("3"),
    ),
    DeterministicSignalDetector(
        "skill-bundle", "STABLE_SKILL_BUNDLE_SYNTHESIS", "bundle_stability", Decimal("0.9")
    ),
)


class PersistedEvidenceRanker:
    """Ranks persisted deterministic evidence; it cannot create new evidence."""

    key = "persisted-evidence-ranker"

    def detect(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        required = ("signal_type", "score", "source_id", "evidence")
        validated = [dict(item) for item in signals if all(field in item for field in required)]
        return sorted(
            validated, key=lambda item: (-Decimal(str(item["score"])), str(item["source_id"]))
        )
