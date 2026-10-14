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
