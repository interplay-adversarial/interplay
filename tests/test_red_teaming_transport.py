"""Synthetic loopback tests for the shared runner transport/scorer/result sink.

No real credentials or hosted model calls: the "target" and "judge" are a local
HTTP fixture and a stub scorer-call respectively.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, MagicMock, patch

import pyarrow.parquet as pq
import pytest

from interplay.assessment.models import JudgeOutput, ModelEndpoint, Observation
from interplay.assessment.storage import private_file
from interplay.red_teaming.transport import (
    AuthenticatedTarget,
    BudgetExceeded,
    CallBudget,
    JudgeScorer,
    RoleCredentialError,
    RunBudget,
    RunnerResultSink,
    UnsupportedCapabilityError,
    new_record,
    recover_runner_records,
    resolve_role,
    role_provenance,
)


@pytest.fixture
def endpoint():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append({"body": body, "headers": dict(self.headers)})
            model = body["model"]
            if model == "malformed-target":
                payload = {"choices": []}
            elif model == "slow-target":
                time.sleep(2)
                payload = _chat_payload("slow")
            else:
                payload = _chat_payload("SYNTHETIC-CANARY")
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    def _chat_payload(content):
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ]
        }

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", calls
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def test_authenticated_request_attaches_bearer_header(endpoint):
    base_url, calls = endpoint
    target = AuthenticatedTarget(
        ModelEndpoint(base_url=base_url, model="target-model"),
        api_key="secret-target-key",
        capabilities=frozenset({"stateless"}),
    )
    response = target.request(
        "stateless", [{"role": "user", "content": "hi"}], budget=CallBudget(RunBudget())
    )
    assert response.content == "SYNTHETIC-CANARY" and response.capture_complete
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-target-key"


@pytest.mark.asyncio
async def test_pair_attack_attaches_authorization_to_the_target_only(endpoint):
    """Closes the documented gap: PAIR's target helper used to send no
    Authorization header at all, so a configured TARGET_API_KEY was silently
    never used. The attacker/judge calls go through any_llm, mocked here."""
    from interplay.red_teaming.pair_runner import pair_attack

    base_url, calls = endpoint
    with patch(
        "interplay.red_teaming.pair_runner.acompletion",
        new=AsyncMock(
            return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="0.0"))])
        ),
    ):
        result = await pair_attack(
            goal="test goal",
            target_url=base_url,
            attacker_model="openai/test",
            judge_model="openai/test",
            target_model="target-model",
            max_queries=1,
            api_key="target-secret",
        )
    assert result.query_count == 1
    assert len(calls) == 1
    assert calls[0]["headers"]["Authorization"] == "Bearer target-secret"
    assert calls[0]["body"]["model"] == "target-model"


@pytest.mark.asyncio
async def test_pair_attack_retains_prior_trials_on_target_failure_instead_of_raising(endpoint):
    """A malformed/failed target reply on a later iteration must not discard the
    trials already gathered, and must stop the campaign rather than retry."""
    from interplay.red_teaming.pair_runner import pair_attack

    base_url, calls = endpoint
    with patch(
        "interplay.red_teaming.pair_runner.acompletion",
        new=AsyncMock(
            return_value=MagicMock(choices=[MagicMock(message=MagicMock(content="0.0"))])
        ),
    ):
        result = await pair_attack(
            goal="test goal",
            target_url=base_url,
            attacker_model="openai/test",
            judge_model="openai/test",
            target_model="malformed-target",
            max_queries=3,
            api_key=None,
        )
    assert len(calls) == 1
    assert result.query_count == 0
    assert len(result.conversation_history) == 1
    assert result.conversation_history[0]["response"] is None
    assert "error" in result.conversation_history[0]


def test_unauthenticated_request_sends_no_authorization_header(endpoint):
    base_url, calls = endpoint
    target = AuthenticatedTarget(
        ModelEndpoint(base_url=base_url, model="target-model"), api_key=None
    )
    target.request("stateless", [{"role": "user", "content": "hi"}], budget=CallBudget(RunBudget()))
    assert "Authorization" not in calls[0]["headers"]


def test_capability_not_declared_is_rejected_before_any_request(endpoint):
    base_url, calls = endpoint
    target = AuthenticatedTarget(
        ModelEndpoint(base_url=base_url, model="target-model"),
        api_key=None,
        capabilities=frozenset({"stateless"}),
    )
    with pytest.raises(UnsupportedCapabilityError, match="target-capability-unsupported:image"):
        target.request("image", [{"role": "user", "content": "hi"}], budget=CallBudget(RunBudget()))
    assert calls == []


def test_malformed_target_reply_is_rejected_not_silently_accepted(endpoint):
    base_url, _ = endpoint
    target = AuthenticatedTarget(
        ModelEndpoint(base_url=base_url, model="malformed-target"), api_key=None
    )
    with pytest.raises(ValueError, match="target-response-invalid"):
        target.request(
            "stateless", [{"role": "user", "content": "hi"}], budget=CallBudget(RunBudget())
        )


def test_per_call_deadline_is_enforced_without_retry(endpoint):
    base_url, calls = endpoint
    target = AuthenticatedTarget(
        ModelEndpoint(base_url=base_url, model="slow-target", request_seconds=1), api_key=None
    )
    import httpx

    budget = CallBudget(RunBudget(campaign_seconds=60))
    with pytest.raises(httpx.TimeoutException):
        target.request("stateless", [{"role": "user", "content": "hi"}], budget=budget)
    assert len(calls) == 1


def test_campaign_deadline_blocks_further_calls():
    budget = CallBudget(RunBudget(campaign_seconds=1))
    budget.deadline = time.monotonic() - 1
    with pytest.raises(BudgetExceeded, match="campaign-deadline"):
        budget.charge_call("target")


def test_per_role_call_budget_is_exhausted_without_retry():
    budget = CallBudget(RunBudget(max_calls_per_role=2))
    budget.charge_call("target")
    budget.charge_call("target")
    with pytest.raises(BudgetExceeded, match="target-call-budget"):
        budget.charge_call("target")


def test_turn_budget_is_exhausted():
    budget = CallBudget(RunBudget(max_turns=1))
    budget.charge_turn()
    with pytest.raises(BudgetExceeded, match="turn-budget"):
        budget.charge_turn()


def test_role_resolution_has_no_fallback_to_another_roles_key(monkeypatch):
    monkeypatch.delenv("JUDGE_API_KEY", raising=False)
    monkeypatch.setenv("TARGET_API_KEY", "target-secret")
    monkeypatch.setenv("JUDGE_MODEL", "judge-model")
    endpoint = ModelEndpoint(base_url="https://judge.example/v1", api_key_env="JUDGE_API_KEY")
    with pytest.raises(RoleCredentialError, match="judge-"):
        resolve_role("judge", endpoint)


def test_role_resolution_uses_only_its_own_explicit_env_vars(monkeypatch):
    monkeypatch.setenv("TARGET_API_KEY", "target-secret")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-secret")
    monkeypatch.setenv("JUDGE_MODEL", "judge-model")
    endpoint = ModelEndpoint(base_url="https://judge.example/v1", api_key_env="JUDGE_API_KEY")
    resolved, key = resolve_role("judge", endpoint)
    assert key == "judge-secret" and resolved.model == "judge-model"


class StubScorer(JudgeScorer):
    """Avoids any hosted call; returns a fixed raw judgment for _call."""

    def __init__(self, raw):
        self.raw = raw

    async def _call(self, goal, probe, observation, *, budget):
        return JudgeOutput.model_validate(self.raw), json.dumps(self.raw)


async def test_missing_evidence_is_inconclusive_not_fabricated_success():
    scorer = StubScorer(
        {"verdict": "success", "reasoning": "claims success", "evidence_refs_json": "[]"}
    )
    observation = Observation(response="hello")
    judgment, _ = await scorer.score("goal", "probe", observation, budget=CallBudget(RunBudget()))
    assert judgment.verdict == "inconclusive"


async def test_invalid_evidence_reference_is_inconclusive():
    scorer = StubScorer(
        {
            "verdict": "success",
            "reasoning": "claims success",
            "evidence_refs_json": '["/response/missing"]',
        }
    )
    observation = Observation(response="hello")
    judgment, _ = await scorer.score("goal", "probe", observation, budget=CallBudget(RunBudget()))
    assert judgment.verdict == "inconclusive"


async def test_provider_failure_is_inconclusive_not_a_fabricated_zero():
    class FailingScorer(JudgeScorer):
        def __init__(self):
            pass

        async def _call(self, *args, **kwargs):
            raise ConnectionError("private-provider-detail")

    judgment, trace = await FailingScorer().score(
        "goal", "probe", Observation(response="hello"), budget=CallBudget(RunBudget())
    )
    assert judgment.verdict == "inconclusive" and trace is None


async def test_supported_success_is_preserved():
    scorer = StubScorer(
        {
            "verdict": "success",
            "reasoning": "Response contains the synthetic canary.",
            "evidence_refs_json": '["/response"]',
        }
    )
    observation = Observation(response="SYNTHETIC-CANARY")
    judgment, _ = await scorer.score("goal", "probe", observation, budget=CallBudget(RunBudget()))
    assert judgment.verdict == "success"


def test_role_provenance_never_includes_credentials():
    roles = {"target": ModelEndpoint(base_url="https://target.example/v1", model="m")}
    provenance = role_provenance(roles)
    assert "secret" not in provenance
    assert json.loads(provenance) == {
        "target": {"base_url": "https://target.example/v1", "model": "m"}
    }


def _roles():
    return {"target": ModelEndpoint(base_url="https://target.example/v1", model="target-model")}


def test_sink_retains_incomplete_trials_and_exports_consistently(tmp_path):
    out = tmp_path / "run"
    sink = RunnerResultSink(out)
    try:
        attempted = new_record(
            run_id="a" * 32,
            ordinal=0,
            method="pair",
            strategy="direct",
            goal="goal",
            probe="probe",
            roles=_roles(),
        )
        sink.stage(attempted)
        failed = attempted.model_copy(
            update={"status": "incomplete", "error_code": "target-observation-failed"}
        )
        sink.stage(failed)
        sink.export([failed])
    finally:
        sink.close()

    rows = [json.loads(line) for line in private_file(out / "records.jsonl").splitlines()]
    assert rows[0]["status"] == "incomplete"
    assert rows[0]["error_code"] == "target-observation-failed"
    assert pq.read_table(out / "records.parquet").to_pylist() == rows
    assert all((p.stat().st_mode & 0o077) == 0 for p in out.iterdir())


def test_recovery_marks_unresolved_attempts_incomplete_without_rerunning(tmp_path):
    out = tmp_path / "run"
    sink = RunnerResultSink(out)
    record = new_record(
        run_id="b" * 32,
        ordinal=0,
        method="pair",
        strategy="direct",
        goal="goal",
        probe="probe",
        roles=_roles(),
    )
    sink.stage(record)  # left at "attempted"; the run never commits a final stage
    sink.close()

    recovered = recover_runner_records(out)
    assert len(recovered) == 1
    assert recovered[0].status == "incomplete" and recovered[0].error_code == "interrupted"


def test_recovery_rejects_a_rewritten_committed_record(tmp_path):
    out = tmp_path / "run"
    sink = RunnerResultSink(out)
    record = new_record(
        run_id="c" * 32,
        ordinal=0,
        method="pair",
        strategy="direct",
        goal="goal",
        probe="probe",
        roles=_roles(),
    )
    final = record.model_copy(update={"status": "complete", "response": "first"})
    sink.stage(record)
    sink.stage(final)
    sink.close()

    rewritten = final.model_copy(update={"response": "rewritten"})
    with (out / "events.jsonl").open("ab") as stream:
        stream.write(rewritten.model_dump_json().encode() + b"\n")

    with pytest.raises(ValueError, match="binding-changed"):
        recover_runner_records(out)
