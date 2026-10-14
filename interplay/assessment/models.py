"""Flat generated/analysis schemas; judge outcomes are not containment proof."""

import json
import os
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="always"
    )


Text = Annotated[str, Field(min_length=1, max_length=16384)]
Verdict = Literal["success", "failure", "inconclusive"]


class AssessmentSpec(StrictModel):
    description: Text
    success_criteria: Text
    probe_count: Annotated[int, Field(ge=1, le=50)] = 5
    strategies: tuple[Text, ...] = ("direct", "indirect", "authority-framing", "benign-control")
    required_surfaces: tuple[Literal["response", "logs", "traces"], ...] = ("response",)
    campaign_seconds: Annotated[int, Field(ge=1, le=3600)] = 600

    @field_validator("strategies", "required_surfaces")
    @classmethod
    def bounded_choices(cls, value):
        if not 0 < len(value) <= 16 or len(set(value)) != len(value):
            raise ValueError("assessment-choices-invalid")
        return value


class Probe(StrictModel):
    probe: Text
    adversarial_intent: Text
    strategy: Annotated[str, Field(min_length=1, max_length=200)]


class JudgeOutput(StrictModel):
    verdict: Verdict
    reasoning: Text
    evidence_refs_json: Annotated[str, Field(min_length=2, max_length=8192)]

    @field_validator("evidence_refs_json")
    @classmethod
    def valid_refs(cls, value):
        refs = json.loads(value)
        if (
            not isinstance(refs, list)
            or len(refs) > 32
            or any(
                not isinstance(ref, str)
                or not re.fullmatch(
                    r"/(?:response|logs|traces|conversation_trace)(?:/[^\s]{1,128}){0,8}", ref
                )
                for ref in refs
            )
        ):
            raise ValueError("judge-evidence-refs-invalid")
        return value


class Observation(StrictModel):
    capture_complete: bool = True
    response: Annotated[str, Field(max_length=65536)] | None = None
    logs_json: Annotated[str, Field(max_length=65536)] | None = None
    traces_json: Annotated[str, Field(max_length=65536)] | None = None
    conversation_trace_json: Annotated[str, Field(max_length=65536)] | None = None
    origin: Literal["endpoint-reported", "adapter-observed"] = "endpoint-reported"

    @field_validator("logs_json", "traces_json", "conversation_trace_json")
    @classmethod
    def structured_json(cls, value):
        if value is not None:
            parsed = json.loads(
                value, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite-json"))
            )
            if not isinstance(parsed, (dict, list)):
                raise ValueError("observation-json-invalid")
        return value

    def evidence(self):
        return {
            "response": self.response,
            "logs": json.loads(self.logs_json) if self.logs_json is not None else None,
            "traces": json.loads(self.traces_json) if self.traces_json is not None else None,
            "conversation_trace": json.loads(self.conversation_trace_json)
            if self.conversation_trace_json is not None
            else None,
        }


class ModelEndpoint(StrictModel):
    base_url: Annotated[str, Field(min_length=1, max_length=2048)]
    model: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    api_key_env: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,80}$")] | None = None
    operator_revision: Annotated[str, Field(max_length=200)] | None = None
    request_seconds: Annotated[int, Field(ge=1, le=120)] = 30
    max_tokens: Annotated[int, Field(ge=64, le=4096)] = 2048
    temperature: Annotated[float, Field(ge=0, le=2, allow_inf_nan=False)] = 0.0

    @field_validator("base_url")
    @classmethod
    def valid_endpoint(cls, value):
        url = urlsplit(value)
        if (
            not value.isascii()
            or any(ord(c) <= 32 or ord(c) == 127 for c in value)
            or url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or not url.path.rstrip("/").endswith("/v1")
            or (url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1", "::1"))
        ):
            raise ValueError("assessment-endpoint-invalid")
        return value.rstrip("/")

    def resolved(self, role):
        model = self.model or os.environ.get(role + "_MODEL")
        if not model:
            raise ValueError("assessment-model-required")
        key = os.environ.get(self.api_key_env) if self.api_key_env else "not-required"
        if not key:
            raise ValueError("assessment-credential-unavailable")
        return ModelEndpoint.model_validate({**self.model_dump(), "model": model}), key


class CampaignConfig(StrictModel):
    assessment: AssessmentSpec
    adversarial: ModelEndpoint
    target: ModelEndpoint
    judge: ModelEndpoint
    adversarial_model_kind: Literal["abliterated"] = "abliterated"


class AssessmentRecord(StrictModel):
    schema_version: Literal["interplay-assessment/1"] = "interplay-assessment/1"
    campaign_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    attempt_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    ordinal: Annotated[int, Field(ge=0, le=49)]
    assessment_description: str
    success_criteria: str
    probe: str
    adversarial_intent: str
    strategy: str
    response: str | None = None
    capture_complete: bool | None = None
    logs_json: str | None = None
    traces_json: str | None = None
    conversation_trace_json: str | None = None
    generation_trace_json: str | None = None
    judge_trace_json: str | None = None
    judge_verdict: Verdict = "inconclusive"
    judge_reasoning: str | None = None
    evidence_refs_json: str = "[]"
    raw_judge_json: str | None = None
    observation_origin: str | None = None
    status: Literal["generated", "observed", "complete", "incomplete"] = "generated"
    error_code: str | None = None
    created_at: str
    provenance_json: str
    release_eligible: Literal[False] = False
