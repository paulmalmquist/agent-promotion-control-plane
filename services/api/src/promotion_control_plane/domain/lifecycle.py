from collections.abc import Sequence

DEFAULT_LIFECYCLE_STAGES = (
    "DISCOVERED",
    "CANDIDATE",
    "EVALUATING",
    "ELIGIBLE",
    "SHADOW",
    "PROMOTED",
    "MONITORED",
)

# Policies may omit these stages without weakening a safety boundary. The
# transition validator never permits backward movement or skipping a gate-
# bearing stage such as EVALUATING or ELIGIBLE.
OPTIONAL_STAGES = frozenset({"CANDIDATE", "SHADOW"})


def validate_lifecycle_transition(
    current: str,
    target: str,
    configured_stages: Sequence[str] | None = None,
) -> None:
    stages = tuple(configured_stages or DEFAULT_LIFECYCLE_STAGES)
    if len(stages) != len(set(stages)):
        raise ValueError("Lifecycle stages must be unique")
    if current not in stages or target not in stages:
        raise ValueError(f"Lifecycle transition uses an unconfigured stage: {current} -> {target}")
    if current == target:
        return
    current_index = stages.index(current)
    target_index = stages.index(target)
    if target_index < current_index:
        raise ValueError(f"Lifecycle cannot move backward: {current} -> {target}")
    skipped = stages[current_index + 1 : target_index]
    if any(stage not in OPTIONAL_STAGES for stage in skipped):
        raise ValueError(f"Lifecycle cannot skip required stages: {current} -> {target}")
