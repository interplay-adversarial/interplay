"""Adapter boundary tests without importing optional Gym or model providers."""

import asyncio
import copy
import json
import time
from contextlib import asynccontextmanager, suppress
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, PrivateAttr

from interplay.assessment.gym import GymSession, GymTargetConfig, NeMoGymTarget
from interplay.assessment.models import AssessmentSpec, JudgeOutput, Probe
from interplay.assessment.runner import run_assessment
from interplay.assessment.storage import json_bytes

PROBE = Probe(probe="Record MARKER", adversarial_intent="Synthetic fixture", strategy="fixture")
ATTEMPT = "a" * 32


class Value:
    def __init__(self, value):
        self.value = value

    @classmethod
    def model_validate(cls, value):
        return value if isinstance(value, cls) else cls(value)

    def model_dump(self, **kwargs):
        return self.value


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from interplay.assessment import gym

    state = {"calls": [], "world": {}, "mode": "complete", "closed": False, "outcome": True}
    response = {
        "status": "completed",
        "incomplete_details": None,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "MARKER"}],
            }
        ],
    }

    state["response"] = response

    class Reply:
        status, ok, cookies = 200, True, {}

        def __init__(self, value):
            self.raw, self.content = json_bytes(value), self

        async def read(self):
            return self.raw

    class Client:
        async def post(self, *, server_name, url_path, json, cookies):
            state["calls"].append((server_name, url_path))
            if server_name == "resources":
                state["world"]["marker"] = "MARKER"
            return Reply(response if server_name == "model" else {"recorded": True})

    class Agent:
        def __init__(self):
            self.server_client = Client()
            self.config = SimpleNamespace(
                max_steps=2,
                model_server=SimpleNamespace(name="model"),
                resources_server=SimpleNamespace(name="resources"),
            )

        def model_copy(self, *, update):
            result = copy.copy(self)
            result.__dict__.update(update)
            return result

        async def _create_episode(self, body, **kwargs):
            await self.server_client.post(
                server_name="model", url_path="/v1/responses", json=body, cookies=None
            )
            if state["mode"] == "unknown":
                await self.server_client.post(
                    server_name="resources", url_path="/run_shell", json={}, cookies=None
                )
            if state["mode"] == "budget":
                for _ in range(3):
                    await self.server_client.post(
                        server_name="model", url_path="/v1/responses", json=body, cookies=None
                    )
            await self.server_client.post(
                server_name="resources",
                url_path="/record_marker",
                json={"marker": "MARKER"},
                cookies=None,
            )
            if state["mode"] == "failed":
                raise RuntimeError("Private upstream diagnostic")
            if state["mode"] == "cancelled":
                await asyncio.sleep(5)
            if state["mode"] == "late":
                # Cancellation-resistant upstream work still must not become complete.
                with suppress(asyncio.CancelledError):
                    await asyncio.sleep(5)
            native = copy.deepcopy(response)
            if state["mode"] == "truncated":
                native["status"] = "incomplete"
            trajectory = {
                "task_id": kwargs["task_id"],
                "rollout_id": kwargs["rollout_id"],
                "invocations": [{"status": "completed"}],
                "tool_calls": [{"status": "completed", "tool_name": "record_marker"}],
                "gaps": [],
            }
            if state["mode"] == "wrong-id":
                trajectory["rollout_id"] = "other"
            return Value(native), Value(trajectory), None, None

    monkeypatch.setattr(
        gym, "_native", lambda: (Agent, BaseModel, PrivateAttr, Value, Value, Value)
    )

    async def outcome():
        if state["outcome"] == "failed":
            raise RuntimeError("Private diagnostic")
        if state["outcome"] == "invalid":
            return {"nan": float("nan")}
        return dict(state["world"]) if state["outcome"] else None

    @asynccontextmanager
    async def factory(attempt):
        state["attempt"] = attempt
        try:
            yield GymSession(Agent(), outcome)
        finally:
            state["closed"] = True

    config = GymTargetConfig(
        task_id="synthetic",
        max_steps=2,
        request_json=json.dumps(
            {
                "tools": [
                    {
                        "type": "function",
                        "name": "record_marker",
                        "parameters": {"type": "object", "properties": {}},
                    }
                ]
            }
        ),
    )
    return config, factory, state


def make(setup, tmp_path, **overrides):
    config, factory, state = setup
    return NeMoGymTarget(config.model_copy(update=overrides), factory, tmp_path / "capture")


def test_native_dispatch_binding_and_independent_outcome(setup, tmp_path):
    target = make(setup, tmp_path)
    observation = target.observe(PROBE, ATTEMPT, deadline=time.monotonic() + 5)
    state = setup[2]
    assert observation.capture_complete and observation.origin == "adapter-observed"
    assert observation.response == "MARKER" and state["closed"]
    logs = json.loads(observation.logs_json)
    assert logs["attempt_id"] == logs["rollout_id"] == ATTEMPT
    assert logs["environment_outcome"] == {"marker": "MARKER"} and not logs["containment_evaluated"]
    trace = json.loads(observation.traces_json)
    assert [e["kind"] for e in trace["boundary_events"]] == ["tool-attempted", "tool-observed"]
    assert len(state["calls"]) == 2
    assert all(not p.stat().st_mode & 0o077 for p in (tmp_path / "capture").rglob("*"))
    with pytest.raises(FileExistsError):
        target.observe(PROBE, ATTEMPT, deadline=time.monotonic() + 5)
    assert len(state["calls"]) == 2


@pytest.mark.parametrize("mode", ["failed", "unknown", "budget", "truncated", "wrong-id"])
def test_partial_observations_remain_inconclusive(setup, tmp_path, mode):
    setup[2]["mode"] = mode
    observation = make(setup, tmp_path).observe(PROBE, ATTEMPT, deadline=time.monotonic() + 5)
    assert not observation.capture_complete and observation.response == "MARKER"
    assert setup[2]["closed"]
    if mode == "unknown":
        assert not any(p == "/run_shell" for _, p in setup[2]["calls"])
    if mode == "failed":
        assert json.loads(observation.logs_json)["environment_outcome"] == {"marker": "MARKER"}
    if mode == "budget":
        assert len(setup[2]["calls"]) == 2
    assert b"Private upstream diagnostic" not in b"".join(
        p.read_bytes() for p in (tmp_path / "capture").rglob("*") if p.is_file()
    )


@pytest.mark.parametrize("outcome", [False, "failed", "invalid"])
def test_missing_or_failed_environment_capture_cannot_complete(setup, tmp_path, outcome):
    setup[2]["outcome"] = outcome
    observation = make(setup, tmp_path).observe(PROBE, ATTEMPT, deadline=time.monotonic() + 5)
    assert not observation.capture_complete and observation.response == "MARKER"
    assert json.loads(observation.logs_json)["outcome_status"] in ("missing", "failed")


@pytest.mark.parametrize("mode", ["cancelled", "late"])
def test_cooperative_deadline_preserves_tool_effect_and_late_response(setup, tmp_path, mode):
    setup[2]["mode"] = mode
    observation = make(setup, tmp_path).observe(PROBE, ATTEMPT, deadline=time.monotonic() + 2.02)
    assert not observation.capture_complete
    assert json.loads(observation.logs_json)["environment_outcome"] == {"marker": "MARKER"}
    assert observation.response == "MARKER" and setup[2]["closed"]


def test_expired_attempt_never_dispatches(setup, tmp_path):
    observation = make(setup, tmp_path).observe(PROBE, ATTEMPT, deadline=time.monotonic() - 1)
    assert not observation.capture_complete and not setup[2]["calls"]


def test_source_mismatch_prevents_session_and_output(setup, tmp_path, monkeypatch):
    from interplay.assessment import gym

    def mismatch():
        raise ValueError("gym-imported-source-mismatch")

    monkeypatch.setattr(gym, "_native", mismatch)
    target = make(setup, tmp_path)
    with pytest.raises(ValueError, match="source-mismatch"):
        target.observe(PROBE, ATTEMPT, deadline=time.monotonic() + 5)
    assert not setup[2]["calls"] and not (tmp_path / "capture" / ATTEMPT).exists()


@pytest.mark.parametrize(
    "template",
    [
        '{"input":[{"role":"user","content":"override"}]}',
        '{"tools":[{"type":"function","name":"../escape"}]}',
        '{"stream":true}',
        '{"tools":[{"type":"function","name":"x"},{"type":"function","name":"x"}]}',
    ],
)
def test_untrusted_template_routes_rejected(setup, tmp_path, template):
    config, factory, _ = setup
    with pytest.raises(ValueError):
        NeMoGymTarget(
            config.model_copy(update={"request_json": template}), factory, tmp_path / "capture"
        )
    assert not (tmp_path / "capture").exists()


def test_assessment_cites_observed_outcome_and_missing_capture_withholds_success(setup, tmp_path):
    class Generator:
        def generate(self, spec, *, deadline):
            return [(PROBE, None)]

    class Judge:
        def judge(self, spec, probe, observation, *, deadline):
            return JudgeOutput(
                verdict="success",
                reasoning="Constructed fixture",
                evidence_refs_json='["/logs/environment_outcome/marker"]',
            ), None

    target = make(setup, tmp_path)
    result = run_assessment(
        AssessmentSpec(
            description="Synthetic effect",
            success_criteria="Marker recorded",
            probe_count=1,
            required_surfaces=("logs", "traces"),
        ),
        Generator(),
        target,
        Judge(),
        tmp_path / "assessment",
    )
    assert result["successes"] == 1 and not result["release_eligible"]
    setup[2]["outcome"] = False
    result = run_assessment(
        AssessmentSpec(
            description="Synthetic effect",
            success_criteria="Marker recorded",
            probe_count=1,
            required_surfaces=("logs", "traces"),
        ),
        Generator(),
        target,
        Judge(),
        tmp_path / "missing",
    )
    assert result["successes"] == 0 and result["inconclusive"] == 1


def test_known_credential_redaction_and_reasoning_omission(setup, tmp_path):
    config, factory, state = setup
    secret = "fixture-private-credential"
    state["response"]["output"][0]["content"][0]["text"] = "Seen " + secret
    state["response"]["output"].append(
        {"type": "reasoning", "summary": [{"text": "fixture-private-reasoning"}]}
    )
    target = NeMoGymTarget(config, factory, tmp_path / "capture", secrets=(secret,))
    result = target.observe(PROBE, ATTEMPT, deadline=time.monotonic() + 5)
    assert result.response == "Seen [REDACTED]"
    contents = b"".join(p.read_bytes() for p in (tmp_path / "capture").rglob("*") if p.is_file())
    assert secret.encode() not in contents and b"fixture-private-reasoning" not in contents


def test_import_does_not_load_optional_sdk_or_network(tmp_path):
    import os
    import subprocess
    import sys
    from pathlib import Path

    source = Path(__file__).resolve().parents[1]
    script = """import importlib.abc,sys
class Guard(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in {'nemo_gym','responses_api_agents','httpx','aiohttp','any_llm','data_designer'}: raise RuntimeError('optional-import-attempt')
sys.meta_path.insert(0,Guard())
def audit(event,args):
 if event in ('socket.connect','socket.getaddrinfo','socket.sendto'): raise RuntimeError('network-attempt')
sys.addaudithook(audit)
from interplay.assessment.gym import GymTargetConfig,NeMoGymTarget
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(source)},
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr.decode()
