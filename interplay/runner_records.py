"""Runner export schema, usable without importing inference providers."""

from typing import Annotated, Literal

from pydantic import Field

from .assessment.models import StrictModel, Text, Verdict

RUNNER_SCHEMA_VERSION = "interplay-runner/2"


class RunnerRecord(StrictModel):
    """One retained trial; exported stages include incomplete/search-only trials."""

    schema_version: Literal["interplay-runner/1", "interplay-runner/2"] = RUNNER_SCHEMA_VERSION
    run_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    attempt_id: Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]
    ordinal: Annotated[int, Field(ge=0, le=4999)]
    method: Annotated[str, Field(min_length=1, max_length=40)]
    strategy: Annotated[str, Field(min_length=1, max_length=200)]
    goal: Annotated[str, Field(max_length=16384)]
    probe: Text
    response: str | None = None
    capture_complete: bool = True
    conversation_trace_json: str | None = None
    judge_verdict: Verdict = "inconclusive"
    judge_reasoning: str | None = None
    evidence_refs_json: str = "[]"
    raw_judge_json: str | None = None
    role_provenance_json: Annotated[str, Field(max_length=4096)]
    method_metadata_json: str = "{}"
    status: Literal["attempted", "observed", "complete", "incomplete"] = "attempted"
    error_code: str | None = None
    created_at: str
