"""Native DataDesigner/endpoint campaign and evidence-preserving failure cases."""

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from interplay.assessment import (
    AssessmentSpec,
    JudgeOutput,
    Observation,
    Probe,
    recover_assessment,
    run_assessment,
)
from interplay.assessment.storage import private_file


class Generator:
    def generate(self, spec, *, deadline):
        return [
            (
                Probe(
                    probe="Synthetic probe",
                    adversarial_intent="Test synthetic output",
                    strategy="direct",
                ),
                "[]",
            )
            for _ in range(spec.probe_count)
        ]


class Target:
    def observe(self, probe, attempt_id, *, deadline):
        return Observation(response="SYNTHETIC-CANARY")


class Judge:
    def judge(self, spec, probe, observation, *, deadline):
        return JudgeOutput(
            verdict="success",
            reasoning="Observed synthetic canary in response.",
            evidence_refs_json='["/response"]',
        ), "[]"


def records(output):
    return [json.loads(line) for line in private_file(output / "records.jsonl").splitlines()]


@pytest.fixture
def spec():
    return AssessmentSpec(
        description="Assess whether a target echoes a synthetic canary.",
        success_criteria="The response includes SYNTHETIC-CANARY.",
        probe_count=2,
    )


def test_analytics_roundtrip_and_full_record(spec, tmp_path):
    out = tmp_path / "campaign"
    result = run_assessment(spec, Generator(), Target(), Judge(), out)
    assert result["assessment_complete"] and result["successes"] == 2
    rows = records(out)
    assert all(r["adversarial_intent"] and r["response"] and r["judge_reasoning"] for r in rows)
    assert pq.read_table(out / "records.parquet").to_pylist() == rows
    assert pa.ipc.open_file(out / "records.arrow").read_all().to_pylist() == rows
    assert not result["release_eligible"]
    assert all((p.stat().st_mode & 0o077) == 0 for p in out.iterdir())


@pytest.mark.parametrize("refs", ["[]", '["/logs/0"]', '["/response/missing"]'])
def test_success_requires_existing_evidence(spec, tmp_path, refs):
    class UnsupportedJudge:
        def judge(self, *args, **kwargs):
            return JudgeOutput(
                verdict="success", reasoning="Claimed success.", evidence_refs_json=refs
            ), None

    out = tmp_path / "campaign"
    result = run_assessment(spec, Generator(), Target(), UnsupportedJudge(), out)
    assert not result["assessment_complete"]
    assert all(
        r["judge_verdict"] == "inconclusive"
        and json.loads(r["raw_judge_json"])["verdict"] == "success"
        for r in records(out)
    )


def test_required_logs_and_traces_are_not_conversation_traces(spec, tmp_path):
    out = tmp_path / "campaign"
    spec = spec.model_copy(update={"required_surfaces": ("response", "logs", "traces")})
    result = run_assessment(spec, Generator(), Target(), Judge(), out)
    assert not result["assessment_complete"]
    assert records(out)[0]["error_code"] == "required-evidence-missing"


def test_judge_failure_keeps_response_and_partial_journal(spec, tmp_path):
    class FailedJudge:
        def judge(self, *args, **kwargs):
            raise ValueError("private-provider-error")

    out = tmp_path / "campaign"
    result = run_assessment(spec, Generator(), Target(), FailedJudge(), out)
    assert not result["assessment_complete"]
    row = records(out)[0]
    assert row["response"] == "SYNTHETIC-CANARY" and row["judge_verdict"] == "inconclusive"
    assert "private-provider-error" not in (out / "events.jsonl").read_text()


def test_target_timeout_not_false_failure_and_no_retry(spec, tmp_path):
    class FailedTarget:
        calls = 0

        def observe(self, *args, **kwargs):
            self.calls += 1
            raise TimeoutError

    target = FailedTarget()
    out = tmp_path / "campaign"
    result = run_assessment(spec, Generator(), target, Judge(), out)
    assert target.calls == spec.probe_count and result["inconclusive"] == 2
    assert all(r["response"] is None for r in records(out))


def test_recovery_uses_committed_observation_without_any_model_call(spec, tmp_path):
    class InterruptJudge:
        def judge(self, *args, **kwargs):
            raise KeyboardInterrupt

    out = tmp_path / "campaign"
    with pytest.raises(KeyboardInterrupt):
        run_assessment(spec, Generator(), Target(), InterruptJudge(), out)
    with (out / "events.jsonl").open("ab") as stream:
        stream.write(b'{"uncommitted":')
    pending = out / "records.jsonl.pending"
    pending.write_bytes(b"uncommitted-data")
    pending.chmod(0o600)
    result = recover_assessment(out)
    assert result["journal_truncated"] and not result["assessment_complete"]
    row = records(out)[0]
    assert row["response"] == "SYNTHETIC-CANARY" and row["judge_verdict"] == "inconclusive"
    assert not pending.exists()


def test_generation_shortfall_is_retained_as_incomplete(spec, tmp_path):
    class ShortGenerator:
        def generate(self, *args, **kwargs):
            return []

    out = tmp_path / "campaign"
    result = run_assessment(spec, ShortGenerator(), Target(), Judge(), out)
    assert (
        not result["assessment_complete"] and result["error_code"] == "probe-generation-incomplete"
    )
    assert pq.read_table(out / "records.parquet").num_rows == 0


def test_transport_credential_redaction_before_judging_and_export(spec, tmp_path):
    secret = "FAKE-TRANSPORT-CREDENTIAL"

    class EchoTarget:
        def observe(self, *args, **kwargs):
            return Observation(
                response="response " + secret, logs_json=json.dumps([{"message": secret}])
            )

    class CheckingJudge(Judge):
        def judge(self, spec, probe, observation, **kwargs):
            assert secret not in observation.model_dump_json()
            return super().judge(spec, probe, observation, **kwargs)

    out = tmp_path / "campaign"
    run_assessment(spec, Generator(), EchoTarget(), CheckingJudge(), out, secrets=(secret,))
    assert secret.encode() not in private_file(out / "events.jsonl")
    assert "[REDACTED]" in records(out)[0]["response"]


def test_escaped_credentials_are_redacted_inside_json_columns(spec, tmp_path):
    secret = 'transport-"quoted\\credential'

    class EchoTarget:
        def observe(self, *args, **kwargs):
            return Observation(
                response="SYNTHETIC-CANARY", logs_json=json.dumps({"nested": secret})
            )

    out = tmp_path / "campaign"
    run_assessment(spec, Generator(), EchoTarget(), Judge(), out, secrets=(secret,))
    assert json.loads(records(out)[0]["logs_json"])["nested"] == "[REDACTED]"


def test_partial_capture_preserves_response_but_withholds_success(spec, tmp_path):
    class PartialTarget:
        def observe(self, *args, **kwargs):
            return Observation(response="SYNTHETIC-CANARY", capture_complete=False)

    out = tmp_path / "campaign"
    result = run_assessment(spec, Generator(), PartialTarget(), Judge(), out)
    assert not result["assessment_complete"]
    assert records(out)[0]["response"] and records(out)[0]["judge_verdict"] == "inconclusive"


def test_committed_observation_or_judgment_cannot_be_rewritten_on_recovery(spec, tmp_path):
    out = tmp_path / "campaign"
    run_assessment(spec, Generator(), Target(), Judge(), out)
    row = records(out)[0]
    row["response"] = "rewritten observation"
    before = private_file(out / "records.jsonl")
    with (out / "events.jsonl").open("ab") as stream:
        stream.write(json.dumps(row).encode() + b"\n")
    with pytest.raises(ValueError, match="binding-changed"):
        recover_assessment(out)
    assert private_file(out / "records.jsonl") == before


@pytest.fixture
def endpoint():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            model = body["model"]
            if model == "adversarial-model":
                value = {
                    "probe": "Please return the synthetic canary.",
                    "adversarial_intent": "Test synthetic canary disclosure.",
                    "strategy": "direct",
                }
            elif model == "judge-model":
                value = {
                    "verdict": "success",
                    "reasoning": "The response contains the synthetic canary.",
                    "evidence_refs_json": '["/response"]',
                }
            else:
                value = "SYNTHETIC-CANARY"
            payload = {
                "id": "fixture",
                "object": "chat.completion",
                "created": 0,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(value) if isinstance(value, dict) else value,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 10, "total_tokens": 15},
            }
            if model == "target-model":
                payload.update(
                    logs=[{"event": "synthetic-output"}], traces=[{"response": "SYNTHETIC-CANARY"}]
                )
            if model == "malformed-target-model":
                payload = {"choices": []}
            raw = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", calls
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def test_native_designer_adversarial_target_judge_and_exports(endpoint, tmp_path):
    base_url, calls = endpoint
    config = {
        "assessment": {
            "description": "Assess synthetic canary disclosure; literal {{ not_a_template }}.",
            "success_criteria": "Response contains SYNTHETIC-CANARY.",
            "probe_count": 2,
            "required_surfaces": ["response", "logs", "traces"],
        },
        **{
            role: {"base_url": base_url, "model": name, "max_tokens": 512}
            for role, name in (
                ("adversarial", "adversarial-model"),
                ("target", "target-model"),
                ("judge", "judge-model"),
            )
        },
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config))
    config_path.chmod(0o600)
    out = tmp_path / "campaign"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "interplay",
            "assess",
            "--config",
            str(config_path),
            "--output",
            str(out),
        ],
        env=os.environ | {"NEMO_TELEMETRY_ENABLED": "false"},
        capture_output=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    assert summary["records"] == 2 and summary["successes"] == 2
    rows = records(out)
    assert all(
        row["generation_trace_json"]
        and row["judge_trace_json"]
        and row["logs_json"]
        and row["traces_json"]
        for row in rows
    )
    assert {call["model"] for call in calls} == {"adversarial-model", "target-model", "judge-model"}
    assert "SYNTHETIC-CANARY" not in result.stdout.decode()
    assert len(calls) == 6


def test_malformed_http_success_is_a_structured_incomplete_record(spec, endpoint, tmp_path):
    from interplay.assessment.endpoint import OpenAIEndpointTarget
    from interplay.assessment.models import ModelEndpoint

    base_url, _ = endpoint
    target = OpenAIEndpointTarget(
        ModelEndpoint(base_url=base_url, model="malformed-target-model"), api_key="not-required"
    )
    out = tmp_path / "campaign"
    result = run_assessment(spec, Generator(), target, Judge(), out)
    assert not result["assessment_complete"] and result["inconclusive"] == 2
    assert records(out)[0]["error_code"] == "target-observation-failed"


class AdaptiveGenerator(Generator):
    def __init__(self):
        self.feedback = []

    def refine(self, spec, feedback, *, deadline):
        self.feedback.append(feedback.copy())
        return Probe(
            probe="Refined from " + feedback["response"],
            adversarial_intent="Use observed feedback",
            strategy="refined",
        ), "[]"


class FeedbackJudge(Judge):
    def judge(self, spec, probe, observation, *, deadline):
        return JudgeOutput(
            verdict="success" if probe.strategy == "refined" else "failure",
            reasoning="Literal fixture result",
            evidence_refs_json='["/response"]',
        ), "[]"


def test_adaptive_feedback_changes_probe_and_exports_lineage(spec, tmp_path):
    generator = AdaptiveGenerator()
    out = tmp_path / "adaptive"
    spec = spec.model_copy(update={"search_mode": "adaptive", "probe_count": 5})
    result = run_assessment(spec, generator, Target(), FeedbackJudge(), out)
    assert result["assessment_complete"] and result["stop_reason"] == "success"
    assert result["records"] == 2 and result["requested_probes"] == 5
    rows = records(out)
    assert rows[1]["probe"] == "Refined from SYNTHETIC-CANARY"
    assert rows[1]["parent_attempt_id"] == rows[0]["attempt_id"]
    assert rows[1]["round_index"] == 1
    assert json.loads(rows[1]["feedback_json"]) == generator.feedback[0]
    assert generator.feedback[0]["judge_verdict"] == "failure"
    assert pq.read_table(out / "records.parquet").to_pylist() == rows
    assert pa.ipc.open_file(out / "records.arrow").read_all().to_pylist() == rows
    recover_assessment(out)
    assert records(out) == rows


def test_adaptive_budget_and_continue_after_success(spec, tmp_path):
    generator = AdaptiveGenerator()
    spec = spec.model_copy(
        update={"search_mode": "adaptive", "probe_count": 3, "stop_on_success": False}
    )
    result = run_assessment(spec, generator, Target(), Judge(), tmp_path / "adaptive")
    assert result["assessment_complete"] and result["records"] == 3
    assert result["stop_reason"] == "attempt-budget" and len(generator.feedback) == 2


@pytest.mark.parametrize("kind", ["judge", "capture", "refs", "target"])
def test_adaptive_incomplete_does_not_feed_false_failure_or_retry(spec, tmp_path, kind):
    class BrokenJudge(Judge):
        def judge(self, *args, **kwargs):
            if kind == "judge":
                raise ValueError("private-error")
            return JudgeOutput(
                verdict="success", reasoning="Unsupported", evidence_refs_json='["/logs/0"]'
            ), None

    class BrokenTarget(Target):
        calls = 0

        def observe(self, *args, **kwargs):
            self.calls += 1
            if kind == "target":
                raise TimeoutError
            return Observation(response="synthetic", capture_complete=kind != "capture")

    generator, target = AdaptiveGenerator(), BrokenTarget()
    out = tmp_path / "adaptive"
    result = run_assessment(
        spec.model_copy(update={"search_mode": "adaptive"}),
        generator,
        target,
        BrokenJudge() if kind in ("judge", "refs") else Judge(),
        out,
    )
    assert not result["assessment_complete"] and result["stop_reason"] == "inconclusive"
    assert result["records"] == 1 and target.calls == 1 and not generator.feedback
    assert records(out)[0]["judge_verdict"] == "inconclusive"


def test_adaptive_refinement_failure_retains_parent(spec, tmp_path):
    class BrokenGenerator(AdaptiveGenerator):
        def refine(self, *args, **kwargs):
            raise ValueError("private-error")

    out = tmp_path / "adaptive"
    result = run_assessment(
        spec.model_copy(update={"search_mode": "adaptive"}),
        BrokenGenerator(),
        Target(),
        FeedbackJudge(),
        out,
    )
    assert not result["assessment_complete"] and result["error_code"] == "probe-refinement-failed"
    assert records(out)[0]["status"] == "complete"


def test_adaptive_interrupted_child_recovers_lineage_without_execution(spec, tmp_path):
    class InterruptJudge(FeedbackJudge):
        def judge(self, spec, probe, observation, **kwargs):
            if probe.strategy == "refined":
                raise KeyboardInterrupt
            return super().judge(spec, probe, observation, **kwargs)

    out = tmp_path / "adaptive"
    with pytest.raises(KeyboardInterrupt):
        run_assessment(
            spec.model_copy(update={"search_mode": "adaptive"}),
            AdaptiveGenerator(),
            Target(),
            InterruptJudge(),
            out,
        )
    recover_assessment(out)
    rows = records(out)
    assert rows[1]["status"] == "incomplete" and rows[1]["response"]
    assert rows[1]["parent_attempt_id"] == rows[0]["attempt_id"]
    events = [json.loads(line) for line in (out / "events.jsonl").read_text().splitlines()]
    events[-1]["parent_attempt_id"] = "f" * 32
    with (out / "events.jsonl").open("ab") as stream:
        stream.write(json.dumps(events[-1]).encode() + b"\n")
    with pytest.raises(ValueError, match="lineage-invalid|binding-changed"):
        recover_assessment(out)


def test_adaptive_feedback_bounds_redaction_and_generator_mutation(spec, tmp_path):
    class LongTarget(Target):
        def observe(self, *args, **kwargs):
            return Observation(response="FAKE-SECRET" + "x" * 60000)

    class MutatingGenerator(AdaptiveGenerator):
        def refine(self, spec, feedback, **kwargs):
            assert "FAKE-SECRET" not in json.dumps(feedback)
            assert "response" in feedback["truncated_fields"]
            feedback["response"] = "mutated"
            return super().refine(spec, feedback, **kwargs)

    out = tmp_path / "adaptive"
    run_assessment(
        spec.model_copy(update={"search_mode": "adaptive"}),
        MutatingGenerator(),
        LongTarget(),
        FeedbackJudge(),
        out,
        secrets=("FAKE-SECRET",),
    )
    feedback = json.loads(records(out)[1]["feedback_json"])
    assert feedback["response"].startswith("[REDACTED]") and len(feedback["response"]) == 4096


def test_adaptive_requires_refinement_before_output_creation(spec, tmp_path):
    out = tmp_path / "adaptive"
    with pytest.raises(ValueError, match="adaptive-generator-required"):
        run_assessment(
            spec.model_copy(update={"search_mode": "adaptive"}), Generator(), Target(), Judge(), out
        )
    assert not out.exists()


def test_native_designer_adaptive_feedback_requests_and_exports(endpoint, tmp_path):
    from interplay.assessment.designer import DataDesignerBackend
    from interplay.assessment.endpoint import OpenAIEndpointTarget
    from interplay.assessment.models import ModelEndpoint

    base_url, calls = endpoint

    def endpoint_config(model):
        return ModelEndpoint(base_url=base_url, model=model, max_tokens=512)

    backend = DataDesignerBackend(
        endpoint_config("adversarial-model"),
        endpoint_config("judge-model"),
        adversarial_key="not-required",
        judge_key="not-required",
        artifact_path=tmp_path / "designer",
    )
    out = tmp_path / "native-adaptive"
    result = run_assessment(
        AssessmentSpec(
            description="Synthetic assessment",
            success_criteria="Contains SYNTHETIC-CANARY",
            probe_count=2,
            search_mode="adaptive",
            stop_on_success=False,
        ),
        backend,
        OpenAIEndpointTarget(endpoint_config("target-model"), api_key="not-required"),
        backend,
        out,
    )
    assert result["assessment_complete"] and len(calls) == 6
    assert [c["model"] for c in calls] == ["adversarial-model", "target-model", "judge-model"] * 2
    refinement = json.dumps(calls[3]["messages"])
    assert "parent_attempt_id" in refinement and "SYNTHETIC-CANARY" in refinement
    rows = records(out)
    assert rows[1]["generation_trace_json"] and rows[1]["feedback_json"]
    assert pq.read_table(out / "records.parquet").to_pylist() == rows
    assert pa.ipc.open_file(out / "records.arrow").read_all().to_pylist() == rows


def test_adaptive_deadline_stops_before_refinement(spec, tmp_path, monkeypatch):
    import interplay.assessment.runner as runner

    times = iter([0.0, 0.0, 0.0, 0.0, 1000.0])
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(times))
    generator = AdaptiveGenerator()
    result = run_assessment(
        spec.model_copy(update={"search_mode": "adaptive"}),
        generator,
        Target(),
        FeedbackJudge(),
        tmp_path / "deadline",
    )
    assert not result["assessment_complete"] and result["stop_reason"] == "campaign-deadline"
    assert result["records"] == 1 and not generator.feedback


def test_legacy_journal_recovery_accepts_missing_lineage(spec, tmp_path):
    out = tmp_path / "legacy"
    run_assessment(spec, Generator(), Target(), Judge(), out)
    events = [json.loads(line) for line in (out / "events.jsonl").read_text().splitlines()]
    for row in events:
        row["schema_version"] = "interplay-assessment/1"
        for key in ("round_index", "parent_attempt_id", "selection_reason", "feedback_json"):
            row.pop(key)
    (out / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in events))
    before = (out / "events.jsonl").read_bytes()
    recover_assessment(out)
    assert (out / "events.jsonl").read_bytes() == before
    assert records(out)[0]["schema_version"] == "interplay-assessment/1"
