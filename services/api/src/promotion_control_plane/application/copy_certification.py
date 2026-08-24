import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from openai import OpenAI
from pydantic import BaseModel, Field

from promotion_control_plane.domain.hashing import content_hash
from promotion_control_plane.settings import get_settings


@dataclass(frozen=True, slots=True)
class CopyCertification:
    status: str
    purpose: str | None
    event: str | None
    button_effects: dict[str, str]
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class GovernedCopyAction:
    label: str
    consequence: str
    undo: str


@dataclass(frozen=True, slots=True)
class GovernedCopyArtifact:
    purpose: str
    event: str
    actions: tuple[GovernedCopyAction, ...]

    def render(self) -> str:
        action_lines = [
            f"{action.label}: {action.consequence} Undo: {action.undo}" for action in self.actions
        ]
        return "\n".join((self.purpose, self.event, *action_lines))


@dataclass(frozen=True, slots=True)
class GovernedCopyCase:
    screen: str
    artifact_digest: str
    copy: GovernedCopyArtifact

    @property
    def buttons(self) -> tuple[str, ...]:
        return tuple(action.label for action in self.copy.actions)


class CopySemanticResponse(BaseModel):
    purpose: str = Field(min_length=1, max_length=1000)
    event: str = Field(min_length=1, max_length=1000)
    button_effects: dict[str, str]
    passed: bool
    result: Literal["certified", "failed"]


class CopySemanticProvider(Protocol):
    def certify(
        self, copy: str | GovernedCopyArtifact, buttons: tuple[str, ...] = ()
    ) -> CopyCertification: ...


class StrictFakeCopySemanticProvider:
    def certify(
        self, copy: str | GovernedCopyArtifact, buttons: tuple[str, ...] = ()
    ) -> CopyCertification:
        if isinstance(copy, GovernedCopyArtifact):
            if not copy.purpose.strip() or not copy.event.strip():
                return CopyCertification(
                    "FAILED", None, None, {}, "Purpose and event are required."
                )
            structured_effects: dict[str, str] = {}
            for action in copy.actions:
                if not action.consequence.strip() or not action.undo.strip():
                    return CopyCertification(
                        "FAILED",
                        copy.purpose,
                        copy.event,
                        {},
                        "Every action needs consequence and undo.",
                    )
                structured_effects[action.label] = f"{action.consequence} Undo: {action.undo}"
            if buttons and set(buttons) != set(structured_effects):
                return CopyCertification(
                    "FAILED",
                    copy.purpose,
                    copy.event,
                    structured_effects,
                    "Actions differ from buttons.",
                )
            return CopyCertification("CERTIFIED", copy.purpose, copy.event, structured_effects)

        lines = [line.strip() for line in copy.splitlines() if line.strip()]
        if len(lines) < 2:
            return CopyCertification("FAILED", None, None, {}, "Two opening lines are required.")
        if len(lines[0].split()) < 3 or len(lines[1].split()) < 3:
            return CopyCertification(
                "FAILED", lines[0], lines[1], {}, "Purpose and event need context."
            )
        sentences = [
            sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+|\n", copy) if sentence.strip()
        ]
        effects: dict[str, str] = {}
        for button in buttons:
            matching = [
                sentence for sentence in sentences if button.casefold() in sentence.casefold()
            ]
            if not matching:
                return CopyCertification(
                    "FAILED", lines[0], lines[1], effects, "Button effect is missing."
                )
            index = sentences.index(matching[0])
            context = " ".join(sentences[index : index + 2])
            if not re.search(
                r"\b(undo|revers|permanent|unavailable|restore|cancel)\w*\b", context, re.I
            ):
                return CopyCertification(
                    "FAILED", lines[0], lines[1], effects, "Action undo is missing."
                )
            effects[button] = context
        return CopyCertification("CERTIFIED", lines[0], lines[1], effects)


class OpenAICopySemanticProvider:
    def __init__(self, client: Any | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.client = client
        if self.client is None and settings.openai_api_key:
            self.client = OpenAI(api_key=settings.openai_api_key)
        self.model = model or settings.openai_eval_model

    def certify(
        self, copy: str | GovernedCopyArtifact, buttons: tuple[str, ...] = ()
    ) -> CopyCertification:
        deterministic = StrictFakeCopySemanticProvider().certify(copy, buttons)
        if deterministic.status != "CERTIFIED":
            return deterministic
        if self.client is None:
            return CopyCertification(
                "UNAVAILABLE",
                deterministic.purpose,
                deterministic.event,
                deterministic.button_effects,
                "OPENAI_API_KEY is not configured; no certification was claimed.",
            )
        rendered = copy.render() if isinstance(copy, GovernedCopyArtifact) else copy
        try:
            response = self.client.responses.parse(
                model=self.model,
                store=False,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "You are a context-free interface-copy evaluator. Use only the supplied "
                            "copy. State the screen purpose, what happened or is true now, and the "
                            "effect and undo behavior of every named button. Return button_effects "
                            "with exactly the supplied button labels. Mark passed only when every "
                            "answer is clear from the copy."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"rendered_copy": rendered, "buttons": buttons}, sort_keys=True
                        ),
                    },
                ],
                text_format=CopySemanticResponse,
            )
        except Exception as error:
            return CopyCertification(
                "FAILED",
                deterministic.purpose,
                deterministic.event,
                {},
                f"Live semantic evaluator failed: {type(error).__name__}.",
            )
        parsed = response.output_parsed
        if parsed is None:
            return CopyCertification(
                "FAILED", None, None, {}, "Live semantic evaluator returned no structured result."
            )
        expected_buttons = set(buttons)
        returned_buttons = set(parsed.button_effects)
        valid_effects = returned_buttons == expected_buttons and all(
            value.strip() for value in parsed.button_effects.values()
        )
        status = (
            "CERTIFIED"
            if parsed.passed and parsed.result == "certified" and valid_effects
            else "FAILED"
        )
        return CopyCertification(
            status,
            parsed.purpose,
            parsed.event,
            parsed.button_effects,
            None
            if status == "CERTIFIED"
            else "Live semantic evaluator did not certify every governed action.",
        )


def _governed_copy_path() -> Path:
    configured = Path(get_settings().config_root) / "copy" / "governed-copy.json"
    if configured.is_file():
        return configured
    return Path(__file__).resolve().parents[5] / "configs" / "copy" / "governed-copy.json"


def load_governed_copy_cases(path: Path | None = None) -> tuple[GovernedCopyCase, ...]:
    source = path or _governed_copy_path()
    payload = json.loads(source.read_text(encoding="utf-8"))
    body = payload.get("body")
    digest = payload.get("digest")
    if not isinstance(body, dict) or not isinstance(digest, str):
        raise ValueError("Governed copy artifact must contain a body and digest.")
    if digest != f"sha256:{content_hash(body)}":
        raise ValueError("Governed copy artifact digest does not match its body.")
    screens = body.get("screens")
    actions = body.get("actions")
    semantic_cases = payload.get("semantic_cases")
    if not isinstance(screens, dict) or not isinstance(actions, dict):
        raise ValueError("Governed copy artifact must define screens and actions.")
    if not isinstance(semantic_cases, list):
        raise ValueError("Governed copy artifact must define semantic cases.")

    cases: list[GovernedCopyCase] = []
    covered_actions: set[str] = set()
    for raw_case in semantic_cases:
        if not isinstance(raw_case, dict):
            raise ValueError("Every semantic case must be an object.")
        screen_key = raw_case.get("screen")
        action_keys = raw_case.get("actions")
        if not isinstance(screen_key, str) or screen_key not in screens:
            raise ValueError("Every semantic case must name a governed screen.")
        if not isinstance(action_keys, list) or not all(
            isinstance(action_key, str) and action_key in actions for action_key in action_keys
        ):
            raise ValueError("Every semantic case action must name governed action copy.")
        screen = screens[screen_key]
        if not isinstance(screen, dict):
            raise ValueError("Every governed screen must be an object.")
        governed_actions: list[GovernedCopyAction] = []
        for action_key in action_keys:
            action = actions[action_key]
            if not isinstance(action, dict):
                raise ValueError("Every governed action must be an object.")
            governed_actions.append(
                GovernedCopyAction(
                    label=str(action["label"]),
                    consequence=str(action["consequence"]),
                    undo=str(action["undo"]),
                )
            )
            covered_actions.add(action_key)
        cases.append(
            GovernedCopyCase(
                screen=screen_key,
                artifact_digest=digest,
                copy=GovernedCopyArtifact(
                    purpose=str(screen["line1"]),
                    event=str(screen["line2"]),
                    actions=tuple(governed_actions),
                ),
            )
        )

    if {case.screen for case in cases} != set(screens):
        raise ValueError("Semantic cases must cover every governed screen exactly once.")
    if covered_actions != set(actions):
        raise ValueError("Semantic cases must cover every governed action.")
    return tuple(cases)


def live_copy_certification(
    copy: str | GovernedCopyArtifact, buttons: tuple[str, ...] = ()
) -> CopyCertification:
    return OpenAICopySemanticProvider().certify(copy, buttons)
