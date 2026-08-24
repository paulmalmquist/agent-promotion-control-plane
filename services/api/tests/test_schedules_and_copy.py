import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from promotion_control_plane.application.copy_certification import (
    CopySemanticResponse,
    GovernedCopyAction,
    GovernedCopyArtifact,
    OpenAICopySemanticProvider,
    StrictFakeCopySemanticProvider,
    load_governed_copy_cases,
)
from promotion_control_plane.application.schedules import connection_message, next_expected_trigger


def test_next_expected_trigger_respects_spring_dst_gap() -> None:
    result = next_expected_trigger(
        "30 2 * * *", "America/New_York", datetime(2026, 3, 8, 6, 0, tzinfo=UTC)
    )
    assert result == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)


def test_next_expected_trigger_respects_fall_dst_boundary() -> None:
    result = next_expected_trigger(
        "30 1 * * *", "America/New_York", datetime(2026, 10, 31, 6, 0, tzinfo=UTC)
    )
    assert result == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)


def test_connection_copy_never_claims_resident_scheduler_ownership() -> None:
    assert "only observes" in connection_message("CONNECTED")
    assert "will not run automatically" in connection_message("DISCONNECTED")


def test_strict_fake_copy_certification_checks_context_and_buttons() -> None:
    copy = "Review this promotion decision.\nRegistry activation is pending.\nApprove changes selection. Undo is unavailable."
    certification = StrictFakeCopySemanticProvider().certify(copy, ("Approve",))
    assert certification.status == "CERTIFIED"
    assert certification.button_effects["Approve"]


def test_live_copy_certification_is_unavailable_without_credentials(monkeypatch: object) -> None:
    from promotion_control_plane import settings

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # type: ignore[attr-defined]
    settings.get_settings.cache_clear()
    certification = OpenAICopySemanticProvider().certify(
        "Review governed promotion copy.\nRegistry activation remains pending.", ()
    )
    assert certification.status == "UNAVAILABLE"
    assert certification.status != "CERTIFIED"


def test_structured_copy_requires_consequence_and_undo() -> None:
    valid = GovernedCopyArtifact(
        "Review this promotion decision.",
        "Registry activation is pending.",
        (
            GovernedCopyAction(
                "Approve", "Queues registry publication.", "Cannot be undone after queueing."
            ),
        ),
    )
    assert StrictFakeCopySemanticProvider().certify(valid, ("Approve",)).status == "CERTIFIED"
    missing_undo = GovernedCopyArtifact(
        valid.purpose,
        valid.event,
        (GovernedCopyAction("Approve", "Queues registry publication.", ""),),
    )
    assert StrictFakeCopySemanticProvider().certify(missing_undo, ("Approve",)).status == "FAILED"


def test_shared_governed_artifact_certifies_every_screen_and_action() -> None:
    cases = load_governed_copy_cases()
    digests = {case.artifact_digest for case in cases}

    assert len(cases) == 12
    assert len(digests) == 1
    for case in cases:
        certification = StrictFakeCopySemanticProvider().certify(case.copy, case.buttons)
        assert certification.status == "CERTIFIED", case.screen
        assert set(certification.button_effects) == set(case.buttons)


def test_openai_copy_provider_returns_structured_model_inferences() -> None:
    calls: list[dict[str, Any]] = []

    class FakeResponses:
        def parse(self, **kwargs: Any) -> Any:
            calls.append(kwargs)
            request = json.loads(kwargs["input"][1]["content"])
            return SimpleNamespace(
                output_parsed=CopySemanticResponse(
                    purpose="Model-derived screen purpose.",
                    event="Model-derived current event.",
                    button_effects={
                        button: f"Model-derived effect and undo for {button}."
                        for button in request["buttons"]
                    },
                    passed=True,
                    result="certified",
                )
            )

    client = SimpleNamespace(responses=FakeResponses())
    case = next(case for case in load_governed_copy_cases() if case.screen == "candidate")
    certification = OpenAICopySemanticProvider(client=client, model="test-model").certify(
        case.copy, case.buttons
    )

    assert certification.status == "CERTIFIED"
    assert certification.purpose == "Model-derived screen purpose."
    assert certification.event == "Model-derived current event."
    assert set(certification.button_effects) == set(case.buttons)
    assert calls[0]["store"] is False
    assert calls[0]["text_format"] is CopySemanticResponse
