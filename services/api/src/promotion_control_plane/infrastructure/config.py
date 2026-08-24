from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from promotion_control_plane.domain.hashing import content_hash
from promotion_control_plane.infrastructure.models import (
    Criterion,
    DetectorRevision,
    EvaluatorRevision,
    Policy,
    ScheduledJob,
)

CONFIG_NAMESPACE = uuid5(NAMESPACE_URL, "agent-promotion-control-plane:config:v1")


def _config_id(kind: str, artifact_id: str, version: str) -> UUID:
    return uuid5(CONFIG_NAMESPACE, f"{kind}:{artifact_id}:{version}")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CriterionConfig(StrictModel):
    criterion_id: str
    version: str = "1.0.0"
    title: str
    description: str | None = None
    category: str
    evaluator_type: str
    comparison_operator: Literal["gte", "gt", "lte", "lt", "eq"] = "gte"
    threshold: float
    hard_gate: bool = False
    weight: float | None = Field(default=None, ge=0, le=1)
    minimum_samples: int = Field(default=0, ge=0)
    required_evidence: list[str] = []
    aggregation_rule: Literal["sample_weighted_mean", "mean", "minimum", "maximum"] = (
        "sample_weighted_mean"
    )


class ObservationConfig(StrictModel):
    required_runs: int = Field(ge=0)
    review_after_hours: int = Field(ge=0)


class PolicyConfig(StrictModel):
    schema_version: int = 1
    policy_id: str
    version: str
    title: str
    applicable_candidate_types: list[str]
    target_stage: str
    lifecycle_stages: list[str]
    minimum_weighted_score: float = Field(ge=0, le=100)
    required_lifecycle_approvals: int = Field(default=0, ge=0)
    regression_tolerance: float = Field(ge=0)
    post_promotion_observation: ObservationConfig
    criteria: list[CriterionConfig]

    @model_validator(mode="after")
    def validate_weights(self) -> "PolicyConfig":
        weights = [criterion.weight for criterion in self.criteria if criterion.weight is not None]
        if weights and abs(sum(weights) - 1.0) > 0.000001:
            raise ValueError("weights must total 1.0 when weighted criteria exist")
        if not weights and self.minimum_weighted_score != 0:
            raise ValueError("nonzero threshold requires weighted criteria")
        return self


class DetectorEntry(StrictModel):
    detector_id: str
    signal_type: str
    minimum_observations: int = Field(ge=0)
    confidence_floor: float = Field(ge=0, le=1)


class AssistedRankingConfig(StrictModel):
    enabled: bool
    persisted_signals_only: bool
    may_create_evidence: bool

    @model_validator(mode="after")
    def cannot_invent(self) -> "AssistedRankingConfig":
        if not self.persisted_signals_only or self.may_create_evidence:
            raise ValueError("AI-assisted ranking may only rank persisted deterministic signals")
        return self


class DetectorSetConfig(StrictModel):
    schema_version: int = 1
    detector_set_id: str
    version: str
    detectors: list[DetectorEntry]
    ai_assisted_ranking: AssistedRankingConfig


class EvaluatorEntry(StrictModel):
    evaluator_id: str
    evaluator_type: str
    version: str
    enabled: bool | None = None
    allowlist: list[str] | None = None
    enabled_when_env: str | None = None
    model_env: str | None = None
    default_model: str | None = None
    strict_structured_output: bool | None = None
    store: bool | None = None


class EvaluatorSetConfig(StrictModel):
    schema_version: int = 1
    evaluator_set_id: str
    version: str
    evaluators: list[EvaluatorEntry]


class ScheduleEntry(StrictModel):
    job_id: str
    name: str
    purpose: str
    job_type: str
    cron_expression: str
    timezone: str
    trigger_owner: str
    trigger_mode: str
    owner_reference: str
    connection_state: str
    grace_window_minutes: int = Field(ge=0)


class ScheduleSetConfig(StrictModel):
    schema_version: int = 1
    schedule_set_id: str
    version: str
    notice: str
    jobs: list[ScheduleEntry]


ConfigArtifact = PolicyConfig | DetectorSetConfig | EvaluatorSetConfig | ScheduleSetConfig


def load_artifact(path: Path) -> tuple[ConfigArtifact, str]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a mapping")
    if "policy_id" in payload:
        artifact: ConfigArtifact = PolicyConfig.model_validate(payload)
    elif "detector_set_id" in payload:
        artifact = DetectorSetConfig.model_validate(payload)
    elif "evaluator_set_id" in payload:
        artifact = EvaluatorSetConfig.model_validate(payload)
    elif "schedule_set_id" in payload:
        artifact = ScheduleSetConfig.model_validate(payload)
    else:
        raise ValueError(f"Unsupported configuration artifact: {path}")
    return artifact, content_hash(artifact.model_dump(mode="json"))


def artifact_identity(artifact: ConfigArtifact) -> tuple[str, str]:
    if isinstance(artifact, PolicyConfig):
        return artifact.policy_id, artifact.version
    if isinstance(artifact, DetectorSetConfig):
        return artifact.detector_set_id, artifact.version
    if isinstance(artifact, EvaluatorSetConfig):
        return artifact.evaluator_set_id, artifact.version
    return artifact.schedule_set_id, artifact.version


def assert_identity_content(session: Session, artifact: ConfigArtifact, digest: str) -> None:
    artifact_id, version = artifact_identity(artifact)
    if isinstance(artifact, PolicyConfig):
        existing: Any = session.scalar(
            select(Policy).where(Policy.policy_key == artifact_id, Policy.version == version)
        )
    elif isinstance(artifact, DetectorSetConfig):
        existing = session.scalar(
            select(DetectorRevision).where(
                DetectorRevision.detector_key == artifact_id,
                DetectorRevision.version == version,
            )
        )
    elif isinstance(artifact, EvaluatorSetConfig):
        existing = session.scalar(
            select(EvaluatorRevision).where(
                EvaluatorRevision.evaluator_key == artifact_id,
                EvaluatorRevision.version == version,
            )
        )
    else:
        existing = session.scalar(
            select(ScheduledJob).where(
                ScheduledJob.version == version,
                ScheduledJob.metadata_snapshot["schedule_set_id"].astext == artifact_id,
            )
        )
    if existing is not None and existing.content_hash != digest:
        raise ValueError(f"{artifact_id}@{version} already exists with different content")


def load_config_directory(root: Path) -> list[tuple[ConfigArtifact, str]]:
    loaded = [load_artifact(path) for path in sorted(root.rglob("*.yaml"))]
    identities: dict[tuple[str, str, str], str] = {}
    for artifact, digest in loaded:
        artifact_id, version = artifact_identity(artifact)
        key = (type(artifact).__name__, artifact_id, version)
        if key in identities and identities[key] != digest:
            raise ValueError(f"{artifact_id}@{version} is defined with different content")
        identities[key] = digest
    return loaded


def import_config_directory(session: Session, root: Path, *, commit: bool = True) -> int:
    loaded = load_config_directory(root)
    inserted = 0
    for artifact, digest in loaded:
        assert_identity_content(session, artifact, digest)
        if isinstance(artifact, PolicyConfig):
            policy_existing = session.scalar(
                select(Policy).where(
                    Policy.policy_key == artifact.policy_id, Policy.version == artifact.version
                )
            )
            if policy_existing is not None:
                continue
            policy = Policy(
                id=_config_id("policy", artifact.policy_id, artifact.version),
                policy_key=artifact.policy_id,
                version=artifact.version,
                name=artifact.title,
                content_hash=digest,
                minimum_weighted_score=artifact.minimum_weighted_score,
                required_lifecycle_approvals=artifact.required_lifecycle_approvals,
                lifecycle_stages=artifact.lifecycle_stages,
                configuration=artifact.model_dump(mode="json"),
            )
            session.add(policy)
            session.flush()
            for ordinal, criterion_config in enumerate(artifact.criteria, start=1):
                criterion_payload = criterion_config.model_dump(mode="json")
                session.add(
                    Criterion(
                        id=_config_id(
                            "criterion",
                            f"{artifact.policy_id}:{criterion_config.criterion_id}",
                            criterion_config.version,
                        ),
                        policy_id=policy.id,
                        criterion_key=criterion_config.criterion_id,
                        version=criterion_config.version,
                        category=criterion_config.category,
                        evaluator_type=criterion_config.evaluator_type,
                        name=criterion_config.title,
                        description=criterion_config.description or criterion_config.title,
                        hard_gate=criterion_config.hard_gate,
                        threshold=criterion_config.threshold,
                        comparison_operator=criterion_config.comparison_operator,
                        weight=criterion_config.weight,
                        minimum_samples=criterion_config.minimum_samples,
                        required_evidence=criterion_config.required_evidence,
                        aggregation_rule=criterion_config.aggregation_rule,
                        content_hash=content_hash(criterion_payload),
                        ordinal=ordinal,
                    )
                )
            inserted += 1
        elif isinstance(artifact, DetectorSetConfig):
            detector_existing = session.scalar(
                select(DetectorRevision).where(
                    DetectorRevision.detector_key == artifact.detector_set_id,
                    DetectorRevision.version == artifact.version,
                )
            )
            if detector_existing is None:
                session.add(
                    DetectorRevision(
                        id=_config_id("detector-set", artifact.detector_set_id, artifact.version),
                        detector_key=artifact.detector_set_id,
                        version=artifact.version,
                        content_hash=digest,
                        configuration=artifact.model_dump(mode="json"),
                    )
                )
                inserted += 1
        elif isinstance(artifact, EvaluatorSetConfig):
            evaluator_existing = session.scalar(
                select(EvaluatorRevision).where(
                    EvaluatorRevision.evaluator_key == artifact.evaluator_set_id,
                    EvaluatorRevision.version == artifact.version,
                )
            )
            if evaluator_existing is None:
                session.add(
                    EvaluatorRevision(
                        id=_config_id("evaluator-set", artifact.evaluator_set_id, artifact.version),
                        evaluator_key=artifact.evaluator_set_id,
                        version=artifact.version,
                        evaluator_type="EVALUATOR_SET",
                        content_hash=digest,
                        configuration=artifact.model_dump(mode="json"),
                    )
                )
                inserted += 1
        else:
            for schedule_config in artifact.jobs:
                schedule_existing = session.scalar(
                    select(ScheduledJob).where(ScheduledJob.job_key == schedule_config.job_id)
                )
                if schedule_existing is not None:
                    if schedule_existing.content_hash != digest:
                        raise ValueError(
                            f"{schedule_config.job_id}@{artifact.version} already exists with different content"
                        )
                    continue
                session.add(
                    ScheduledJob(
                        id=_config_id("schedule", schedule_config.job_id, artifact.version),
                        job_key=schedule_config.job_id,
                        version=artifact.version,
                        content_hash=digest,
                        name=schedule_config.name,
                        description=schedule_config.purpose,
                        job_type=schedule_config.job_type,
                        enabled=True,
                        trigger_owner=schedule_config.trigger_owner,
                        trigger_mode=schedule_config.trigger_mode.upper(),
                        owner_reference=schedule_config.owner_reference,
                        connection_state=schedule_config.connection_state.upper(),
                        timezone=schedule_config.timezone,
                        schedule_expression=schedule_config.cron_expression,
                        grace_window_seconds=schedule_config.grace_window_minutes * 60,
                        metadata_snapshot={
                            "schedule_set_id": artifact.schedule_set_id,
                            "job_type": schedule_config.job_type,
                        },
                    )
                )
                inserted += 1
    if commit:
        session.commit()
    return inserted
