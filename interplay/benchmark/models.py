"""Flat versioned benchmark contracts; all model-call budgets are explicit."""

import hashlib
import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ..assessment.http import payload
from ..assessment.models import JudgeOutput, ModelEndpoint, Observation, StrictModel, Text, Verdict
from ..assessment.runner import evidence_supported
from ..assessment.storage import json_bytes
from ..calibration.models import Digest, Identifier
from ..report import _json


def digest(value):
    return hashlib.sha256(json_bytes(value)).hexdigest()


def profile(value):
    data = _json(value)
    if not isinstance(data, dict) or set(data) != {"endpoint", "extra_body_json"}:
        raise ValueError("benchmark-profile-invalid")
    endpoint = ModelEndpoint.model_validate(data["endpoint"])
    if endpoint.model is None:
        raise ValueError("benchmark-model-required")
    extra = _json(data["extra_body_json"])
    if not isinstance(extra, dict) or len(json_bytes(extra)) > 16384:
        raise ValueError("benchmark-extra-body-invalid")
    payload(endpoint, [], extra)
    return endpoint, extra


class BenchmarkCase(StrictModel):
    schema_version: Literal["interplay-benchmark-case/1"] = "interplay-benchmark-case/1"
    case_id: Identifier
    goal: Text
    prompt: Text
    messages_json: str | None = None

    @model_validator(mode="after")
    def fixed_history(self):
        self.messages()
        return self

    def messages(self):
        if self.messages_json is None:
            return [{"role": "user", "content": self.prompt}]
        messages = _json(self.messages_json)
        if (
            not isinstance(messages, list)
            or not 1 <= len(messages) <= 21
            or any(
                not isinstance(m, dict)
                or set(m) != {"role", "content"}
                or m["role"] not in ("system", "user", "assistant")
                or not isinstance(m["content"], str)
                or not 1 <= len(m["content"]) <= 16384
                for m in messages
            )
            or messages[-1] != {"role": "user", "content": self.prompt}
        ):
            raise ValueError("benchmark-fixed-history-invalid")
        return messages

    def digest(self):
        return digest(self.model_dump())


class Manifest(StrictModel):
    schema_version: Literal["interplay-benchmark/1"] = "interplay-benchmark/1"
    suite_id: Identifier
    method: Literal["fixed-probe"] = "fixed-probe"
    cases_sha256: Digest
    source_revision: Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
    implementation_sha256: Digest
    baseline_json: Annotated[str, Field(max_length=32768)]
    candidate_json: Annotated[str, Field(max_length=32768)]
    judge_json: Annotated[str, Field(max_length=32768)] | None = None
    repeats: Annotated[int, Field(ge=1, le=10)] = 1
    max_cases: Annotated[int, Field(ge=1, le=1000)] = 5
    campaign_seconds_per_variant: Annotated[int, Field(ge=1, le=3600)] = 600
    method_parameters_json: str = (
        '{"target_queries_per_case":1,"retry_policy":"none","order":"alternate-per-case-repeat"}'
    )

    @model_validator(mode="after")
    def equal_budgets(self):
        baseline, _ = profile(self.baseline_json)
        candidate, _ = profile(self.candidate_json)
        if (
            baseline.max_tokens != candidate.max_tokens
            or baseline.request_seconds != candidate.request_seconds
        ):
            raise ValueError("benchmark-equal-request-budgets-required")
        if self.judge_json is not None:
            profile(self.judge_json)
        if _json(self.method_parameters_json) != {
            "target_queries_per_case": 1,
            "retry_policy": "none",
            "order": "alternate-per-case-repeat",
        }:
            raise ValueError("benchmark-unsupported-method-parameters")
        return self

    def digest(self):
        return digest(self.model_dump())


class BenchmarkRecord(StrictModel):
    schema_version: Literal["interplay-benchmark-record/1"] = "interplay-benchmark-record/1"
    manifest_sha256: Digest
    profile_sha256: Digest
    case_id: Identifier
    case_sha256: Digest
    repeat_index: Annotated[int, Field(ge=0, le=9)]
    variant: Literal["baseline", "candidate"]
    status: Literal["complete", "incomplete", "not-run"]
    terminal: bool = False
    response: str | None = None
    capture_complete: bool = False
    judge_verdict: Verdict = "inconclusive"
    judge_reasoning: str | None = None
    evidence_refs_json: str = "[]"
    raw_judge_json: str | None = None
    error_code: str | None = None
    # Calls are unavailable on legacy imports, not inferred from response presence.
    target_calls: Annotated[int, Field(ge=0, le=1)] | None = None
    judge_calls: Annotated[int, Field(ge=0, le=1)] | None = None
    target_latency_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    judge_latency_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    usage_json: str = "{}"
    source_json: str = "{}"

    @model_validator(mode="after")
    def measurements_and_judgment(self):
        usage = _json(self.usage_json)
        if not isinstance(usage, dict) or set(usage) - {"target", "judge"}:
            raise ValueError("benchmark-usage-invalid")
        for values in usage.values():
            if values is None:
                continue
            if not isinstance(values, dict) or set(values) - {
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "cost_usd",
            }:
                raise ValueError("benchmark-usage-invalid")
            for key, value in values.items():
                if value is not None and (
                    type(value) not in ((int, float) if key == "cost_usd" else (int,))
                    or not 0 <= value <= (1e100 if key == "cost_usd" else 2**63 - 1)
                    or not math.isfinite(value)
                ):
                    raise ValueError("benchmark-usage-invalid")
        if not isinstance(_json(self.source_json), dict):
            raise ValueError("benchmark-source-invalid")
        if self.judge_verdict != "inconclusive":
            judgment = JudgeOutput(
                verdict=self.judge_verdict,
                reasoning=self.judge_reasoning or "Not retained",
                evidence_refs_json=self.evidence_refs_json,
            )
            if (
                self.status != "complete"
                or not self.capture_complete
                or not evidence_supported(judgment, Observation(response=self.response))
            ):
                raise ValueError("benchmark-unsupported-judgment")
        return self
