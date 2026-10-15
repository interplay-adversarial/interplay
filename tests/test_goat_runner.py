"""Synthetic loopback tests for the GOAT (Generative Offensive Agent Tester) runner.

No real credentials or hosted model calls: the target is a local HTTP fixture;
the attacker's decision call (`acompletion`) is mocked; the judge's model call
(`JudgeScorer._call`) is mocked directly so verdicts are deterministic.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from interplay.assessment.models import JudgeOutput
from interplay.red_teaming.goat_runner import GoatConfig, goat_attack


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


def _attacker_mock(decisions: list[str]):
    """Each call returns the next raw attacker decision text, in order."""
    it = iter(decisions)

    async def side_effect(**kwargs):
        return MagicMock(choices=[MagicMock(message=MagicMock(content=next(it)))])

    return AsyncMock(side_effect=side_effect)


def _decision(strategy: str, prompt: str, explanation: str = "because") -> str:
    return json.dumps({"strategy": strategy, "prompt": prompt, "explanation": explanation})


def test_strategy_switches_to_a_different_strategy_after_a_failed_turn(endpoint):
    base_url, calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        verdict = "success" if "role-play" in probe else "failure"
        return (
            JudgeOutput(verdict=verdict, reasoning="r", evidence_refs_json='["/response"]'),
            "{}",
        )

    with (
        patch(
            "interplay.red_teaming.goat_runner.acompletion",
            new=_attacker_mock([_decision("Persona modulation", "role-play prompt")]),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            goat_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            strategy_pool=["Logical appeal", "Persona modulation"],
            max_turns=3,
        )
    # Turn 0 ("seed") fails, triggering a switch to Persona modulation for turn 1,
    # which the judge confirms -- a terminal success, so no turn 2 is attempted.
    assert len(calls) == 2
    assert result.stop_reason == "success"
    assert result.confirmed_success is True
    assert [t["strategy"] for t in result.trials] == ["seed", "Persona modulation"]
    assert result.trials[1]["parent_id"] == result.trials[0]["attempt_id"]
    assert result.trials[1]["prompt"] == "role-play prompt"


def test_secondary_judge_models_form_a_panel_with_irr(endpoint):
    base_url, calls = endpoint
    judge_a_verdicts = iter(["success", "success"])
    judge_b_verdicts = iter(["failure", "success"])

    def fake_call(self, goal, probe, observation, *, budget):
        verdicts = judge_a_verdicts if self.endpoint.model == "openai/judge" else judge_b_verdicts
        return (
            JudgeOutput(verdict=next(verdicts), reasoning="r", evidence_refs_json='["/response"]'),
            "{}",
        )

    with (
        patch(
            "interplay.red_teaming.goat_runner.acompletion",
            new=_attacker_mock([_decision("Persona modulation", "turn-2 prompt")]),
        ),
        patch(
            "interplay.red_teaming.transport.JudgeScorer._call",
            autospec=True,
            side_effect=fake_call,
        ),
    ):
        result = _run(
            goat_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            secondary_judge_models=["openai/judge-2"],
            judge_aggregation="unanimous",
            strategy_pool=["Logical appeal", "Persona modulation"],
            max_turns=3,
        )
    # Turn 0: panel split (unanimous -> inconclusive), so the campaign continues;
    # turn 1: panel agrees "success", which is terminal.
    assert len(calls) == 2
    assert result.stop_reason == "success"
    assert result.confirmed_success is True
    assert result.trials[0]["judge_verdict"] == "inconclusive"
    assert result.trials[1]["judge_verdict"] == "success"
    assert json.loads(result.trials[1]["judge_panel_json"])["aggregation"] == "unanimous"
    assert result.irr_unavailable_reason is None
    assert result.irr_report["n_judges"] == 2
    assert result.irr_report["n_cases"] == 2


def test_malformed_decision_is_rejected_not_executed_as_a_prompt(endpoint):
    base_url, calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        return JudgeOutput(verdict="failure", reasoning="r", evidence_refs_json="[]"), "{}"

    with (
        patch(
            "interplay.red_teaming.goat_runner.acompletion",
            new=_attacker_mock(["this is not JSON, just free text the runner must not execute"]),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            goat_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            strategy_pool=["Logical appeal", "Persona modulation"],
            max_turns=3,
        )
    # Only the seed turn (turn 0) ever queries the target; the malformed
    # decision for turn 1 stops the campaign instead of becoming a trial.
    assert len(calls) == 1
    assert len(result.trials) == 1
    assert result.stop_reason.startswith("attacker-output-invalid:malformed-decision")


def test_unknown_strategy_is_rejected_not_silently_relabeled(endpoint):
    base_url, calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        return JudgeOutput(verdict="failure", reasoning="r", evidence_refs_json="[]"), "{}"

    with (
        patch(
            "interplay.red_teaming.goat_runner.acompletion",
            new=_attacker_mock([_decision("not-in-the-pool", "whatever prompt")]),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            goat_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            strategy_pool=["Logical appeal", "Persona modulation"],
            max_turns=3,
        )
    assert len(calls) == 1
    assert len(result.trials) == 1
    assert result.stop_reason == "attacker-output-invalid:unknown-strategy:not-in-the-pool"
    assert all(t["strategy"] != "unknown" for t in result.trials)


def test_executed_trajectory_alignment_strategy_bound_to_prompt_actually_sent(endpoint):
    base_url, calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        return JudgeOutput(verdict="failure", reasoning="r", evidence_refs_json="[]"), "{}"

    with (
        patch(
            "interplay.red_teaming.goat_runner.acompletion",
            new=_attacker_mock(
                [
                    _decision("Logical appeal", "appeal-prompt"),
                    _decision("Persona modulation", "persona-prompt"),
                ]
            ),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            goat_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            strategy_pool=["Logical appeal", "Persona modulation"],
            max_turns=3,
        )
    assert result.stop_reason == "turn-budget"
    assert len(result.trials) == 3
    for trial, expected_prompt, expected_strategy in zip(
        result.trials,
        ["test", "appeal-prompt", "persona-prompt"],
        ["seed", "Logical appeal", "Persona modulation"],
        strict=True,
    ):
        assert trial["prompt"] == expected_prompt
        assert trial["strategy"] == expected_strategy


def test_no_judge_configured_leaves_every_trial_inconclusive_and_incomplete(endpoint):
    base_url, calls = endpoint
    with patch(
        "interplay.red_teaming.goat_runner.acompletion",
        new=_attacker_mock([_decision("Logical appeal", "appeal-prompt")]),
    ):
        result = _run(
            goat_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model=None,
            strategy_pool=["Logical appeal"],
            max_turns=2,
        )
    assert len(calls) == 2
    assert result.confirmed_success is False
    assert all(t["judge_verdict"] == "inconclusive" for t in result.trials)
    assert all(t["error_code"] == "no-judge-configured" for t in result.trials)


def test_target_failure_is_retained_as_an_incomplete_trial_not_lost(endpoint):
    base_url, _calls = endpoint
    with patch(
        "interplay.red_teaming.goat_runner.acompletion",
        new=_attacker_mock([_decision("Logical appeal", "appeal-prompt")]),
    ):
        result = _run(
            goat_attack,
            goal="test",
            target_url="http://127.0.0.1:1/v1",  # nothing listening: connection fails
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            strategy_pool=["Logical appeal"],
            max_turns=2,
        )
    assert result.stop_reason == "target-observation-failed"
    assert len(result.trials) == 1
    assert result.trials[0]["status"] == "incomplete"
    assert result.trials[0]["error_code"].startswith("target-observation-failed:")


def test_conversation_mode_sends_accumulated_turns_to_the_target(endpoint):
    base_url, calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        return JudgeOutput(verdict="failure", reasoning="r", evidence_refs_json="[]"), "{}"

    with (
        patch(
            "interplay.red_teaming.goat_runner.acompletion",
            new=_attacker_mock([_decision("Logical appeal", "appeal-prompt")]),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        _run(
            goat_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            strategy_pool=["Logical appeal"],
            max_turns=2,
            target_mode="conversation",
        )
    assert len(calls[0]["messages"]) == 1
    # Turn 1 carries turn 0's user prompt and the target's own turn-0 reply.
    assert len(calls[1]["messages"]) == 3
    assert calls[1]["messages"][0] == {"role": "user", "content": "test"}
    assert calls[1]["messages"][1] == {"role": "assistant", "content": "SYNTHETIC-CANARY"}
    assert calls[1]["messages"][2] == {"role": "user", "content": "appeal-prompt"}


def test_stateless_mode_sends_only_the_current_prompt(endpoint):
    base_url, calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        return JudgeOutput(verdict="failure", reasoning="r", evidence_refs_json="[]"), "{}"

    with (
        patch(
            "interplay.red_teaming.goat_runner.acompletion",
            new=_attacker_mock([_decision("Logical appeal", "appeal-prompt")]),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        _run(
            goat_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            strategy_pool=["Logical appeal"],
            max_turns=2,
            target_mode="stateless",
        )
    assert len(calls[1]["messages"]) == 1
    assert calls[1]["messages"][0] == {"role": "user", "content": "appeal-prompt"}


def test_success_is_terminal_no_further_attacker_call(endpoint):
    base_url, calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        return (
            JudgeOutput(verdict="success", reasoning="r", evidence_refs_json='["/response"]'),
            "{}",
        )

    attacker_mock = _attacker_mock([_decision("Logical appeal", "unused-if-called")])
    with (
        patch("interplay.red_teaming.goat_runner.acompletion", new=attacker_mock),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            goat_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            strategy_pool=["Logical appeal"],
            max_turns=5,
        )
    assert attacker_mock.await_count == 0  # the seed turn succeeds; no decision was ever requested
    assert len(calls) == 1
    assert result.stop_reason == "success"
    assert result.turns == 1


def test_deadline_exhaustion_preserves_prior_trials_without_raising(endpoint):
    base_url, _calls = endpoint

    async def slow_side_effect(**kwargs):
        import asyncio

        await asyncio.sleep(0.6)
        return MagicMock(
            choices=[MagicMock(message=MagicMock(content=_decision("Logical appeal", "p")))]
        )

    def fake_call(goal, probe, observation, *, budget):
        return JudgeOutput(verdict="inconclusive", reasoning="r", evidence_refs_json="[]"), "{}"

    with (
        patch(
            "interplay.red_teaming.goat_runner.acompletion",
            new=AsyncMock(side_effect=slow_side_effect),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            goat_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            judge_model="openai/judge",
            strategy_pool=["Logical appeal"],
            max_turns=5,
            campaign_seconds=1,
        )
    assert result.stop_reason == "campaign-deadline"
    assert len(result.trials) >= 1  # turn 0's trial was kept


def test_invalid_config_is_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GoatConfig(max_turns=0)
    with pytest.raises(ValidationError):
        GoatConfig(strategy_pool=())
    with pytest.raises(ValidationError):
        GoatConfig(strategy_pool=("dup", "dup"))


def _run(coro_fn, **kwargs):
    import asyncio

    return asyncio.run(coro_fn(**kwargs))
