from promotion_control_plane.application.errors import conflict
from promotion_control_plane.domain.lifecycle import validate_lifecycle_transition
from promotion_control_plane.infrastructure.models import Candidate, Policy

MUTATION_STOP_STATUSES = frozenset({"PROMOTION_PENDING", "SUSPENDED", "RETIRED", "REJECTED"})
MUTATION_STOP_STAGES = frozenset({"PROMOTED", "MONITORED"})
DERIVED_EVALUATION_BLOCKER_CODES = frozenset(
    {
        "HARD_GATE_FAILED",
        "EVALUATION_REQUIREMENTS_INCOMPLETE",
        "EVALUATION_PROVIDER_FAILED",
        "ACTIVE_PLAN_POLICY_MISMATCH",
        "EVALUATION_RETRIES_EXHAUSTED",
    }
)


def require_evaluation_mutable(candidate: Candidate) -> None:
    if candidate.status in MUTATION_STOP_STATUSES or candidate.stage in MUTATION_STOP_STAGES:
        raise conflict(
            "CANDIDATE_LIFECYCLE_LOCKED",
            "Evaluation cannot replace evidence while promotion, monitoring, or a terminal state is active.",
            stage=candidate.stage,
            status=candidate.status,
        )


def require_transition(candidate: Candidate, policy: Policy, target: str) -> None:
    try:
        validate_lifecycle_transition(candidate.stage, target, policy.lifecycle_stages)
    except ValueError as error:
        raise conflict(
            "ILLEGAL_LIFECYCLE_TRANSITION",
            str(error),
            current_stage=candidate.stage,
            target_stage=target,
        ) from error
