"""Per-invocation role configuration, bounded inference and durable runner stages.

The context is isolated per async task. Target work in a cancelled worker thread
never writes a journal: only its awaiting coroutine can commit observations.
"""

import asyncio
import dataclasses
import inspect
import json
import os
import time
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated
from uuid import uuid4

from pydantic import Field

from ..assessment.models import JudgeOutput, ModelEndpoint, Observation, StrictModel
from ..assessment.runner import redact
from ..assessment.storage import json_bytes
from .base import create_completion_kwargs
from .transport import (
    BudgetExceeded,
    CallBudget,
    RunnerRecord,
    RunnerResultSink,
    RunnerStorageError,
    new_record,
    resolve_role,
)

_SESSION: ContextVar["RunnerSession | None"] = ContextVar("runner_session", default=None)


class JudgeMember(StrictModel):
    """Explicit identity and independently resolved credentials for one panel member."""

    judge_id: Annotated[str, Field(min_length=1, max_length=200)]
    endpoint: ModelEndpoint


def current_session():
    return _SESSION.get()


def clean(value, secrets=()):
    session = current_session()
    keys = tuple(k for k in (*secrets, *(session.secrets if session else ())) if k)
    if isinstance(value, str):
        variants = set(keys)
        for key in keys:
            variants.add(json.dumps(key, ensure_ascii=True)[1:-1])
            variants.add(json.dumps(key, ensure_ascii=False)[1:-1])
        return redact(value, variants)
    if isinstance(value, list):
        return [clean(v, keys) for v in value]
    if isinstance(value, tuple):
        return tuple(clean(v, keys) for v in value)
    if isinstance(value, dict):
        return {clean(k, keys): clean(v, keys) for k, v in value.items()}
    return value


def clean_observation(observation, secrets=()):
    return Observation.model_validate(clean(observation.model_dump(), secrets))


def configured_role(role, endpoint, api_key):
    session = current_session()
    if session:
        endpoint, api_key = session.roles.get(role, (endpoint, api_key))
        session.endpoints[role] = endpoint
        if api_key:
            session.secrets.add(api_key)
    return endpoint, api_key


def completion_credentials(kwargs):
    """Account for the SDK's provider-env fallback when its api_key is None."""
    key = kwargs.get("api_key") or os.getenv(f"{kwargs.get('provider', 'openai').upper()}_API_KEY")
    session = current_session()
    if key and session:
        session.secrets.add(key)
    return (key,) if key else ()


def role_completion_kwargs(role, **kwargs):
    """Legacy arguments remain defaults; explicit role endpoints never share keys."""
    session = current_session()
    if session and role in session.roles:
        endpoint, key = session.roles[role]
        kwargs.update(model=endpoint.model, base_url=endpoint.base_url, api_key=key)
        kwargs["provider"] = endpoint.model.split("/")[0] if "/" in endpoint.model else "openai"
    result = create_completion_kwargs(**kwargs)
    completion_credentials(result)
    if session:
        endpoint = session.roles.get(role, (None, None))[0]
        if endpoint:
            session.endpoints[role] = endpoint
            result["request_seconds"] = endpoint.request_seconds
        else:
            # Record an SDK default as unknown, never invent a resolved URL.
            session.endpoints[role] = SimpleNamespace(
                base_url=result.get("api_base"), model=result["model"]
            )
        if result.get("api_key"):
            session.secrets.add(result["api_key"])
    return result


async def bounded_completion(call, *, budget=None, request_seconds=30, **kwargs):
    """Bound the SDK and await; reject late results even if cancellation is suppressed."""
    session = current_session()
    budget = budget or (session.budget if session else None)
    remaining = min(request_seconds, budget.remaining()) if budget else request_seconds
    if remaining <= 0:
        raise BudgetExceeded("campaign-deadline")
    kwargs = dict(kwargs)
    keys = completion_credentials(kwargs)
    if "messages" in kwargs:
        kwargs["messages"] = clean(kwargs["messages"], keys)
    end = time.monotonic() + remaining
    try:
        async with asyncio.timeout(remaining):
            response = await call(**kwargs, timeout=remaining)
    except TimeoutError as exc:
        raise BudgetExceeded(
            "campaign-deadline" if budget and budget.remaining() <= 0 else "model-request-deadline"
        ) from exc
    if budget:
        budget.check_deadline()
    if time.monotonic() >= end:
        raise BudgetExceeded("model-request-deadline")
    for choice in response.choices:
        if isinstance(choice.message.content, str):
            choice.message.content = clean(choice.message.content, keys)
    return response


class RunnerSession:
    def __init__(self, method, goal, *, output_dir, role_endpoints, judge_members, api_key):
        self.method, self.goal = method, goal
        self.roles = {
            role: resolve_role(role, endpoint) for role, endpoint in (role_endpoints or {}).items()
        }
        if any(role not in ("attacker", "target", "evaluator", "judge") for role in self.roles):
            raise ValueError("runner-role-invalid")
        self.judge_members = judge_members
        if judge_members:
            if len(judge_members) > 16 or len({m.judge_id for m in judge_members}) != len(
                judge_members
            ):
                raise ValueError("judge-panel-ids-invalid")
            if "judge" in self.roles:
                raise ValueError("configure-judge-role-or-members")
        self.secrets = {key for _, key in self.roles.values() if key}
        if api_key:
            self.secrets.add(api_key)
        for member in judge_members or ():
            _, key = resolve_role("judge", member.endpoint)
            self.secrets.add(key)
        self.endpoints = {role: endpoint for role, (endpoint, _) in self.roles.items()}
        for member in judge_members or ():
            self.endpoints["judge:" + member.judge_id] = resolve_role("judge", member.endpoint)[0]
        self.run_id = uuid4().hex
        self.records: list[RunnerRecord] = []
        self.budget: CallBudget | None = None
        self.sink = RunnerResultSink(Path(output_dir)) if output_dir is not None else None

    def stage(self, record):
        record = RunnerRecord.model_validate(clean(record.model_dump()))
        if self.sink:
            try:
                self.sink.stage(record)
            except Exception as exc:
                raise RunnerStorageError("runner-stage-write-failed") from exc
        if record.ordinal == len(self.records):
            self.records.append(record)
        else:
            self.records[record.ordinal] = record
        return record

    def start(self, messages, metadata):
        record = new_record(
            run_id=self.run_id,
            ordinal=len(self.records),
            method=self.method,
            strategy=str(
                metadata.get(
                    "strategy", metadata.get("transform", metadata.get("phase", self.method))
                )
            ),
            goal=self.goal,
            probe=messages[-1]["content"],
            roles=self.endpoints,
            secrets=tuple(self.secrets),
        )
        record = record.model_copy(
            update={
                "attempt_id": metadata.get("attempt_id", record.attempt_id),
                "method_metadata_json": json_bytes(clean(metadata)).decode(),
            }
        )
        return self.stage(record)

    def finish(self, error="interrupted"):
        for record in self.records[:]:
            if record.status in ("attempted", "observed"):
                self.stage(record.model_copy(update={"status": "incomplete", "error_code": error}))
        if self.sink:
            self.sink.export(self.records)


def retained_runner(method):
    """All method entry points accept output_dir, role_endpoints and judge_members.

    With output_dir omitted, the same stages are retained in result.records in
    memory. A new output directory enables private fsynced journals and exports.
    """

    def decorate(fn):
        @wraps(fn)
        async def run(*args, output_dir=None, role_endpoints=None, judge_members=None, **kwargs):
            bound = inspect.signature(fn).bind(*args, **kwargs)
            session = RunnerSession(
                method,
                bound.arguments["goal"],
                output_dir=output_dir,
                role_endpoints=role_endpoints,
                judge_members=judge_members,
                api_key=bound.arguments.get("api_key"),
            )
            token = _SESSION.set(session)
            error = "interrupted"
            try:
                result = await fn(*args, **kwargs)
                error = getattr(result, "stop_reason", "no-judge-configured")
                # Sanitize errors and attacker-generated diagnostic fields as well.
                for field in dataclasses.fields(result):
                    value = getattr(result, field.name)
                    if isinstance(value, list) and value and hasattr(value[0], "model_dump"):
                        value = [type(v).model_validate(clean(v.model_dump())) for v in value]
                    else:
                        value = clean(value)
                    setattr(result, field.name, value)
                # Include search-only trials (pruned/unsupported/render failures)
                # in exports as incomplete, explicitly never observed attempts.
                trials = getattr(result, "trials", [])
                for trial in trials:
                    data = trial.model_dump() if hasattr(trial, "model_dump") else trial
                    if data.get("attempt_id") not in {r.attempt_id for r in session.records}:
                        record = session.start([{"role": "user", "content": data["prompt"]}], data)
                        session.stage(
                            record.model_copy(
                                update={
                                    "status": "incomplete",
                                    "error_code": data.get("error_code") or "not-queried",
                                }
                            )
                        )
                if session.sink:
                    from ..assessment.storage import atomic_file

                    summary = {
                        f.name: clean(getattr(result, f.name))
                        for f in dataclasses.fields(result)
                        if f.name not in ("trials", "records", "conversation_history")
                    }
                    atomic_file(session.sink.root / "summary.json", json_bytes(summary))
                result.records = session.records
                return result
            finally:
                try:
                    session.finish(error)
                finally:
                    if session.sink:
                        session.sink.close()
                    _SESSION.reset(token)

        return run

    return decorate


async def request_target(target, kind, messages, *, budget, metadata=None, **kwargs):
    """Commit attempted and observed stages before any judge or refinement call."""
    session = current_session()
    messages = clean(messages)
    record = session.start(messages, metadata or {}) if session else None
    try:
        remaining = min(target.endpoint.request_seconds, budget.remaining())
        if remaining <= 0:
            raise BudgetExceeded("campaign-deadline")
        async with asyncio.timeout(remaining):
            response = await asyncio.to_thread(
                target.request, kind, messages, budget=budget, **kwargs
            )
        # A late response is retained, but never accepted as a complete observation.
        response = response.model_copy(
            update={
                "content": clean(response.content, (target.api_key,)),
                "capture_complete": response.capture_complete and budget.remaining() > 0,
            }
        )
        if session:
            session.stage(
                record.model_copy(
                    update={
                        "status": "observed",
                        "response": response.content,
                        "capture_complete": response.capture_complete,
                        "conversation_trace_json": json_bytes(clean(messages)).decode(),
                    }
                )
            )
        return response
    except BaseException as exc:
        if isinstance(exc, RunnerStorageError):
            raise
        if session:
            session.stage(
                record.model_copy(
                    update={"status": "incomplete", "error_code": "target-" + type(exc).__name__}
                )
            )
        if isinstance(exc, TimeoutError):
            raise BudgetExceeded("target-request-deadline") from exc
        raise


async def score_observation(scorer, goal, probe, observation, *, budget):
    """Retain the captured response even when no judge call can be admitted."""
    observation = clean_observation(observation)
    try:
        judgment, trace = await scorer.score(clean(goal), clean(probe), observation, budget=budget)
    except BudgetExceeded as exc:
        judgment, trace = (
            JudgeOutput(verdict="inconclusive", reasoning=str(exc), evidence_refs_json="[]"),
            None,
        )
    judgment = JudgeOutput.model_validate(clean(judgment.model_dump()))
    trace = clean(trace)
    session = current_session()
    interrupted = budget.remaining() <= 0 or judgment.reasoning in (
        "judge-call-budget",
        "campaign-deadline",
        "model-request-deadline",
        "judge-call-failed",
    )
    if session and session.records and session.records[-1].status == "observed":
        record = session.records[-1]
        incomplete = interrupted or not observation.capture_complete
        session.stage(
            record.model_copy(
                update={
                    "status": "incomplete" if incomplete else "complete",
                    "judge_verdict": "inconclusive" if incomplete else judgment.verdict,
                    "judge_reasoning": judgment.reasoning,
                    "evidence_refs_json": judgment.evidence_refs_json,
                    "raw_judge_json": trace,
                    "error_code": judgment.reasoning
                    if interrupted
                    else ("incomplete-capture" if incomplete else None),
                }
            )
        )
    return judgment, trace
