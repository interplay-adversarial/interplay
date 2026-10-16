"""Flat, versioned calibration artifacts with case/rubric/model bindings."""

import hashlib
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from ..assessment.models import Observation, StrictModel, Text, Verdict
from ..assessment.storage import json_bytes
from ..report import _json

RUBRIC_VERSION = "interplay-label-rubric/1"
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Case(StrictModel):
    schema_version: Literal["interplay-calibration-case/1"] = "interplay-calibration-case/1"
    rubric_version: Literal["interplay-label-rubric/1"] = RUBRIC_VERSION
    case_id: Identifier
    family: Identifier
    criterion: Text
    probe: Text
    observation_json: Annotated[str, Field(max_length=262144)]
    design_bucket: Literal["supported-success", "supported-failure", "missing-or-ambiguous"]

    @model_validator(mode="after")
    def observation_valid(self):
        Observation.model_validate(_json(self.observation_json))
        return self

    def task(self):
        return self.model_dump(exclude={"design_bucket"})

    def digest(self):
        return hashlib.sha256(json_bytes(self.task())).hexdigest()

    def observation(self):
        return Observation.model_validate(_json(self.observation_json))


class HumanLabel(StrictModel):
    schema_version: Literal["interplay-human-label/1"] = "interplay-human-label/1"
    rubric_version: Literal["interplay-label-rubric/1"] = RUBRIC_VERSION
    case_id: Identifier
    case_sha256: Digest
    label_source: Literal["human"] = "human"
    reviewer_id: Identifier | None = None
    independent_review: bool = False
    verdict: Verdict | None = None
    reasoning: Text | None = None
    submitted_at: str | None = None

    @model_validator(mode="after")
    def completed_attestation(self):
        if self.verdict is not None:
            if (
                not self.reviewer_id
                or not self.reasoning
                or not self.independent_review
                or not self.submitted_at
            ):
                raise ValueError("calibration-human-attestation-required")
            stamp = datetime.fromisoformat(self.submitted_at.replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("calibration-label-timezone-required")
        return self


class GoldLabel(StrictModel):
    schema_version: Literal["interplay-human-gold/1"] = "interplay-human-gold/1"
    rubric_version: Literal["interplay-label-rubric/1"] = RUBRIC_VERSION
    case_id: Identifier
    case_sha256: Digest
    verdict: Verdict
    labels_json: str
    adjudication_json: str | None = None

    @model_validator(mode="after")
    def provenance_required(self):
        data = _json(self.labels_json)
        if not isinstance(data, list) or len(data) != 2:
            raise ValueError("calibration-two-human-labels-required")
        labels = [HumanLabel.model_validate(row) for row in data]
        if any(
            label.verdict is None
            or label.case_id != self.case_id
            or label.case_sha256 != self.case_sha256
            for label in labels
        ):
            raise ValueError("calibration-label-binding-invalid")
        reviewers = {label.reviewer_id for label in labels}
        if len(reviewers) != 2:
            raise ValueError("calibration-independent-reviewers-required")
        if labels[0].verdict == labels[1].verdict:
            if self.adjudication_json is not None or self.verdict != labels[0].verdict:
                raise ValueError("calibration-agreed-label-changed")
        else:
            if self.adjudication_json is None:
                raise ValueError("calibration-adjudication-required")
            decision = HumanLabel.model_validate(_json(self.adjudication_json))
            if (
                decision.verdict != self.verdict
                or decision.reviewer_id in reviewers
                or decision.case_id != self.case_id
                or decision.case_sha256 != self.case_sha256
            ):
                raise ValueError("calibration-adjudication-binding-invalid")
        return self


class JudgeIdentity(StrictModel):
    schema_version: Literal["interplay-calibration-judge/1"] = "interplay-calibration-judge/1"
    judge_id: Identifier
    provider: Text
    model: Text
    revision: Text | None = None

    def digest(self):
        return hashlib.sha256(json_bytes(self.model_dump())).hexdigest()

    def model_key(self):
        return self.provider, self.model, self.revision


class Prediction(StrictModel):
    schema_version: Literal["interplay-calibration-prediction/1"] = (
        "interplay-calibration-prediction/1"
    )
    rubric_version: Literal["interplay-label-rubric/1"] = RUBRIC_VERSION
    case_id: Identifier
    case_sha256: Digest
    judge_id: Identifier
    judge_sha256: Digest
    raw_reply: Annotated[str, Field(max_length=65536)] | None = None
    finish_reason: Literal["stop", "length", "error", "tool_calls"] = "error"
    error_code: Annotated[str, Field(max_length=200)] | None = None
    request_sha256: Digest | None = None
    response_sha256: Digest | None = None
