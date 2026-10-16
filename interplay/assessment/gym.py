"""Optional pinned SimpleAgent target with durable observations, never containment.

The trusted session factory owns environment setup/cleanup and model transport.
Generated probes supply user text only; they cannot select tools or endpoints.
"""

import asyncio
import hashlib
import importlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from ..report import _json
from .models import Observation, StrictModel
from .runner import redact
from .storage import atomic_file, json_bytes

GYM_REVISION = "f444b8020a3431fc820ef061cef400140bc7afb5"


class GymTargetConfig(StrictModel):
    gym_revision: Literal[GYM_REVISION] = GYM_REVISION
    task_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")]
    request_json: Annotated[str, Field(max_length=32768)]
    max_steps: Annotated[int, Field(ge=1, le=20)] = 3
    max_tool_calls: Annotated[int, Field(ge=1, le=64)] = 8
    max_output_tokens: Annotated[int, Field(ge=64, le=4096)] = 512
    rollout_seconds: Annotated[int, Field(ge=1, le=600)] = 60
    observation_seconds: Annotated[int, Field(ge=1, le=10)] = 2


@dataclass
class GymSession:
    """Fresh trusted context yielded by an async context-manager session factory.

    ``agent`` is the pinned native SimpleAgent. ``observe_environment`` is an
    async zero-argument read of the environment/receiver, independent of model
    text. Return a JSON object or None when unavailable. Cookie values are never
    exported. Factory setup/cleanup and callbacks must cooperate with cancellation.
    """

    agent: object
    observe_environment: object
    resources_cookies: dict | None = None


def _native():
    """Load optional Gym and check the actual imported compatibility surface."""
    from nemo_gym.openai_utils import NeMoGymResponse, NeMoGymResponseCreateParamsNonStreaming
    from nemo_gym.rollout_observability import TrajectoryRecord
    from nemo_gym.server_utils import ServerClient
    from pydantic import PrivateAttr
    from responses_api_agents.simple_agent.app import SimpleAgent

    pin = _json(Path(__file__).with_name("gym_source.json").read_bytes())
    for name, expected in pin["files"].items():
        module = importlib.import_module(name.removesuffix(".py").replace("/", "."))
        if hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest() != expected:
            raise ValueError("gym-imported-source-mismatch")
    return (
        SimpleAgent,
        ServerClient,
        PrivateAttr,
        NeMoGymResponseCreateParamsNonStreaming,
        NeMoGymResponse,
        TrajectoryRecord,
    )


def _public_capture(value):
    """Keep visible observations; omit native reasoning items/content."""
    if isinstance(value, list):
        return [
            _public_capture(v)
            for v in value
            if not (isinstance(v, dict) and v.get("type") == "reasoning")
        ]
    if isinstance(value, dict):
        return {k: _public_capture(v) for k, v in value.items() if k != "reasoning_content"}
    return value


def _text(response):
    output = response.get("output")
    if not isinstance(output, list):
        return None
    return (
        "\n".join(
            part["text"]
            for item in output
            if isinstance(item, dict)
            and item.get("type") == "message"
            and item.get("role") == "assistant"
            and isinstance(item.get("content"), list)
            for part in item.get("content", [])
            if isinstance(part, dict)
            and part.get("type") == "output_text"
            and isinstance(part.get("text"), str)
        )
        or None
    )


class _Capture:
    def __init__(self, root, binding, secrets):
        self.root, self.binding, self.secrets = root, binding, secrets
        self.events, self.size, self.truncated = [], 0, False
        self.last_response = None
        self.path = root / "events.jsonl"
        atomic_file(self.path, b"")

    def clean(self, value):
        value = _public_capture(redact(value, self.secrets))
        # Recognize exact known credentials inside embedded JSON strings as well.
        raw = json_bytes(value).decode()
        for secret in self.secrets:
            import json

            for ascii_only in (True, False):
                raw = raw.replace(json.dumps(secret, ensure_ascii=ascii_only)[1:-1], "[REDACTED]")
        return _json(raw)

    def event(self, kind, **data):
        item = self.clean({**self.binding, "kind": kind, **data})
        encoded = json_bytes(item)
        if len(encoded) > 256 * 1024 or self.size + len(encoded) > 8 * 1024 * 1024:
            self.truncated = True
            item = {
                **self.binding,
                "kind": kind,
                "capture_truncated": True,
                "omitted_sha256": hashlib.sha256(encoded).hexdigest(),
            }
            encoded = json_bytes(item)
        # A bounded number of calls bounds the number of markers, too.
        with self.path.open("ab") as stream:
            stream.write(encoded + b"\n")
            stream.flush()
            import os

            os.fsync(stream.fileno())
        self.size += len(encoded) + 1
        self.events.append(item)

    def artifact(self, name, value):
        value = self.clean(value)
        encoded = json_bytes(value)
        if len(encoded) > 2 * 1024 * 1024:
            self.truncated = True
            value = {
                **self.binding,
                "capture_truncated": True,
                "omitted_sha256": hashlib.sha256(encoded).hexdigest(),
            }
        atomic_file(self.root / name, json_bytes(value))


def _recording_client(
    base, private_attr, inner, capture, *, config, tools, model_name, resources_name, deadline
):
    class BufferedReply:
        def __init__(self, raw, response):
            self.raw, self.status, self.ok = raw, response.status, response.ok
            self.cookies, self.content = response.cookies, self

        async def read(self):
            return self.raw

        def raise_for_status(self):
            if not self.ok:
                raise ValueError("gym-upstream-status")

    class RecordingClient(base):
        _inner: object = private_attr()
        _models: int = private_attr(default=0)
        _tools: int = private_attr(default=0)

        async def post(self, *, server_name, url_path, json, cookies=None):
            if time.monotonic() >= deadline:
                raise TimeoutError
            is_model = server_name == model_name and url_path == "/v1/responses"
            is_tool = server_name == resources_name and url_path in {"/" + n for n in tools}
            if not is_model and not is_tool:
                raise ValueError("gym-dispatch-not-allowed")
            role = "model" if is_model else "tool"
            if is_model:
                self._models += 1
                if self._models > config.max_steps:
                    raise ValueError("gym-model-call-budget")
            else:
                self._tools += 1
                if self._tools > config.max_tool_calls:
                    raise ValueError("gym-tool-call-budget")
            request = json.model_dump(mode="json") if hasattr(json, "model_dump") else json
            capture.event(role + "-attempted", name=url_path, request=request)
            try:
                reply = await self._inner.post(
                    server_name=server_name, url_path=url_path, json=json, cookies=cookies
                )
                if hasattr(reply.content, "iter_chunked"):
                    data = bytearray()
                    async for chunk in reply.content.iter_chunked(65536):
                        data.extend(chunk)
                        if len(data) > 2 * 1024 * 1024:
                            capture.truncated = True
                            raise ValueError("gym-response-limit")
                    raw = bytes(data)
                else:
                    # In-process synthetic clients own their bounded bytes.
                    raw = await reply.content.read()
                if len(raw) > 2 * 1024 * 1024:
                    capture.truncated = True
                    raise ValueError("gym-response-limit")
                try:
                    value = _json(raw)
                except (ValueError, UnicodeError, RecursionError):
                    value = {"text": raw.decode(errors="replace")}
                capture.event(
                    role + "-observed", name=url_path, status=reply.status, response=value
                )
                if is_model and isinstance(value, dict):
                    capture.last_response = capture.clean(value)
                return BufferedReply(raw, reply)
            except BaseException:
                capture.event(role + "-unfinished", name=url_path)
                raise

    wrapped = RecordingClient.model_construct()
    wrapped._inner = inner
    return wrapped


class NeMoGymTarget:
    """TargetAdapter for one pinned native SimpleAgent episode per attempt.

    ``session_factory(attempt_id)`` must return a fresh async context manager
    yielding GymSession. It owns resource seeding, explicit model credentials,
    transport timeouts/retries and cleanup. The adapter never retries a dispatch;
    configure the underlying client to avoid automatic action retries. ``output``
    must be a new private directory. Use a process supervisor for hard deadlines.
    """

    def __init__(self, config, session_factory, output, *, secrets=()):
        self.config = GymTargetConfig.model_validate(config)
        self.session_factory, self.secrets = session_factory, tuple(s for s in secrets if s)
        raw = _json(self.config.request_json)
        if (
            not isinstance(raw, dict)
            or set(raw) - {"model", "input", "tools", "temperature", "top_p", "seed"}
            or not isinstance(raw.get("input", []), list)
        ):
            raise ValueError("gym-request-template-invalid")
        history = raw.get("input", [])
        if len(history) > 10 or any(
            not isinstance(m, dict)
            or set(m) != {"role", "content"}
            or m["role"] not in ("system", "developer")
            or not isinstance(m["content"], str)
            for m in history
        ):
            raise ValueError("gym-template-history-invalid")
        tools = raw.get("tools", [])
        if (
            not isinstance(tools, list)
            or len(tools) > 16
            or any(
                not isinstance(t, dict)
                or t.get("type") != "function"
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", t.get("name", ""))
                for t in tools
            )
            or len({t["name"] for t in tools}) != len(tools)
        ):
            raise ValueError("gym-template-tools-invalid")
        self.template, self.tools = raw, {t["name"] for t in tools}
        if redact(self.config.model_dump(), self.secrets) != self.config.model_dump():
            raise ValueError("gym-template-contains-credential")
        self.root = Path(output)
        self.root.mkdir(mode=0o700, exist_ok=False)
        atomic_file(self.root / "config.json", json_bytes(self.config.model_dump()))

    def observe(self, probe, attempt_id, *, deadline):
        """Synchronous assessment hook; async hosts should use observe_async."""
        return asyncio.run(self.observe_async(probe, attempt_id, deadline=deadline))

    async def observe_async(self, probe, attempt_id, *, deadline):
        if not re.fullmatch(r"[0-9a-f]{32}", attempt_id):
            raise ValueError("gym-attempt-id-invalid")
        if redact(probe.model_dump(), self.secrets) != probe.model_dump():
            raise ValueError("gym-probe-contains-credential")
        native_agent, base, private_attr, params, response_type, trajectory_type = _native()
        body = params.model_validate(
            {
                **self.template,
                "input": [
                    *self.template.get("input", []),
                    {"role": "user", "content": probe.probe},
                ],
                "max_output_tokens": self.config.max_output_tokens,
            }
        )
        root = self.root / attempt_id
        root.mkdir(mode=0o700, exist_ok=False)
        binding = {
            "attempt_id": attempt_id,
            "task_id": self.config.task_id,
            "rollout_id": attempt_id,
            "probe_sha256": hashlib.sha256(json_bytes(probe.model_dump())).hexdigest(),
            "gym_revision": GYM_REVISION,
        }
        capture = _Capture(root, binding, self.secrets)
        capture.artifact("request.json", {**binding, "request": body.model_dump(mode="json")})
        capture.event("attempted")
        errors, response, trajectory, outcome = [], None, None, None
        outcome_status = "missing"
        end = min(
            deadline,
            time.monotonic() + self.config.rollout_seconds + self.config.observation_seconds,
        )
        rollout_end = min(
            end - self.config.observation_seconds, time.monotonic() + self.config.rollout_seconds
        )
        try:
            if time.monotonic() >= rollout_end:
                raise TimeoutError
            async with asyncio.timeout_at(end):
                async with self.session_factory(attempt_id) as session:
                    if (
                        not isinstance(session, GymSession)
                        or type(session.agent) is not native_agent
                        or session.agent.config.max_steps != self.config.max_steps
                        or not callable(session.observe_environment)
                    ):
                        raise ValueError("gym-session-invalid")
                    cfg = session.agent.config
                    client = _recording_client(
                        base,
                        private_attr,
                        session.agent.server_client,
                        capture,
                        config=self.config,
                        tools=self.tools,
                        model_name=cfg.model_server.name,
                        resources_name=cfg.resources_server.name if cfg.resources_server else None,
                        deadline=rollout_end,
                    )
                    agent = session.agent.model_copy(update={"server_client": client})
                    try:
                        async with asyncio.timeout_at(rollout_end):
                            result = await agent._create_episode(
                                body,
                                model_url_path="/v1/responses",
                                resources_server_cookies=session.resources_cookies,
                                task_id=self.config.task_id,
                                rollout_id=attempt_id,
                                collect_trajectory=True,
                            )
                        response = response_type.model_validate(result[0]).model_dump(mode="json")
                        trajectory = trajectory_type.model_validate(result[1]).model_dump(
                            mode="json"
                        )
                        capture.artifact(
                            "native.json",
                            {**binding, "response": response, "trajectory": trajectory},
                        )
                        if time.monotonic() >= rollout_end:
                            errors.append("gym-late-rollout")
                    except Exception:
                        errors.append("gym-rollout-incomplete")
                    try:
                        outcome = await session.observe_environment()
                        if outcome is not None and not isinstance(outcome, dict):
                            raise ValueError("gym-outcome-invalid")
                        outcome_status = "observed" if outcome is not None else "missing"
                        capture.artifact("environment.json", {**binding, "outcome": outcome})
                        if time.monotonic() >= end:
                            outcome_status = "late"
                    except Exception:
                        outcome = None
                        outcome_status = "failed"
        except Exception:
            errors.append("gym-session-incomplete")
        if time.monotonic() >= end:
            errors.append("gym-deadline")
        complete = bool(
            response
            and trajectory
            and not errors
            and outcome_status == "observed"
            and response.get("status") == "completed"
            and response.get("incomplete_details") is None
            and trajectory.get("task_id") == self.config.task_id
            and trajectory.get("rollout_id") == attempt_id
            and trajectory.get("invocations")
            and all(i.get("status") == "completed" for i in trajectory["invocations"])
            and all(t.get("status") == "completed" for t in trajectory.get("tool_calls", []))
            and not trajectory.get("gaps")
            and not capture.truncated
        )
        observed_response = capture.clean(response) if response else capture.last_response
        text = _text(observed_response or {})
        logs = {
            **binding,
            "schema_version": "interplay-gym-outcomes/1",
            "outcome_status": outcome_status,
            "environment_outcome": outcome,
            "errors": errors,
            "containment_evaluated": False,
        }
        traces = {
            **binding,
            "native_trajectory": trajectory,
            "boundary_events": [e for e in capture.events if e["kind"].startswith("tool-")],
            "model_attempts": sum(e["kind"] == "model-attempted" for e in capture.events),
        }
        conversation = {
            **binding,
            "request": body.model_dump(mode="json"),
            "output": (observed_response or {}).get("output", []),
        }

        def bounded(value):
            nonlocal complete
            encoded = json_bytes(capture.clean(value))
            if len(encoded) > 65536:
                complete = False
                return json_bytes(
                    {
                        **binding,
                        "capture_truncated": True,
                        "omitted_sha256": hashlib.sha256(encoded).hexdigest(),
                    }
                ).decode()
            return encoded.decode()

        logs_json, traces_json, conversation_json = [
            bounded(v) for v in (logs, traces, conversation)
        ]
        if text is not None and len(text) > 65536:
            text, complete = text[:65536], False
        observation = Observation(
            capture_complete=complete,
            response=text,
            logs_json=logs_json,
            traces_json=traces_json,
            conversation_trace_json=conversation_json,
            origin="adapter-observed",
        )
        capture.artifact("observation.json", observation.model_dump())
        capture.event("finished", capture_complete=complete, errors=errors)
        return observation
