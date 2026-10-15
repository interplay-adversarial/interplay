"""Synthetic loopback tests for the Crescendo runner.

No real credentials or hosted model calls: the target is a local HTTP fixture;
the attacker's escalation call (`acompletion`) is mocked; the judge's model
call (`JudgeScorer._call`) is mocked directly so verdicts are deterministic.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from interplay.assessment.models import JudgeOutput, ModelEndpoint
from interplay.red_teaming.crescendo_runner import CrescendoConfig, crescendo_attack
from interplay.red_teaming.transport import RunnerResultSink, new_record, recover_runner_records


@pytest.fixture
def endpoint():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            payload = {
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "SYNTHETIC-CANARY"},
                        "finish_reason": "stop",
                    }
                ]
            }
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", calls
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


@pytest.fixture
def context_dependent_endpoint():
    """A synthetic target that only emits the "harmful" payload when an
    earlier turn's reply is present in the incoming messages -- it cannot be
    satisfied by a stateless (context-free) call."""
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            has_prior_context = any(
                m.get("role") == "assistant" and "BENIGN-SEED-REPLY" in m.get("content", "")
                for m in body["messages"]
            )
            content = "HARMFUL-PAYLOAD" if has_prior_context else "BENIGN-SEED-REPLY"
            payload = {
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ]
            }
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", calls
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def _attacker_mock(prompts: list[str]):
    """Each call returns the next raw escalation prompt text, in order."""
    it = iter(prompts)

    async def side_effect(**kwargs):
        return MagicMock(choices=[MagicMock(message=MagicMock(content=next(it)))])

    return AsyncMock(side_effect=side_effect)


def _verdict_from_response(verdict_for_harmful: str = "success"):
    def fake_call(goal, probe, observation, *, budget):
        response = observation.response or ""
        verdict = verdict_for_harmful if "HARMFUL-PAYLOAD" in response else "failure"
        return (
            JudgeOutput(verdict=verdict, reasoning="r", evidence_refs_json='["/response"]'),
            "{}",
        )

    return fake_call


def test_stateless_mode_cannot_satisfy_a_context_dependent_fixture(context_dependent_endpoint):
    """The synthetic target only yields the harmful payload once it has seen
    its own earlier reply; a stateless run never shows it that reply, so it
    can never falsely pass."""
    base_url, calls = context_dependent_endpoint
    with (
        patch(
            "interplay.red_teaming.crescendo_runner.acompletion",
            new=_attacker_mock(["escalate further"]),
        ),
        patch(
            "interplay.red_teaming.transport.JudgeScorer._call",
            side_effect=_verdict_from_response(),
        ),
    ):
        result = _run(
            crescendo_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            max_turns=2,
            target_mode="stateless",
        )
    assert len(calls) == 2
    assert result.confirmed_success is False
    assert all(t["judge_verdict"] != "success" for t in result.trials)


def test_conversation_mode_lets_a_context_dependent_fixture_succeed(context_dependent_endpoint):
    base_url, calls = context_dependent_endpoint
    with (
        patch(
            "interplay.red_teaming.crescendo_runner.acompletion",
            new=_attacker_mock(["escalate further"]),
        ),
        patch(
            "interplay.red_teaming.transport.JudgeScorer._call",
            side_effect=_verdict_from_response(),
        ),
    ):
        result = _run(
            crescendo_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            max_turns=2,
            target_mode="conversation",
        )
    assert len(calls) == 2
    assert result.stop_reason == "success"
    assert result.confirmed_success is True
    # Turn 1 carried turn 0's reply back, which is what unlocked the payload.
    assert any(m.get("content") == "BENIGN-SEED-REPLY" for m in calls[1]["messages"])


def test_refusal_turn_scores_failure_not_a_fabricated_zero(endpoint):
    base_url, calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        return (
            JudgeOutput(verdict="failure", reasoning="refused", evidence_refs_json='["/response"]'),
            "{}",
        )

    with (
        patch(
            "interplay.red_teaming.crescendo_runner.acompletion",
            new=_attacker_mock(["escalate once"]),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            crescendo_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            max_turns=1,
        )
    assert len(calls) == 1
    assert result.trials[0]["judge_verdict"] == "failure"
    assert result.trials[0]["parent_id"] is None
    assert result.confirmed_success is False


def test_later_turn_success_is_terminal(endpoint):
    base_url, calls = endpoint
    verdicts = iter(["failure", "success"])

    def fake_call(goal, probe, observation, *, budget):
        return JudgeOutput(
            verdict=next(verdicts), reasoning="r", evidence_refs_json='["/response"]'
        ), "{}"

    attacker_mock = _attacker_mock(["escalate-1", "unused-if-terminal"])
    with (
        patch("interplay.red_teaming.crescendo_runner.acompletion", new=attacker_mock),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            crescendo_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            max_turns=5,
        )
    assert len(calls) == 2
    assert attacker_mock.await_count == 1  # only turn 0 -> turn 1's escalation was ever decided
    assert result.stop_reason == "success"
    assert result.turns == 2
    assert result.trials[1]["parent_id"] == result.trials[0]["attempt_id"]


def test_secondary_judge_models_form_a_panel_with_irr(endpoint):
    base_url, calls = endpoint
    judge_a_verdicts = iter(["failure", "failure"])
    judge_b_verdicts = iter(["failure", "success"])

    def fake_call(self, goal, probe, observation, *, budget):
        verdicts = judge_a_verdicts if self.endpoint.model == "openai/judge" else judge_b_verdicts
        return (
            JudgeOutput(verdict=next(verdicts), reasoning="r", evidence_refs_json='["/response"]'),
            "{}",
        )

    attacker_mock = _attacker_mock(["escalate-1"])
    with (
        patch("interplay.red_teaming.crescendo_runner.acompletion", new=attacker_mock),
        patch(
            "interplay.red_teaming.transport.JudgeScorer._call",
            autospec=True,
            side_effect=fake_call,
        ),
    ):
        result = _run(
            crescendo_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            secondary_judge_models=["openai/judge-2"],
            max_turns=2,
        )
    assert len(calls) == 2
    assert result.stop_reason == "turn-budget"  # both judged turns stayed non-success
    assert result.trials[0]["judge_verdict"] == "failure"  # panel agreed
    assert result.trials[1]["judge_verdict"] == "inconclusive"  # panel split (tie)
    assert json.loads(result.trials[0]["judge_panel_json"])["aggregation"] == "majority"
    assert result.irr_unavailable_reason is None
    assert result.irr_report["n_judges"] == 2
    assert result.irr_report["n_cases"] == 2


def test_malformed_judge_output_is_inconclusive_not_a_crash(endpoint):
    base_url, _calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        raise ValueError("not valid json")

    with (
        patch(
            "interplay.red_teaming.crescendo_runner.acompletion",
            new=_attacker_mock(["escalate"]),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            crescendo_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            max_turns=1,
        )
    assert result.trials[0]["judge_verdict"] == "inconclusive"
    assert result.trials[0]["status"] == "complete"


def test_lost_capture_is_retained_as_incomplete_and_inconclusive(endpoint):
    base_url, _calls = endpoint

    class TruncatedHandler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            payload = {
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "cut off mid"},
                        "finish_reason": "length",
                    }
                ]
            }
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), TruncatedHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:

        def fake_call(goal, probe, observation, *, budget):
            return (
                JudgeOutput(verdict="success", reasoning="r", evidence_refs_json='["/response"]'),
                "{}",
            )

        with (
            patch(
                "interplay.red_teaming.crescendo_runner.acompletion",
                new=_attacker_mock(["escalate"]),
            ),
            patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
        ):
            result = _run(
                crescendo_attack,
                goal="test",
                target_url=f"http://127.0.0.1:{server.server_port}/v1",
                attacker_model="openai/attacker",
                judge_model="openai/judge",
                max_turns=1,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    assert result.trials[0]["capture_complete"] is False
    assert result.trials[0]["status"] == "incomplete"
    assert result.trials[0]["error_code"] == "incomplete-capture"
    assert result.trials[0]["judge_verdict"] == "inconclusive"  # never the judge's raw "success"


def test_deadline_exhaustion_preserves_prior_trials_without_raising(endpoint):
    base_url, _calls = endpoint

    async def slow_side_effect(**kwargs):
        import asyncio

        await asyncio.sleep(0.6)
        return MagicMock(choices=[MagicMock(message=MagicMock(content="escalate"))])

    def fake_call(goal, probe, observation, *, budget):
        return JudgeOutput(verdict="inconclusive", reasoning="r", evidence_refs_json="[]"), "{}"

    with (
        patch(
            "interplay.red_teaming.crescendo_runner.acompletion",
            new=AsyncMock(side_effect=slow_side_effect),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            crescendo_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            max_turns=5,
            campaign_seconds=1,
        )
    assert result.stop_reason == "campaign-deadline"
    assert len(result.trials) >= 1  # turn 0's trial was kept


def test_empty_escalation_is_rejected_not_executed_as_a_prompt(endpoint):
    base_url, calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        return JudgeOutput(verdict="failure", reasoning="r", evidence_refs_json="[]"), "{}"

    with (
        patch(
            "interplay.red_teaming.crescendo_runner.acompletion",
            new=_attacker_mock(["   "]),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            crescendo_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            max_turns=3,
        )
    assert len(calls) == 1  # only turn 0 ever queried the target
    assert len(result.trials) == 1
    assert result.stop_reason.startswith("attacker-output-invalid:empty-escalation-prompt")


def test_context_window_reports_omitted_earlier_turns(endpoint):
    base_url, calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        return JudgeOutput(verdict="failure", reasoning="r", evidence_refs_json="[]"), "{}"

    seen_prompts = []

    async def side_effect(**kwargs):
        system = kwargs["messages"][0]["content"]
        seen_prompts.append(system)
        return MagicMock(
            choices=[MagicMock(message=MagicMock(content=f"escalate-{len(seen_prompts)}"))]
        )

    with (
        patch(
            "interplay.red_teaming.crescendo_runner.acompletion",
            new=AsyncMock(side_effect=side_effect),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            crescendo_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            max_turns=4,
            context_window=2,
        )
    assert len(calls) == 4
    # Turn 2's decision (seen_prompts[1]) is generated after turns 0-1 executed
    # (2 trials, window=2 -> nothing omitted yet).
    assert "omitted" not in seen_prompts[1]
    # Turn 3's decision (seen_prompts[2]) is generated after turns 0-2 executed
    # (3 trials, window=2 -> turn 0 is omitted).
    assert "1 earlier turn(s) omitted" in seen_prompts[2]
    assert result.trials[3]["context_omitted_turns"] == 1


def test_target_failure_is_retained_as_an_incomplete_trial_not_lost():
    with patch(
        "interplay.red_teaming.crescendo_runner.acompletion",
        new=_attacker_mock(["escalate"]),
    ):
        result = _run(
            crescendo_attack,
            goal="test",
            target_url="http://127.0.0.1:1/v1",  # nothing listening: connection fails
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            max_turns=2,
        )
    assert result.stop_reason == "target-observation-failed"
    assert len(result.trials) == 1
    assert result.trials[0]["status"] == "incomplete"
    assert result.trials[0]["error_code"].startswith("target-observation-failed:")


def test_messages_sent_json_matches_target_mode(endpoint):
    base_url, _calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        return JudgeOutput(verdict="failure", reasoning="r", evidence_refs_json="[]"), "{}"

    with (
        patch(
            "interplay.red_teaming.crescendo_runner.acompletion",
            new=_attacker_mock(["escalate"]),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            crescendo_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            max_turns=2,
            target_mode="stateless",
        )
    sent = json.loads(result.trials[1]["messages_sent_json"])
    assert sent == [{"role": "user", "content": result.trials[1]["prompt"]}]


def test_offline_retained_trial_export_without_target_replay(tmp_path, endpoint):
    base_url, calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        return JudgeOutput(verdict="failure", reasoning="r", evidence_refs_json="[]"), "{}"

    with (
        patch(
            "interplay.red_teaming.crescendo_runner.acompletion",
            new=_attacker_mock(["escalate"]),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            crescendo_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            max_turns=2,
        )
    assert len(calls) == 2

    out = tmp_path / "crescendo-run"
    sink = RunnerResultSink(out)
    roles = {"attacker": ModelEndpoint(base_url=base_url, model="openai/attacker")}
    records = []
    for i, trial in enumerate(result.trials):
        record = new_record(
            run_id="f" * 32,
            ordinal=i,
            method="crescendo",
            strategy="escalation",
            goal=result.goal,
            probe=trial["prompt"],
            roles=roles,
        )
        record = record.model_copy(
            update={
                "response": trial["response"],
                "capture_complete": trial["capture_complete"],
                "judge_verdict": trial["judge_verdict"],
                "status": "complete",
            }
        )
        sink.stage(record)
        records.append(record)
    sink.export(records)
    sink.close()

    before = len(calls)
    recovered = recover_runner_records(out)
    assert len(calls) == before  # recovery never replays a target call
    assert len(recovered) == len(result.trials)
    assert [r.probe for r in recovered] == [t["prompt"] for t in result.trials]


def test_invalid_config_is_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CrescendoConfig(max_turns=0)
    with pytest.raises(ValidationError):
        CrescendoConfig(max_turns=21)
    with pytest.raises(ValidationError):
        CrescendoConfig(context_window=0)


def _run(coro_fn, **kwargs):
    import asyncio

    return asyncio.run(coro_fn(**kwargs))
