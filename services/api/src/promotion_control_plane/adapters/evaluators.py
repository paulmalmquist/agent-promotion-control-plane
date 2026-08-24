import hashlib
import json
import subprocess
from decimal import Decimal
from typing import Any, Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from promotion_control_plane.adapters.protocols import ArtifactStore, TypedMeasurement
from promotion_control_plane.domain.hashing import content_hash
from promotion_control_plane.settings import get_settings


class DeterministicRuleEvaluator:
    key = "deterministic-rule"

    def evaluate(self, inputs: dict[str, Any], configuration: dict[str, Any]) -> TypedMeasurement:
        field = str(configuration["field"])
        maximum = Decimal(str(configuration.get("maximum", 1)))
        value = Decimal(str(inputs.get(field, 0)))
        normalized = (
            Decimal(str(configuration["normalized_score"]))
            if "normalized_score" in configuration
            else min(max(value / maximum, Decimal(0)), Decimal(1))
            if maximum
            else Decimal(1)
        )
        return TypedMeasurement(
            field,
            normalized,
            int(inputs.get("sample_count", 1)),
            tuple(configuration.get("evidence_codes", ())),
            {"value": str(value), "provider": self.key},
            measurement_value=value,
            measurement_unit=configuration.get("unit"),
        )


class TestSuiteEvaluator:
    key = "allow-listed-test-suite"

    def __init__(self, allowlist: dict[str, tuple[str, ...]]) -> None:
        self.allowlist = allowlist

    def evaluate(self, inputs: dict[str, Any], configuration: dict[str, Any]) -> TypedMeasurement:
        suite = str(configuration["suite"])
        if suite not in self.allowlist:
            raise ValueError("Test suite is not allow-listed")
        completed = subprocess.run(
            self.allowlist[suite], check=False, capture_output=True, text=True, timeout=120
        )
        score = Decimal(1 if completed.returncode == 0 else 0)
        return TypedMeasurement(
            "test_suite",
            score,
            1,
            ("test-output",),
            {"suite": suite, "exit_code": completed.returncode},
            measurement_value=score,
        )


class SyntheticMetricEvaluator:
    key = "synthetic-metric"

    def evaluate(self, inputs: dict[str, Any], configuration: dict[str, Any]) -> TypedMeasurement:
        metric = str(configuration["metric"])
        values = [Decimal(str(value)) for value in inputs.get("values", [])]
        if not values:
            score = Decimal(1)
        else:
            score = min(max(sum(values) / Decimal(len(values)), Decimal(0)), Decimal(1))
        return TypedMeasurement(
            metric,
            score,
            len(values),
            tuple(configuration.get("evidence_codes", ())),
            {"deterministic": True},
            measurement_value=score,
            measurement_unit=configuration.get("unit"),
        )


class RubricResponse(BaseModel):
    score: float = Field(ge=0, le=1)
    evidence_codes: list[str]
    explanation: str
    result: Literal["measured"] = "measured"


class OpenAIRubricEvaluator:
    key = "openai-rubric"

    def __init__(
        self, client: OpenAI | None = None, artifact_store: ArtifactStore | None = None
    ) -> None:
        settings = get_settings()
        if client is None and not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for live rubric evaluation")
        self.client = client or OpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_eval_model
        self.artifact_store = artifact_store

    def evaluate(self, inputs: dict[str, Any], configuration: dict[str, Any]) -> TypedMeasurement:
        sanitized_input = json.dumps(inputs, sort_keys=True)[:20_000]
        input_hash = hashlib.sha256(sanitized_input.encode()).hexdigest()
        rubric = str(configuration["rubric"])
        rubric_version = str(configuration.get("rubric_version", "1.0.0"))
        response = self.client.responses.parse(
            model=self.model,
            store=False,
            input=[
                {"role": "system", "content": rubric},
                {"role": "user", "content": sanitized_input},
            ],
            text_format=RubricResponse,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise RuntimeError("Rubric provider returned no structured measurement")
        raw_digest = hashlib.sha256(response.model_dump_json().encode()).hexdigest()
        usage = response.usage.model_dump() if response.usage else {}
        safe_explanation = " ".join(parsed.explanation.split())[:2000]
        sanitized_artifact = {
            "schema_version": 1,
            "score": parsed.score,
            "evidence_codes": sorted(parsed.evidence_codes),
            "explanation": safe_explanation,
            "model": self.model,
            "usage": usage,
            "input_hash": input_hash,
            "rubric_hash": content_hash({"rubric": rubric, "version": rubric_version}),
            "rubric_version": rubric_version,
            "raw_response_digest": raw_digest,
        }
        artifact_metadata: dict[str, Any] = {"sanitized_artifact": sanitized_artifact}
        if self.artifact_store is not None:
            artifact_uri, artifact_sha = self.artifact_store.put(
                json.dumps(sanitized_artifact, sort_keys=True).encode("utf-8"),
                "application/json",
            )
            artifact_metadata = {
                "sanitized_artifact_uri": artifact_uri,
                "sanitized_artifact_sha256": artifact_sha,
            }
        return TypedMeasurement(
            str(configuration.get("metric", "rubric")),
            Decimal(str(parsed.score)),
            int(inputs.get("sample_count", 1)),
            tuple(parsed.evidence_codes),
            {
                "model": self.model,
                "usage": usage,
                "store": False,
                "input_hash": input_hash,
                "rubric_version": rubric_version,
                "rubric_hash": sanitized_artifact["rubric_hash"],
                **artifact_metadata,
            },
            measurement_value=Decimal(str(parsed.score)),
        )
