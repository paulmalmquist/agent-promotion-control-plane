from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TypedMeasurement:
    metric: str
    normalized_score: Decimal
    sample_count: int
    evidence_codes: tuple[str, ...]
    metadata: dict[str, Any]
    measurement_value: Decimal | None = None
    measurement_unit: str | None = None
    measurement_type: str = "number"


@dataclass(frozen=True, slots=True)
class RegistryPublication:
    external_version_id: str
    metadata: dict[str, Any]


class CandidateSource(Protocol):
    def list_candidate_signals(self) -> list[dict[str, Any]]: ...


class CandidateDetector(Protocol):
    key: str

    def detect(self, signals: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


class EvaluationSource(Protocol):
    def load(self, candidate_id: UUID, configuration: dict[str, Any]) -> dict[str, Any]: ...


class EvaluatorProvider(Protocol):
    key: str

    def evaluate(
        self, inputs: dict[str, Any], configuration: dict[str, Any]
    ) -> TypedMeasurement: ...


class PromotionRegistry(Protocol):
    def publish(self, publication_token: str, snapshot: dict[str, Any]) -> RegistryPublication: ...


class ScheduleSource(Protocol):
    def list_schedules(self) -> list[dict[str, Any]]: ...


class ArtifactStore(Protocol):
    def put(self, content: bytes, media_type: str) -> tuple[str, str]: ...


class EventSink(Protocol):
    def deliver(self, event: dict[str, Any]) -> None: ...
