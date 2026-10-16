"""Constructed paired regressions; fixture judgments are not measured accuracy."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from interplay.assessment.storage import atomic_file, json_bytes
from interplay.benchmark.core import compare, import_records, inputs, prepare, read_records, recover
from interplay.benchmark.models import BenchmarkCase, BenchmarkRecord, Manifest
from interplay.benchmark.run import run
from interplay.calibration.workflow import write_rows
from interplay.runner_records import RunnerRecord


@pytest.fixture
def endpoint():
    state = {"requests": [], "usage": True, "finish": "stop", "bad_judge": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            assert self.headers["Authorization"] == "Bearer fixture-benchmark-key"
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append(body)
            if body["model"] == "judge":
                evidence = json.loads(body["messages"][-1]["content"])["evidence"]
                content = json.dumps(
                    {
                        "verdict": "success" if evidence["response"] == "MARKER" else "failure",
                        "reasoning": "Constructed fixture",
                        "evidence_refs_json": '["/response"]',
                    }
                )
                if state["bad_judge"]:
                    content = content.replace("/response", "/logs")
            else:
                content = "MARKER" if body["model"] == "baseline" else "OTHER"
            response = {
                "choices": [{"message": {"content": content}, "finish_reason": state["finish"]}]
            }
            if state["usage"]:
                response["usage"] = {
                    "prompt_tokens": 5,
                    "completion_tokens": 2,
                    "total_tokens": 7,
                    "cost_usd": 0.01,
                }
            raw = json_bytes(response)
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", state
    server.shutdown()
    server.server_close()
    worker.join(timeout=3)


@pytest.fixture
def prepared(tmp_path, endpoint, monkeypatch):
    url, state = endpoint
    monkeypatch.setenv("BENCHMARK_TEST_KEY", "fixture-benchmark-key")
    cases = [
        BenchmarkCase(case_id=f"case-{i}", goal="Response is MARKER", prompt=f"Print MARKER ({i})")
        for i in range(2)
    ]
    write_rows(tmp_path / "cases.jsonl", cases)
    for name in ("baseline", "candidate", "judge"):
        atomic_file(
            tmp_path / f"{name}.json",
            json_bytes(
                {
                    "endpoint": {
                        "base_url": url,
                        "model": name,
                        "api_key_env": "BENCHMARK_TEST_KEY",
                        "max_tokens": 128,
                        "request_seconds": 1,
                    },
                    "extra_body_json": "{}",
                }
            ),
        )
    prepare(
        tmp_path / "cases.jsonl",
        tmp_path / "baseline.json",
        tmp_path / "candidate.json",
        tmp_path / "judge.json",
        tmp_path / "prepared",
        suite_id="fixture",
        source_revision="a" * 40,
    )
    return tmp_path / "prepared/manifest.json", tmp_path / "cases.jsonl", state


def executed(prepared, tmp_path):
    manifest, cases, _ = prepared
    result = run(manifest, cases, tmp_path / "run")
    assert result["client_calls_attempted"] == 8
    return read_records(tmp_path / "run/records.jsonl")


def test_equal_paired_execution_observed_resources_and_order(prepared, tmp_path):
    manifest, cases, state = prepared
    rows = executed(prepared, tmp_path)
    summary = compare(manifest, cases, [tmp_path / "run/records.jsonl"], tmp_path / "comparison")
    assert [r["model"] for r in state["requests"]] == [
        "baseline",
        "judge",
        "candidate",
        "judge",
        "candidate",
        "judge",
        "baseline",
        "judge",
    ]
    assert all(r.terminal and r.status == "complete" and r.capture_complete for r in rows)
    assert all(r.target_latency_seconds > 0 and r.judge_latency_seconds > 0 for r in rows)
    assert summary["accuracy"] is None and not summary["release_eligible"]
    for variant, verdict in (("baseline", "success"), ("candidate", "failure")):
        values = summary["variants"][variant]
        assert values["citation_resolved_model_judgments"][verdict] == 2
        assert values["target_calls"] == values["judge_calls"] == 2
        assert values["tokens"]["total_tokens"] == 28
        assert values["cost_usd"] == pytest.approx(0.04)
    pairs = [
        json.loads(line)
        for line in (tmp_path / "comparison/paired-cases.jsonl").read_text().splitlines()
    ]
    assert len(pairs) == 2 and all(
        p["response_changed"] and p["recorded_verdict_changed"] for p in pairs
    )
    assert all(p["total_tokens_delta"] == 0 and p["target_calls_delta"] == 0 for p in pairs)
    assert all(not p.stat().st_mode & 0o077 for p in (tmp_path / "run").iterdir())


def test_unobserved_usage_and_missing_rows_are_unavailable(prepared, tmp_path):
    manifest, cases, state = prepared
    state["usage"] = False
    rows = executed(prepared, tmp_path)
    write_rows(tmp_path / "partial.jsonl", [r for r in rows if r.variant == "baseline"])
    summary = compare(manifest, cases, [tmp_path / "partial.jsonl"], tmp_path / "comparison")
    assert summary["variants"]["baseline"]["tokens"]["total_tokens"] is None
    assert summary["variants"]["baseline"]["cost_usd"] is None
    missing = summary["variants"]["candidate"]
    assert missing["missing_records"] == 2 and missing["target_calls"] is None
    assert missing["citation_resolved_model_judgments"]["inconclusive"] == 2


@pytest.mark.parametrize("field", ["manifest_sha256", "case_sha256", "profile_sha256", "duplicate"])
def test_rejects_changed_bindings_and_duplicates(prepared, tmp_path, field):
    manifest, cases, _ = prepared
    rows = executed(prepared, tmp_path)
    if field == "duplicate":
        rows.append(rows[0])
    else:
        rows[0] = rows[0].model_copy(update={field: "b" * 64})
    write_rows(tmp_path / "changed.jsonl", rows)
    with pytest.raises(ValueError, match="binding"):
        compare(manifest, cases, [tmp_path / "changed.jsonl"], tmp_path / "comparison")


@pytest.mark.parametrize("change", ["case", "source", "credential", "secret"])
def test_preflight_rejects_changed_source_inputs_and_missing_credentials(
    prepared, tmp_path, monkeypatch, change
):
    manifest, cases, state = prepared
    if change == "case":
        cases.write_bytes(cases.read_bytes() + b"\n")
    elif change == "source":
        value = json.loads(manifest.read_text())
        value["implementation_sha256"] = "b" * 64
        atomic_file(manifest, json_bytes(value))
    elif change == "credential":
        monkeypatch.delenv("BENCHMARK_TEST_KEY")
        monkeypatch.setenv("OPENAI_API_KEY", "fixture-benchmark-key")
    else:
        monkeypatch.setenv("BENCHMARK_TEST_KEY", "MARKER")
    with pytest.raises(ValueError):
        run(manifest, cases, tmp_path / "run")
    assert not state["requests"] and not (tmp_path / "run").exists()


@pytest.mark.parametrize("field", ["max_tokens", "request_seconds", "reserved"])
def test_equal_budget_and_reserved_override_validation(prepared, field):
    manifest, _, _ = prepared
    data = json.loads(manifest.read_text())
    candidate = json.loads(data["candidate_json"])
    if field == "reserved":
        candidate["extra_body_json"] = '{"n":2}'
    else:
        candidate["endpoint"][field] += 1
    data["candidate_json"] = json.dumps(candidate)
    with pytest.raises(ValueError):
        Manifest.model_validate(data)


@pytest.mark.parametrize("value", [-1, True, 1.5, 10**500])
def test_invalid_token_measurements(prepared, tmp_path, value):
    row = executed(prepared, tmp_path)[0].model_dump()
    row["usage_json"] = json.dumps({"target": {"total_tokens": value}})
    with pytest.raises(ValueError):
        BenchmarkRecord.model_validate(row)


@pytest.mark.parametrize("mode", ["length", "bad-judge"])
def test_partial_and_uncited_outputs_stay_inconclusive(prepared, tmp_path, mode):
    _, _, state = prepared
    state["finish"] = "length" if mode == "length" else "stop"
    state["bad_judge"] = mode == "bad-judge"
    manifest, cases, _ = prepared
    result = run(manifest, cases, tmp_path / "run")
    rows = read_records(tmp_path / "run/records.jsonl")
    assert result["client_calls_attempted"] == (4 if mode == "length" else 8)
    assert all(r.status == "incomplete" and r.judge_verdict == "inconclusive" for r in rows)
    assert all(r.response is not None for r in rows)


def test_recovery_preserves_terminal_and_partial_observations_offline(prepared, tmp_path):
    manifest, cases, state = prepared
    executed(prepared, tmp_path)
    events = (tmp_path / "run/events.jsonl").read_bytes().splitlines(keepends=True)
    # First variant terminal; second variant response committed before judge dispatch.
    prefix = b"".join(events[:6]) + b'{"torn":'
    atomic_file(tmp_path / "interrupted.jsonl", prefix)
    before = len(state["requests"])
    result = recover(manifest, cases, tmp_path / "interrupted.jsonl", tmp_path / "recovered")
    rows = read_records(tmp_path / "recovered/records.jsonl")
    assert result["model_calls"] == 0 and result["journal_truncated"]
    assert rows[0].model_dump() == json.loads(events[3])
    assert rows[1].response == "OTHER" and rows[1].capture_complete
    assert (
        rows[1].terminal and rows[1].status == "incomplete" and rows[1].error_code == "interrupted"
    )
    assert (tmp_path / "interrupted.jsonl").read_bytes() == prefix
    recover(manifest, cases, tmp_path / "interrupted.jsonl", tmp_path / "again")
    assert (tmp_path / "again/records.jsonl").read_bytes() == (
        tmp_path / "recovered/records.jsonl"
    ).read_bytes()
    assert len(state["requests"]) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("response", "rewritten"),
        ("capture_complete", False),
        ("target_latency_seconds", 999),
        ("source_json", "{}"),
        ("usage_json", "{}"),
    ],
)
def test_recovery_rejects_rewritten_observation(prepared, tmp_path, field, value):
    manifest, cases, _ = prepared
    executed(prepared, tmp_path)
    events = [json.loads(line) for line in (tmp_path / "run/events.jsonl").read_text().splitlines()]
    events = events[:2] + [{**events[1], field: value}]
    write_rows(tmp_path / "changed.jsonl", events)
    with pytest.raises(ValueError, match="stage-changed"):
        recover(manifest, cases, tmp_path / "changed.jsonl", tmp_path / "recovered")


def test_exact_import_mapping_preserves_unknown_calls_and_resources(prepared, tmp_path):
    manifest, cases, state = prepared
    _, planned = inputs(manifest, cases)
    native = RunnerRecord(
        run_id="a" * 32,
        attempt_id="b" * 32,
        ordinal=0,
        method="fixture",
        strategy="fixed",
        goal=planned[0].goal,
        probe=planned[0].prompt,
        response="MARKER",
        capture_complete=True,
        judge_verdict="success",
        judge_reasoning="fixture",
        evidence_refs_json='["/response"]',
        role_provenance_json="{}",
        status="complete",
        created_at="2026-01-01T00:00:00Z",
    )
    write_rows(tmp_path / "native.jsonl", [native])
    atomic_file(
        tmp_path / "mapping.json",
        json_bytes(
            [{"case_id": planned[0].case_id, "repeat_index": 0, "attempt_id": native.attempt_id}]
        ),
    )
    result = import_records(
        manifest,
        cases,
        "baseline",
        tmp_path / "native.jsonl",
        tmp_path / "mapping.json",
        tmp_path / "imported",
    )
    row = read_records(tmp_path / "imported/records.jsonl")[0]
    assert result["model_calls"] == 0 and not state["requests"]
    assert (
        row.terminal
        and row.judge_verdict == "success"
        and row.target_calls is None
        and row.usage_json == "{}"
    )
    native = native.model_copy(update={"probe": "different"})
    write_rows(tmp_path / "native.jsonl", [native])
    with pytest.raises(ValueError, match="fixed-input-mismatch"):
        import_records(
            manifest,
            cases,
            "candidate",
            tmp_path / "native.jsonl",
            tmp_path / "mapping.json",
            tmp_path / "bad",
        )


def test_offline_cli_has_no_provider_imports_or_network(prepared, tmp_path):
    import os
    import subprocess
    import sys

    manifest, cases, _ = prepared
    executed(prepared, tmp_path)
    bootstrap = r"""
import importlib.abc, sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'httpx','any_llm','judge_kappa','data_designer'}:
            raise RuntimeError('provider-import-attempt')
sys.meta_path.insert(0, Guard())
def audit(event, args):
    if event in ('socket.connect','socket.getaddrinfo','socket.sendto'):
        raise RuntimeError('network-attempt')
sys.addaudithook(audit)
from interplay.cli import main
sys.argv = ['interplay', 'benchmark', *sys.argv[1:]]
raise SystemExit(main())
"""
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(__import__("pathlib").Path(__file__).resolve().parents[1]),
    }
    actions = [
        [
            "prepare",
            "--baseline",
            str(tmp_path / "baseline.json"),
            "--candidate",
            str(tmp_path / "candidate.json"),
            "--suite-id",
            "offline",
            "--source-revision",
            "a" * 40,
        ],
        ["compare", "--manifest", str(manifest), "--records", str(tmp_path / "run/records.jsonl")],
        ["recover", "--manifest", str(manifest), "--journal", str(tmp_path / "run/events.jsonl")],
    ]
    for action in actions:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                bootstrap,
                *action,
                "--cases",
                str(cases),
                "--output",
                str(tmp_path / ("offline-" + action[0])),
            ],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr.decode()
