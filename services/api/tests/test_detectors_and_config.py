from pathlib import Path

import pytest

from promotion_control_plane.adapters.detectors import (
    DETERMINISTIC_DETECTORS,
    PersistedEvidenceRanker,
)
from promotion_control_plane.infrastructure.config import load_artifact


def test_all_locked_deterministic_signal_types_are_implemented() -> None:
    assert {detector.signal_type for detector in DETERMINISTIC_DETECTORS} == {
        "REPEATED_SUCCESSFUL_SKILL_USAGE",
        "RECURRING_MULTI_SKILL_WORKFLOW",
        "HIGH_MANUAL_INVOCATION_FREQUENCY",
        "REPEATED_HUMAN_WORKAROUND",
        "STRONG_EVALUATION_HISTORY",
        "CAPABILITY_COVERAGE_GAP",
        "RECURRING_OPERATIONAL_TRIGGER",
        "STABLE_SKILL_BUNDLE_SYNTHESIS",
    }


def test_detector_output_is_deterministic() -> None:
    detector = DETERMINISTIC_DETECTORS[0]
    signals = [{"id": "a", "successful_skill_uses": 7}]
    assert detector.detect(signals) == detector.detect(signals)
    assert detector.detect(signals)[0]["source_id"] == "a"


def test_ranker_only_ranks_complete_persisted_evidence() -> None:
    persisted = {
        "signal_type": "A",
        "score": "0.8",
        "source_id": "persisted-1",
        "evidence": {"row": 1},
    }
    invented = {"signal_type": "B", "score": "1"}
    assert PersistedEvidenceRanker().detect([invented, persisted]) == [persisted]


def test_every_checked_in_configuration_artifact_validates_and_hashes() -> None:
    config_root = Path(__file__).resolve().parents[3] / "configs"
    paths = sorted(config_root.rglob("*.yaml"))
    assert len(paths) >= 5
    for path in paths:
        artifact, digest = load_artifact(path)
        assert artifact.schema_version == 1
        assert len(digest) == 64
        assert digest == load_artifact(path)[1]


def test_invalid_nonzero_empty_weight_policy_is_rejected(tmp_path: Path) -> None:
    artifact = tmp_path / "invalid.yaml"
    artifact.write_text(
        """
schema_version: 1
policy_id: invalid
version: 1.0.0
title: Invalid
applicable_candidate_types: [workflow]
target_stage: PROMOTED
lifecycle_stages: [DISCOVERED, PROMOTED]
minimum_weighted_score: 80
required_lifecycle_approvals: 0
regression_tolerance: 0
post_promotion_observation: {required_runs: 0, review_after_hours: 0}
criteria: []
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="nonzero threshold"):
        load_artifact(artifact)
