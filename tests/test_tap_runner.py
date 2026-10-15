"""Synthetic loopback tests for the TAP (Tree of Attacks with Pruning) runner.

No real credentials or hosted model calls: the target is a local HTTP fixture;
the attacker/evaluator go through a mocked `acompletion`; the judge's model
call (`JudgeScorer._call`) is mocked directly so verdicts are deterministic.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from interplay.assessment.models import JudgeOutput
from interplay.red_teaming.tap_runner import TapSearchConfig, tap_attack


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


def _attacker_evaluator_mock(evaluator_scores: dict[str, str] | None = None):
    """A single any_llm.acompletion stand-in used for both attacker and evaluator
    calls, distinguished by the system prompt. The attacker always names its
    strategy in the variant text so the evaluator mock (and tests) can key off it."""
    evaluator_scores = evaluator_scores or {}

    async def side_effect(**kwargs):
        system = kwargs["messages"][0]["content"]
        if "Evaluate how likely" in system:
            prompt = kwargs["messages"][1]["content"]
            score = "0.5"
            for marker, value in evaluator_scores.items():
                if marker in prompt:
                    score = value
                    break
            return MagicMock(choices=[MagicMock(message=MagicMock(content=score))])
        # Attacker: embed the requested strategy in the variant text itself.
        strategy = system.split("strategy: ")[1].split(".")[0]
        return MagicMock(choices=[MagicMock(message=MagicMock(content=f"variant-{strategy}"))])

    return AsyncMock(side_effect=side_effect)


def test_pruned_branches_never_query_the_target(endpoint):
    base_url, calls = endpoint
    with patch(
        "interplay.red_teaming.tap_runner.acompletion",
        new=_attacker_evaluator_mock({"logical-appeal": "0.9", "role-play": "0.1"}),
    ):
        pytest_result = _run(
            tap_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            evaluator_model="openai/evaluator",
            judge_model=None,
            beam_width=1,
            branching_factor=2,
            n_iterations=1,
        )
    # branching_factor=2, beam_width=1: exactly one of the two candidates is
    # admitted, the other pruned -- and only the admitted one hits the target.
    assert len(calls) == 1
    pruned = [t for t in pytest_result.trials if t["pruned"]]
    admitted = [t for t in pytest_result.trials if not t["pruned"]]
    assert len(pruned) == 1 and len(admitted) == 1
    assert pruned[0]["status"] == "pruned" and pruned[0]["response"] is None
    assert admitted[0]["evaluator_score"] == 0.9  # the higher-scored one was admitted


def test_high_evaluator_score_judge_failure_is_not_reported_successful(endpoint):
    base_url, _ = endpoint

    def fake_call(goal, probe, observation, *, budget):
        verdict = "failure" if "logical-appeal" in probe else "success"
        reasoning = "Matches goal." if verdict == "success" else "Does not match."
        refs = '["/response"]'
        return JudgeOutput(verdict=verdict, reasoning=reasoning, evidence_refs_json=refs), "{}"

    with (
        patch(
            "interplay.red_teaming.tap_runner.acompletion",
            new=_attacker_evaluator_mock({"logical-appeal": "0.9", "role-play": "0.1"}),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            tap_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            evaluator_model="openai/evaluator",
            judge_model="openai/judge",
            beam_width=2,
            branching_factor=2,
            n_iterations=1,
        )
    # Both candidates are admitted (beam_width == branching_factor): the
    # high-evaluator-score one (logical-appeal, 0.9) is judged a failure, the
    # low-evaluator-score one (role-play, 0.1) is judged a success. Best
    # selection must follow the judged outcome, not the evaluator score.
    assert result.confirmed_success is True
    assert "role-play" in result.best_prompt
    assert result.best_score == 0.1


def test_early_success_stop_reports_how_many_admitted_were_actually_queried(endpoint):
    """PR Agent finding: search_trajectory must not claim the full admitted
    beam ran when an early success stopped it partway through."""
    base_url, calls = endpoint

    def fake_call(goal, probe, observation, *, budget):
        # The first-processed admitted candidate (logical-appeal, sorted first
        # by its evaluator score) succeeds immediately, before the other two
        # admitted candidates are ever queried.
        verdict = "success" if "logical-appeal" in probe else "failure"
        return JudgeOutput(verdict=verdict, reasoning="r", evidence_refs_json='["/response"]'), "{}"

    with (
        patch(
            "interplay.red_teaming.tap_runner.acompletion",
            new=_attacker_evaluator_mock(
                {"logical-appeal": "0.9", "role-play": "0.5", "authority-endorsement": "0.1"}
            ),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            tap_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            evaluator_model="openai/evaluator",
            judge_model="openai/judge",
            beam_width=3,
            branching_factor=3,
            n_iterations=1,
        )
    assert result.stop_reason == "success"
    assert len(calls) == 1  # only the one successful candidate ever queried the target
    trajectory = result.search_trajectory[0]
    assert trajectory["admitted"] == 3
    assert trajectory["admitted_queried"] == 1


def test_missing_evidence_stays_inconclusive_not_fabricated_success(endpoint):
    base_url, _ = endpoint

    def fake_call(goal, probe, observation, *, budget):
        return (
            JudgeOutput(verdict="success", reasoning="Claims success.", evidence_refs_json="[]"),
            "{}",
        )

    with (
        patch("interplay.red_teaming.tap_runner.acompletion", new=_attacker_evaluator_mock()),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            tap_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            evaluator_model="openai/evaluator",
            judge_model="openai/judge",
            beam_width=1,
            branching_factor=1,
            n_iterations=1,
        )
    assert result.confirmed_success is False
    trial = result.trials[0]
    # JudgeScorer itself downgrades an unsupported "success" claim to
    # inconclusive; the trial is still a completed (not failed) assessment.
    assert trial["judge_verdict"] == "inconclusive" and trial["status"] == "complete"
    assert trial["error_code"] is None


def test_no_judge_configured_leaves_every_trial_inconclusive(endpoint):
    base_url, calls = endpoint
    with patch("interplay.red_teaming.tap_runner.acompletion", new=_attacker_evaluator_mock()):
        result = _run(
            tap_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            evaluator_model="openai/evaluator",
            judge_model=None,
            beam_width=1,
            branching_factor=1,
            n_iterations=1,
        )
    assert len(calls) == 1
    assert result.confirmed_success is False
    assert result.trials[0]["judge_verdict"] == "inconclusive"
    assert result.trials[0]["error_code"] == "no-judge-configured"


def test_no_secondary_judge_reports_agreement_unavailable_not_a_placeholder(endpoint):
    base_url, _ = endpoint

    def fake_call(goal, probe, observation, *, budget):
        return JudgeOutput(verdict="failure", reasoning="r", evidence_refs_json="[]"), "{}"

    with (
        patch("interplay.red_teaming.tap_runner.acompletion", new=_attacker_evaluator_mock()),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            tap_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            evaluator_model="openai/evaluator",
            judge_model="openai/judge",
            beam_width=1,
            branching_factor=1,
            n_iterations=1,
        )
    assert result.irr_report is None
    assert result.irr_unavailable_reason == "insufficient-judges"


def test_secondary_judge_models_form_a_real_panel_with_irr(endpoint):
    base_url, _ = endpoint
    # The first admitted candidate must not reach a panel-confirmed "success" --
    # that would stop the search before the second candidate is ever queried,
    # leaving only one scored trial (IRR needs at least two cases).
    primary_verdicts = iter(["failure", "success"])
    secondary_verdicts = iter(["success", "failure"])

    def fake_call(self, goal, probe, observation, *, budget):
        verdicts = primary_verdicts if self.endpoint.model == "openai/judge" else secondary_verdicts
        return (
            JudgeOutput(verdict=next(verdicts), reasoning="r", evidence_refs_json='["/response"]'),
            "{}",
        )

    with (
        patch("interplay.red_teaming.tap_runner.acompletion", new=_attacker_evaluator_mock()),
        patch(
            "interplay.red_teaming.transport.JudgeScorer._call",
            autospec=True,
            side_effect=fake_call,
        ),
    ):
        result = _run(
            tap_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            evaluator_model="openai/evaluator",
            judge_model="openai/judge",
            secondary_judge_models=["openai/judge-2"],
            judge_aggregation="unanimous",
            beam_width=2,
            branching_factor=2,
            n_iterations=1,
        )
    # Panel disagreed on both candidates (unanimous -> inconclusive each time), so
    # neither is a confirmed success, but the IRR report is still real, not a
    # fixed placeholder (the old code's bug: a fixed 0.85).
    assert result.confirmed_success is False
    assert result.irr_unavailable_reason is None
    assert result.irr_report is not None
    assert result.irr_report["n_judges"] == 2
    assert result.irr_report["alpha"] != 0.85  # the old fixed Cohen's-kappa placeholder
    judged_trial = next(t for t in result.trials if not t["pruned"])
    assert judged_trial["judge_panel_json"] is not None
    assert json.loads(judged_trial["judge_panel_json"])["aggregation"] == "unanimous"


def test_invalid_search_config_is_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TapSearchConfig(beam_width=0)
    with pytest.raises(ValidationError):
        TapSearchConfig(branching_factor=50)
    with pytest.raises(ValidationError):
        TapSearchConfig(n_iterations=-1)


def test_deadline_exhaustion_preserves_prior_trials_without_raising(endpoint):
    base_url, _ = endpoint

    async def slow_side_effect(**kwargs):
        import asyncio

        await asyncio.sleep(0.6)
        system = kwargs["messages"][0]["content"]
        if "Evaluate how likely" in system:
            return MagicMock(choices=[MagicMock(message=MagicMock(content="0.5"))])
        return MagicMock(choices=[MagicMock(message=MagicMock(content="variant"))])

    def fake_call(goal, probe, observation, *, budget):
        return JudgeOutput(verdict="inconclusive", reasoning="r", evidence_refs_json="[]"), "{}"

    with (
        patch(
            "interplay.red_teaming.tap_runner.acompletion",
            new=AsyncMock(side_effect=slow_side_effect),
        ),
        patch("interplay.red_teaming.transport.JudgeScorer._call", side_effect=fake_call),
    ):
        result = _run(
            tap_attack,
            goal="test",
            target_url=base_url,
            attacker_model="openai/attacker",
            evaluator_model="openai/evaluator",
            judge_model="openai/judge",
            beam_width=1,
            branching_factor=1,
            n_iterations=5,
            campaign_seconds=2,
        )
    assert result.stop_reason == "campaign-deadline"
    assert len(result.trials) >= 1  # the first iteration's trial was kept


def _run(coro_fn, **kwargs):
    import asyncio

    return asyncio.run(coro_fn(**kwargs))
