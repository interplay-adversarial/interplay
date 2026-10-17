"""Unit tests for JudgePanel's verdict aggregation and IRR reporting.

No real credentials or hosted model calls: each panel member is a stub
JudgeScorer subclass with a fixed, instance-specific raw judgment, matching
the StubScorer pattern in tests/test_red_teaming_transport.py.
"""

import json
from types import SimpleNamespace

import pytest

from interplay.assessment.models import JudgeOutput, ModelEndpoint, Observation
from interplay.red_teaming.transport import (
    CallBudget,
    JudgePanel,
    JudgeScorer,
    RunBudget,
    build_judge,
    panel_agreement_report,
)


class StubScorer(JudgeScorer):
    """A fixed verdict for one judge, bypassing any hosted call."""

    def __init__(self, model: str, verdict: str, *, refs='["/response"]'):
        self.endpoint = SimpleNamespace(model=model)
        self.api_key = None
        self._raw = {
            "verdict": verdict,
            "reasoning": f"{model} says {verdict}",
            "evidence_refs_json": refs,
        }

    async def _call(self, goal, probe, observation, *, budget):
        return JudgeOutput.model_validate(self._raw), json.dumps(self._raw)


def make_panel(verdicts: list[str], aggregation: str = "majority") -> JudgePanel:
    panel = JudgePanel.__new__(JudgePanel)
    panel.aggregation = aggregation
    panel.scorers = [StubScorer(f"judge-{i}", v) for i, v in enumerate(verdicts)]
    panel._verdicts = []
    return panel


async def score_panel(panel: JudgePanel, observation: Observation | None = None):
    observation = observation or Observation(response="hello")
    budget = CallBudget(RunBudget())
    return await panel.score("goal", "probe", observation, budget=budget)


async def test_majority_clear_winner():
    panel = make_panel(["success", "success", "failure"], aggregation="majority")
    judgment, _trace = await score_panel(panel)
    assert judgment.verdict == "success"


async def test_majority_tie_is_inconclusive():
    panel = make_panel(["success", "failure"], aggregation="majority")
    judgment, _trace = await score_panel(panel)
    assert judgment.verdict == "inconclusive"


async def test_majority_three_way_split_is_inconclusive():
    panel = make_panel(["success", "failure", "inconclusive"], aggregation="majority")
    judgment, _trace = await score_panel(panel)
    assert judgment.verdict == "inconclusive"


async def test_unanimous_agreement():
    panel = make_panel(["success", "success", "success"], aggregation="unanimous")
    judgment, _trace = await score_panel(panel)
    assert judgment.verdict == "success"


async def test_unanimous_disagreement_is_inconclusive():
    panel = make_panel(["success", "success", "failure"], aggregation="unanimous")
    judgment, _trace = await score_panel(panel)
    assert judgment.verdict == "inconclusive"


async def test_two_judges_majority_and_unanimous_are_identical():
    agree = make_panel(["success", "success"], aggregation="majority")
    judgment, _trace = await score_panel(agree)
    assert judgment.verdict == "success"

    disagree = make_panel(["success", "failure"], aggregation="majority")
    judgment, _trace = await score_panel(disagree)
    assert judgment.verdict == "inconclusive"  # same result unanimous would give


async def test_aggregated_evidence_refs_are_the_supported_union():
    panel = make_panel(["success", "success"], aggregation="majority")
    panel.scorers[1]._raw["evidence_refs_json"] = '["/logs/0"]'
    judgment, _trace = await score_panel(panel, Observation(response="hello", logs_json='["log"]'))
    refs = json.loads(judgment.evidence_refs_json)
    assert set(refs) == {"/response", "/logs/0"}


async def test_trace_retains_every_judges_individual_verdict():
    panel = make_panel(["success", "failure"], aggregation="majority")
    _judgment, trace = await score_panel(panel)
    detail = json.loads(trace)
    assert detail["aggregation"] == "majority"
    assert {j["model"] for j in detail["judges"]} == {"judge-0", "judge-1"}
    assert {j["verdict"] for j in detail["judges"]} == {"success", "failure"}


async def test_agreement_report_none_with_fewer_than_two_cases():
    panel = make_panel(["success", "success"])  # 2 judges, but no .score() call made yet -> 0 cases
    report, reason = panel.agreement_report()
    assert report is None
    assert reason == "insufficient-judged-cases"


def test_agreement_report_none_with_fewer_than_two_judges():
    panel = make_panel(
        ["success"]
    )  # bypasses the constructor's own >=2 guard, as a defensive check
    report, reason = panel.agreement_report()
    assert report is None
    assert reason == "insufficient-judges"


async def test_agreement_report_populated_after_two_cases():
    panel = make_panel(["success", "success"])
    await score_panel(panel, Observation(response="case one"))
    await score_panel(panel, Observation(response="case two"))
    report, reason = panel.agreement_report()
    assert reason is None
    assert report["n_judges"] == 2
    assert report["n_cases"] == 2


async def test_agreement_report_reflects_real_disagreement():
    panel = make_panel(["success", "failure"])
    await score_panel(panel, Observation(response="case one"))
    panel.scorers[1]._raw["verdict"] = "success"
    await score_panel(panel, Observation(response="case two"))
    report, reason = panel.agreement_report()
    assert reason is None
    # Judge 1 disagreed on case one and agreed on case two -- alpha should be
    # well below perfect agreement (1.0), not a fixed placeholder.
    assert report["alpha"] < 1.0


async def test_agreement_report_alpha_is_not_estimated_when_judges_never_vary():
    # Every judge says "success" on every case: judge-kappa >= 0.4.0 reports alpha=None
    # with a reason, not the 1.0 ("perfect agreement") that 0.2.x returned for no variation.
    panel = make_panel(["success", "success", "success"])
    for n in range(3):
        await score_panel(panel, Observation(response=f"case {n}"))
    report, reason = panel.agreement_report()
    assert reason is None  # the report exists; it is alpha itself that is undefined
    assert report["n_judges"] == 3
    assert report["n_cases"] == 3
    assert report["alpha"] is None
    assert report["alpha_not_estimated_reason"] == "no_score_variation"


async def _score_with_verdicts(panel: JudgePanel, per_case: list[list[str]]) -> None:
    for n, verdicts in enumerate(per_case):
        for scorer, verdict in zip(panel.scorers, verdicts, strict=True):
            scorer._raw["verdict"] = verdict
        await score_panel(panel, Observation(response=f"case {n}"))


async def test_agreement_report_interval_needs_five_judged_cases():
    four = [
        ["success", "success"],
        ["failure", "failure"],
        ["success", "failure"],
        ["failure", "failure"],
    ]
    panel = make_panel(["success", "success"])
    await _score_with_verdicts(panel, four)
    report, reason = panel.agreement_report()
    assert reason is None
    assert report["alpha"] is not None
    assert report["alpha_ci_low"] is None and report["alpha_ci_high"] is None

    panel = make_panel(["success", "success"])
    await _score_with_verdicts(panel, [*four, ["success", "success"]])
    report, reason = panel.agreement_report()
    assert reason is None
    assert report["n_cases"] == 5
    assert report["alpha_not_estimated_reason"] is None
    assert report["alpha_ci_low"] is not None and report["alpha_ci_high"] is not None
    assert report["alpha_ci_low"] <= report["alpha"] <= report["alpha_ci_high"]


def test_constructor_rejects_fewer_than_two_endpoints():
    with pytest.raises(ValueError, match="judge-panel-needs-at-least-two-judges"):
        JudgePanel([ModelEndpoint(base_url="https://judge.example/v1", model="m")], api_key="k")


def test_build_judge_returns_none_without_a_judge_model():
    assert build_judge(None, None, base_url="https://judge.example/v1", api_key="k") is None


def test_build_judge_returns_a_lone_scorer_without_secondary_models():
    judge = build_judge("openai/judge", None, base_url="https://judge.example/v1", api_key="k")
    assert isinstance(judge, JudgeScorer) and not isinstance(judge, JudgePanel)


def test_build_judge_returns_a_panel_with_secondary_models():
    judge = build_judge(
        "openai/judge", ["openai/judge-2"], base_url="https://judge.example/v1", api_key="k"
    )
    assert isinstance(judge, JudgePanel)
    assert [s.endpoint.model for s in judge.scorers] == ["openai/judge", "openai/judge-2"]


def test_panel_agreement_report_insufficient_judges_for_none_or_lone_scorer():
    assert panel_agreement_report(None) == (None, "insufficient-judges")
    lone = build_judge("openai/judge", None, base_url="https://judge.example/v1", api_key="k")
    assert panel_agreement_report(lone) == (None, "insufficient-judges")


async def test_panel_agreement_report_delegates_to_the_panel():
    panel = make_panel(["success", "success"])
    await score_panel(panel, Observation(response="case one"))
    await score_panel(panel, Observation(response="case two"))
    report, reason = panel_agreement_report(panel)
    assert reason is None
    assert report == panel.agreement_report()[0]
