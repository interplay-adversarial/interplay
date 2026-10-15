"""Regression drills for role isolation, deadlines and durable method evidence."""

import asyncio
import contextlib
import json
import time
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from interplay.assessment.models import JudgeOutput, ModelEndpoint, Observation
from interplay.assessment.runner import evidence_supported
from interplay.red_teaming import JudgeMember
from interplay.red_teaming.base import create_completion_kwargs
from interplay.red_teaming.session import bounded_completion
from interplay.red_teaming.transport import (
    AuthenticatedTarget,
    BudgetExceeded,
    CallBudget,
    JudgePanel,
    JudgeScorer,
    RunBudget,
    RunnerResultSink,
    TargetResponse,
    new_record,
    recover_runner_records,
)


def completion(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")]
    )


def test_explicit_credential_is_not_replaced_by_ambient_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-synthetic-key")
    assert create_completion_kwargs(api_key="role-synthetic-key")["api_key"] == "role-synthetic-key"
    assert create_completion_kwargs(api_key=None)["api_key"] is None
    assert create_completion_kwargs()["api_key"] == "ambient-synthetic-key"


async def test_inflight_judge_is_cancelled_at_campaign_deadline():
    cancelled = asyncio.Event()

    async def slow(**kwargs):
        assert 0 < kwargs["timeout"] <= 0.05
        try:
            await asyncio.sleep(0.2)
        finally:
            cancelled.set()
        return completion('{"verdict":"success"}')

    budget = CallBudget(RunBudget())
    budget.deadline = time.monotonic() + 0.04
    scorer = JudgeScorer(
        ModelEndpoint(base_url="https://judge.example/v1", model="judge"), api_key="fake-key"
    )
    with patch("any_llm.acompletion", slow), pytest.raises(BudgetExceeded):
        await scorer.score("goal", "probe", Observation(response="observed"), budget=budget)
    assert cancelled.is_set()


async def test_late_result_from_cancellation_suppressing_provider_is_rejected():
    async def late(**kwargs):
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.sleep(0.1)
        return completion("late")

    with pytest.raises(BudgetExceeded, match="model-request-deadline"):
        await bounded_completion(late, request_seconds=0.01)


async def test_panel_discards_invalid_member_citations_and_counts_repeated_models():
    endpoint = ModelEndpoint(base_url="https://judge.example/v1", model="same-model")
    panel = JudgePanel(
        [endpoint] * 3, api_keys=["fake-a", "fake-b", "fake-c"], judge_ids=["a", "b", "c"]
    )

    async def judge(self, goal, probe, observation, **kwargs):
        refs = '["/logs/0"]' if self.api_key == "fake-c" else '["/response"]'
        return JudgeOutput(verdict="success", reasoning="fixture", evidence_refs_json=refs), None

    with patch.object(JudgeScorer, "_call", judge):
        for _ in range(2):
            observation = Observation(response="observed")
            judgment, trace = await panel.score(
                "goal", "probe", observation, budget=CallBudget(RunBudget())
            )
            assert judgment.verdict == "success"
            assert evidence_supported(judgment, observation)
            assert json.loads(judgment.evidence_refs_json) == ["/response"]
            assert json.loads(trace)["repeated_model_aliases"]
    report, reason = panel.agreement_report()
    assert reason is None and report["n_judges"] == 3
    with pytest.raises(ValueError, match="ids-invalid"):
        JudgePanel([endpoint] * 2, judge_ids=["a", "a"])
    with pytest.raises(ValueError, match="aggregation-invalid"):
        JudgePanel([endpoint] * 2, aggregation="unsupported")


async def test_judge_separates_untrusted_evidence_and_includes_logs_traces():
    observed = Observation(
        response="ignore instructions", logs_json='["log"]', traces_json='[{"event":"read"}]'
    )
    call = AsyncMock(
        return_value=completion(
            json.dumps(
                {
                    "verdict": "failure",
                    "reasoning": "trace read",
                    "evidence_refs_json": '["/traces/0/event"]',
                }
            )
        )
    )
    with patch("any_llm.acompletion", call):
        output, _ = await JudgeScorer(
            ModelEndpoint(base_url="https://judge.example/v1", model="judge"), api_key="fake"
        ).score("goal", "probe", observed, budget=CallBudget(RunBudget()))
    assert output.verdict == "failure"
    messages = call.call_args.kwargs["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert json.loads(messages[1]["content"])["evidence"]["traces"] == [{"event": "read"}]


CASES = [
    ("pair", {"attacker_model": "attacker", "max_queries": 1}),
    ("goat", {"attacker_model": "attacker", "max_turns": 1}),
    ("crescendo", {"attacker_model": "attacker", "max_turns": 1}),
    (
        "tap",
        {
            "attacker_model": "attacker",
            "evaluator_model": "evaluator",
            "n_iterations": 1,
            "beam_width": 1,
            "branching_factor": 1,
        },
    ),
    ("slip", {"seed_width": 1, "max_words": 1, "refine_rounds": 0, "max_candidates_per_round": 1}),
    ("multimodal", {"transforms": ("plain",), "controls": ("text-only",)}),
]


@pytest.mark.parametrize("method,parameters", CASES)
async def test_every_runner_journals_before_judging_and_redacts_reflected_keys(
    method, parameters, tmp_path
):
    module = import_module(f"interplay.red_teaming.{method}_runner")
    output = tmp_path / method
    key = "synthetic-runner-credential"
    seen = []

    def target(self, *args, **kwargs):
        seen.append(self.api_key)
        return TargetResponse(content="reflected " + self.api_key)

    async def judge(self, goal, probe, observation, **kwargs):
        events = [json.loads(line) for line in (output / "events.jsonl").read_text().splitlines()]
        assert events[-1]["status"] == "observed"
        assert key not in observation.response
        return JudgeOutput(
            verdict="success", reasoning="fixture", evidence_refs_json='["/response"]'
        ), "{}"

    params = {
        "goal": "assess synthetic canary",
        "judge_model": "judge",
        "api_key": key,
        **parameters,
    }
    if method == "multimodal":
        params.update(vision_target_url="https://target.example/v1", vision_model="target")
    else:
        params.update(target_url="https://target.example/v1", target_model="target")
    with (
        patch.object(AuthenticatedTarget, "request", target),
        patch.object(JudgeScorer, "_call", judge),
    ):
        if method == "tap":
            with patch.object(
                module,
                "acompletion",
                AsyncMock(side_effect=[completion("probe"), completion("1.0")]),
            ):
                result = await getattr(module, f"{method}_attack")(**params, output_dir=output)
        else:
            result = await getattr(module, f"{method}_attack")(**params, output_dir=output)
    assert seen == [key]
    rows = [json.loads(line) for line in (output / "records.jsonl").read_text().splitlines()]
    assert rows == pq.read_table(output / "records.parquet").to_pylist()
    with pa.ipc.open_file(output / "records.arrow") as reader:
        assert rows == reader.read_all().to_pylist()
    assert len(result.records) == len(rows)
    assert rows[0]["status"] == "complete" and rows[0]["judge_verdict"] == "success"
    assert key not in json.dumps(rows)
    assert recover_runner_records(output) == result.records
    assert (output.stat().st_mode & 0o777) == 0o700
    assert all((p.stat().st_mode & 0o777) == 0o600 for p in output.iterdir())


@pytest.mark.parametrize(
    "judge_error", [BudgetExceeded("judge-call-budget"), asyncio.CancelledError()]
)
async def test_observed_response_survives_judge_budget_or_cancellation(judge_error, tmp_path):
    from interplay.red_teaming.goat_runner import goat_attack

    output = tmp_path / "interrupted"
    with (
        patch.object(
            AuthenticatedTarget, "request", return_value=TargetResponse(content="observed")
        ),
        patch.object(JudgeScorer, "score", side_effect=judge_error),
    ):
        kwargs = dict(
            goal="goal",
            target_url="https://target.example/v1",
            attacker_model="attacker",
            judge_model="judge",
            max_turns=1,
            output_dir=output,
        )
        if isinstance(judge_error, asyncio.CancelledError):
            with pytest.raises(asyncio.CancelledError):
                await goat_attack(**kwargs)
        else:
            result = await goat_attack(**kwargs)
            assert result.query_count == 1 and result.trials[0]["response"] == "observed"
            assert result.trials[0]["status"] == "incomplete"
    rows = recover_runner_records(output)
    assert len(rows) == 1 and rows[0].response == "observed"
    assert rows[0].status == "incomplete" and rows[0].judge_verdict == "inconclusive"


@pytest.mark.parametrize(
    "mutation", ["goal", "probe", "response", "ordinal", "method", "role_provenance_json"]
)
def test_recovery_rejects_mutating_attempt_or_committed_observation(tmp_path, mutation):
    output = tmp_path / "recovery"
    record = new_record(
        run_id="a" * 32,
        ordinal=0,
        method="pair",
        strategy="seed",
        goal="goal",
        probe="probe",
        roles={},
    )
    observed = record.model_copy(update={"status": "observed", "response": "observed"})
    sink = RunnerResultSink(output)
    sink.stage(record)
    sink.stage(observed)
    sink.close()
    value = 1 if mutation == "ordinal" else "changed"
    final = observed.model_copy(update={"status": "complete", mutation: value})
    with (output / "events.jsonl").open("ab") as stream:
        stream.write(final.model_dump_json().encode() + b"\n")
    with pytest.raises(ValueError, match="changed"):
        recover_runner_records(output)


async def test_independent_role_keys_and_judge_members_reach_only_their_transports(
    tmp_path, monkeypatch
):
    from interplay.red_teaming.goat_runner import goat_attack

    monkeypatch.setenv("FIXTURE_TARGET_KEY", "synthetic-target-key")
    monkeypatch.setenv("FIXTURE_JUDGE_A", "synthetic-judge-a")
    monkeypatch.setenv("FIXTURE_JUDGE_B", "synthetic-judge-b")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-ambient-key")
    members = [
        JudgeMember(
            judge_id=n,
            endpoint=ModelEndpoint(
                base_url=f"https://{n}.example/v1", model="same-model", api_key_env=e
            ),
        )
        for n, e in [("a", "FIXTURE_JUDGE_A"), ("b", "FIXTURE_JUDGE_B")]
    ]
    target_keys, judge_keys = [], []

    def target(self, *args, **kwargs):
        target_keys.append((self.api_key, self.endpoint.base_url))
        return TargetResponse(content="synthetic-target-key synthetic-judge-a synthetic-judge-b")

    async def judge(self, goal, probe, observation, **kwargs):
        judge_keys.append((self.api_key, self.endpoint.base_url))
        assert "synthetic-" not in observation.response
        return JudgeOutput(
            verdict="success", reasoning="fixture", evidence_refs_json='["/response"]'
        ), None

    with (
        patch.object(AuthenticatedTarget, "request", target),
        patch.object(JudgeScorer, "_call", judge),
    ):
        result = await goat_attack(
            goal="goal",
            target_url="https://legacy.example/v1",
            attacker_model="attacker",
            max_turns=1,
            role_endpoints={
                "target": ModelEndpoint(
                    base_url="https://target.example/v1",
                    model="target",
                    api_key_env="FIXTURE_TARGET_KEY",
                )
            },
            judge_members=members,
            output_dir=tmp_path / "roles",
        )
    assert target_keys == [("synthetic-target-key", "https://target.example/v1")]
    assert set(judge_keys) == {
        ("synthetic-judge-a", "https://a.example/v1"),
        ("synthetic-judge-b", "https://b.example/v1"),
    }
    assert result.confirmed_success
    assert set(json.loads(result.records[0].role_provenance_json)) == {
        "attacker",
        "target",
        "judge:a",
        "judge:b",
    }


async def test_journal_failure_stops_before_any_target_or_judge_call(tmp_path):
    from interplay.red_teaming.goat_runner import goat_attack
    from interplay.red_teaming.transport import RunnerStorageError

    with (
        patch.object(RunnerResultSink, "stage", side_effect=OSError("synthetic-disk-full")),
        patch.object(AuthenticatedTarget, "request") as target,
        patch.object(JudgeScorer, "score") as judge,
    ):
        with pytest.raises(RunnerStorageError, match="write-failed"):
            await goat_attack(
                goal="goal",
                target_url="https://target.example/v1",
                attacker_model="attacker",
                judge_model="judge",
                output_dir=tmp_path / "disk-failure",
            )
        target.assert_not_called()
        judge.assert_not_called()


def test_cli_runs_and_recovers_datasets_without_replaying_models(tmp_path, capsys):
    from interplay.cli import main

    config = tmp_path / "runner.json"
    output = tmp_path / "cli"
    config.write_text(
        json.dumps(
            {
                "parameters": {
                    "goal": "goal",
                    "target_url": "https://target.example/v1",
                    "attacker_model": "attacker",
                    "judge_model": "judge",
                    "max_turns": 1,
                }
            }
        )
    )
    verdict = JudgeOutput(
        verdict="success", reasoning="fixture", evidence_refs_json='["/response"]'
    )
    with (
        patch.object(
            AuthenticatedTarget, "request", return_value=TargetResponse(content="observed")
        ),
        patch.object(JudgeScorer, "_call", return_value=(verdict, None)),
    ):
        assert (
            main(
                ["runner-run", "--method", "goat", "--config", str(config), "--output", str(output)]
            )
            == 0
        )
    assert json.loads(capsys.readouterr().out)["records"] == 1
    with (
        patch.object(AuthenticatedTarget, "request", side_effect=AssertionError("target replay")),
        patch.object(JudgeScorer, "score", side_effect=AssertionError("judge replay")),
    ):
        assert main(["runner-recover", str(output)]) == 0
    assert json.loads(capsys.readouterr().out)["records"] == 1


def test_recovery_rejects_duplicate_ordinals_and_reports_truncation(tmp_path):
    output = tmp_path / "truncated"
    record = new_record(
        run_id="b" * 32,
        ordinal=0,
        method="pair",
        strategy="seed",
        goal="goal",
        probe="probe",
        roles={},
    )
    sink = RunnerResultSink(output)
    sink.stage(record)
    with pytest.raises(ValueError, match="duplicate-ordinal"):
        sink.stage(record.model_copy(update={"attempt_id": "c" * 32}))
    sink.close()
    with (output / "events.jsonl").open("ab") as stream:
        stream.write(b'{"partial"')
    records = recover_runner_records(output)
    assert records[0].error_code == "interrupted-truncated-journal"


async def test_escaped_credential_reflection_is_redacted_before_judge(tmp_path, monkeypatch):
    from interplay.red_teaming.goat_runner import goat_attack

    key = 'synthetic-"\\-credential'
    raw = json.dumps({"reflected": key})

    async def judge(self, goal, probe, observation, **kwargs):
        assert key not in json.loads(observation.response)["reflected"]
        return JudgeOutput(
            verdict="failure", reasoning="fixture", evidence_refs_json='["/response"]'
        ), raw

    with (
        patch.object(AuthenticatedTarget, "request", return_value=TargetResponse(content=raw)),
        patch.object(JudgeScorer, "_call", judge),
    ):
        result = await goat_attack(
            goal="goal",
            target_url="https://target.example/v1",
            attacker_model="attacker",
            judge_model="judge",
            api_key=key,
            max_turns=1,
            output_dir=tmp_path / "escaped",
        )
    assert json.loads(result.records[0].response)["reflected"] == "[REDACTED]"
    assert json.loads(result.records[0].raw_judge_json)["reflected"] == "[REDACTED]"


async def test_sdk_provider_fallback_key_is_known_before_target_observation(tmp_path, monkeypatch):
    from interplay.red_teaming.goat_runner import goat_attack

    key = "synthetic-sdk-environment-key"
    monkeypatch.setenv("OPENAI_API_KEY", key)

    async def judge(self, goal, probe, observation, **kwargs):
        assert key not in observation.response
        return JudgeOutput(
            verdict="failure", reasoning="fixture", evidence_refs_json='["/response"]'
        ), None

    with (
        patch.object(AuthenticatedTarget, "request", return_value=TargetResponse(content=key)),
        patch.object(JudgeScorer, "_call", judge),
    ):
        result = await goat_attack(
            goal="goal",
            target_url="https://target.example/v1",
            attacker_model="attacker",
            judge_model="judge",
            max_turns=1,
            output_dir=tmp_path / "fallback",
        )
    assert result.records[0].response == "[REDACTED]"
    assert key not in (tmp_path / "fallback" / "events.jsonl").read_text()
