import os
from decimal import Decimal

import pytest

from promotion_control_plane.adapters.evaluators import OpenAIRubricEvaluator
from promotion_control_plane.application.copy_certification import (
    OpenAICopySemanticProvider,
    load_governed_copy_cases,
)
from promotion_control_plane.settings import get_settings

pytestmark = pytest.mark.live_openai


def require_openai_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not configured")
    get_settings.cache_clear()


def test_live_openai_rubric_returns_strict_typed_measurement() -> None:
    require_openai_key()
    measurement = OpenAIRubricEvaluator().evaluate(
        {"answer": "The policy requires exact authorization adherence.", "sample_count": 1},
        {
            "metric": "authorization_copy",
            "rubric_version": "1.0.0",
            "rubric": (
                "Return a measured response. Score 1 only if the answer explicitly requires exact "
                "authorization adherence; otherwise score 0."
            ),
        },
    )
    assert Decimal(0) <= measurement.normalized_score <= Decimal(1)
    assert measurement.metadata["model"]
    assert measurement.metadata["store"] is False
    assert len(measurement.metadata["input_hash"]) == 64
    assert len(measurement.metadata["rubric_hash"]) == 64


def test_live_openai_cold_read_certification_explains_every_action() -> None:
    require_openai_key()
    provider = OpenAICopySemanticProvider()
    for case in load_governed_copy_cases():
        certification = provider.certify(case.copy, case.buttons)
        assert certification.status == "CERTIFIED", (
            case.screen,
            case.artifact_digest,
            certification.reason,
        )
        assert certification.purpose
        assert certification.event
        assert set(certification.button_effects) == set(case.buttons)
