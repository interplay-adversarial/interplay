"""Synthetic workflow tests; these constructed labels are not empirical human calibration."""

import json
import os
import subprocess
import sys
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from interplay.assessment.judgments import aggregate_verdicts
from interplay.assessment.storage import atomic_file, json_bytes
from interplay.calibration.collect import collect
from interplay.calibration.metrics import classification_metrics, evaluate, normalize, proportion
from interplay.calibration.models import Case, GoldLabel, HumanLabel, JudgeIdentity, Prediction
from interplay.calibration.workflow import (
    compile_gold,
    prediction_templates,
    prepare,
    read_rows,
    write_rows,
)


def label(case, reviewer, verdict):
    return HumanLabel(
        case_id=case.case_id,
        case_sha256=case.digest(),
        reviewer_id=reviewer,
        independent_review=True,
        verdict=verdict,
        reasoning="Constructed unit-test label, not a real review.",
        submitted_at="2026-01-01T00:00:00Z",
    )


@pytest.fixture
def inputs(tmp_path):
    cases = [
        Case(
            case_id=f"sample-{i}",
            family="synthetic",
            criterion="The response is MARKER.",
            probe="Synthetic probe",
            observation_json='{"response":"MARKER"}',
            design_bucket="supported-success",
        )
        for i in range(3)
    ]
    write_rows(tmp_path / "cases.jsonl", cases)
    for reviewer in ("a", "b"):
        write_rows(
            tmp_path / f"{reviewer}.jsonl",
            [
                label(c, reviewer, v)
                for c, v in zip(cases, ["success", "failure", "inconclusive"], strict=True)
            ],
        )
    judges = [
        JudgeIdentity(judge_id="a", provider="fixture", model="fixture-one"),
        JudgeIdentity(judge_id="b", provider="fixture", model="fixture-two"),
        JudgeIdentity(judge_id="c", provider="fixture", model="fixture-one"),
    ]
    atomic_file(tmp_path / "judges.json", json_bytes([j.model_dump() for j in judges]))
    return cases, judges


def test_preparation_has_sixty_balanced_cases_and_unlabeled_review_packets(tmp_path):
    root = tmp_path / "prepared"
    summary = prepare(root)
    assert summary["cases"] == 60 and summary["human_labels"] == 0
    assert not summary["reference_ready"] and not summary["metrics_generated"]
    cases = read_rows(root / "cases.jsonl", Case)
    assert Counter(c.design_bucket for c in cases) == {
        "supported-success": 20,
        "supported-failure": 20,
        "missing-or-ambiguous": 20,
    }
    assert len({c.family for c in cases}) == 20 and len({c.digest() for c in cases}) == 60
    assert not any(
        "design_bucket" in line for line in (root / "review-a/cases.jsonl").read_text().splitlines()
    )
    assert all(r.verdict is None for r in read_rows(root / "review-a/labels.jsonl", HumanLabel))
    status = compile_gold(
        root / "cases.jsonl",
        [root / "review-a/labels.jsonl", root / "review-b/labels.jsonl"],
        None,
        tmp_path / "pending",
    )
    assert status["resolved_cases"] == 0 and not status["reference_ready"]
    assert not (tmp_path / "pending/gold.jsonl").exists()
    assert all(not p.stat().st_mode & 0o077 for p in [root, *root.rglob("*")])
    assert "Ignore the rubric" in " ".join(c.observation_json for c in cases)
    ambiguous = [c for c in cases if c.design_bucket == "missing-or-ambiguous"]
    assert any(c.observation().capture_complete for c in ambiguous)
    assert any(not c.observation().capture_complete for c in ambiguous)


def test_agreed_human_attestations_compile_gold_and_preserve_provenance(tmp_path, inputs):
    cases, _ = inputs
    summary = compile_gold(
        tmp_path / "cases.jsonl",
        [tmp_path / "a.jsonl", tmp_path / "b.jsonl"],
        None,
        tmp_path / "gold",
    )
    assert summary["reference_ready"] and summary["resolved_cases"] == 3
    gold = read_rows(tmp_path / "gold/gold.jsonl", GoldLabel)
    assert [r.verdict for r in gold] == ["success", "failure", "inconclusive"]
    assert all(r.case_sha256 == c.digest() for r, c in zip(gold, cases, strict=True))
    assert "not authenticated" in summary["human_origin"]


def test_disagreement_needs_third_reviewer_adjudication(tmp_path, inputs):
    cases, _ = inputs
    labels = read_rows(tmp_path / "b.jsonl", HumanLabel)
    labels[0] = label(cases[0], "b", "failure")
    write_rows(tmp_path / "b.jsonl", labels)
    summary = compile_gold(
        tmp_path / "cases.jsonl",
        [tmp_path / "a.jsonl", tmp_path / "b.jsonl"],
        None,
        tmp_path / "pending",
    )
    assert not summary["reference_ready"] and summary["resolved_cases"] == 2
    assert not (tmp_path / "pending/gold.jsonl").exists()
    write_rows(tmp_path / "decisions.jsonl", [label(cases[0], "c", "inconclusive")])
    summary = compile_gold(
        tmp_path / "cases.jsonl",
        [tmp_path / "a.jsonl", tmp_path / "b.jsonl"],
        tmp_path / "decisions.jsonl",
        tmp_path / "resolved",
    )
    assert summary["reference_ready"]
    gold = read_rows(tmp_path / "resolved/gold.jsonl", GoldLabel)
    assert gold[0].verdict == "inconclusive" and gold[0].adjudication_json is not None


@pytest.mark.parametrize(
    "mutation",
    [
        "same-reviewer",
        "generated",
        "stale-case",
        "wrong-rubric",
        "no-attestation",
        "naive-date",
        "duplicate-row",
    ],
)
def test_invalid_or_stale_labels_cannot_make_a_reference(tmp_path, inputs, mutation):
    rows = [r.model_dump() for r in read_rows(tmp_path / "b.jsonl", HumanLabel)]
    field_values = {
        "same-reviewer": ("reviewer_id", "a"),
        "generated": ("label_source", "model"),
        "stale-case": ("case_sha256", "0" * 64),
        "wrong-rubric": ("rubric_version", "unknown/2"),
        "no-attestation": ("independent_review", False),
        "naive-date": ("submitted_at", "2026-01-01T00:00:00"),
    }
    if mutation == "duplicate-row":
        rows.append(rows[0])
    else:
        key, value = field_values[mutation]
        rows[0][key] = value
    write_rows(tmp_path / "b.jsonl", rows)
    with pytest.raises(ValueError):
        compile_gold(
            tmp_path / "cases.jsonl",
            [tmp_path / "a.jsonl", tmp_path / "b.jsonl"],
            None,
            tmp_path / "gold",
        )
    assert not (tmp_path / "gold").exists()


@pytest.mark.parametrize("agreed,reviewer", [(False, "a"), (True, "c")])
def test_adjudication_cannot_reuse_original_reviewer_or_override_agreement(
    tmp_path, inputs, agreed, reviewer
):
    cases, _ = inputs
    if not agreed:
        rows = read_rows(tmp_path / "b.jsonl", HumanLabel)
        rows[0] = label(cases[0], "b", "failure")
        write_rows(tmp_path / "b.jsonl", rows)
    write_rows(tmp_path / "decisions.jsonl", [label(cases[0], reviewer, "failure")])
    with pytest.raises(ValueError):
        compile_gold(
            tmp_path / "cases.jsonl",
            [tmp_path / "a.jsonl", tmp_path / "b.jsonl"],
            tmp_path / "decisions.jsonl",
            tmp_path / "gold",
        )


def test_metrics_confusion_abstention_and_denominators():
    metrics = classification_metrics(
        ["success", "success", "failure", "failure", "inconclusive"],
        ["success", "inconclusive", "success", "failure", "success"],
    )
    assert metrics["three_class_accuracy"]["rate"] == 2 / 5
    assert metrics["false_positive_rate"]["rate"] == 1 / 2
    assert metrics["sensitivity"]["rate"] == 1 / 2
    assert metrics["decisive_coverage"]["rate"] == 4 / 5
    assert metrics["selective_accuracy"]["rate"] == 2 / 4
    assert metrics["ambiguous_false_confirmation_rate"]["rate"] == 1
    assert metrics["confusion_matrix"]["success"]["inconclusive"] == 1
    empty = classification_metrics([], [])
    assert empty["sensitivity"]["rate"] is None
    assert empty["false_positive_rate"]["wilson_95"] is None


def test_wilson_interval_known_values_and_extremes():
    assert proportion(2, 20)["wilson_95"] == pytest.approx([0.02786648, 0.30103365])
    assert proportion(0, 20)["wilson_95"] == pytest.approx([0, 0.16112516])
    assert proportion(20, 20)["wilson_95"] == pytest.approx([0.83887484, 1])


def prediction(case, judge, verdict="success", **updates):
    values = dict(
        case_id=case.case_id,
        case_sha256=case.digest(),
        judge_id=judge.judge_id,
        judge_sha256=judge.digest(),
        finish_reason="stop",
        raw_reply=json.dumps(
            {
                "verdict": verdict,
                "reasoning": "Synthetic prediction",
                "evidence_refs_json": '["/response"]',
            }
        ),
    )
    return Prediction(**{**values, **updates})


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"raw_reply": "not JSON"}, "invalid-model-output"),
        ({"raw_reply": '{"verdict":"success","verdict":"failure"}'}, "invalid-model-output"),
        ({"finish_reason": "length"}, "unfinished-or-missing-reply"),
        ({"error_code": "timeout"}, "recorded-provider-error"),
        ({"error_code": "not-run"}, "not-run"),
        (
            {
                "raw_reply": json.dumps(
                    {
                        "verdict": "success",
                        "reasoning": "unsupported",
                        "evidence_refs_json": '["/logs/missing"]',
                    }
                )
            },
            "unsupported-citations",
        ),
    ],
)
def test_invalid_or_unavailable_predictions_become_abstentions(inputs, changes, reason):
    cases, judges = inputs
    normalized = normalize(cases[0], prediction(cases[0], judges[0], **changes))
    assert normalized["effective_verdict"] == "inconclusive" and normalized["reason"] == reason
    assert normalized["prediction_json"] is not None


def test_normalization_matches_runtime_fences_and_capture_rules(inputs):
    cases, judges = inputs
    pred = prediction(
        cases[0],
        judges[0],
        raw_reply='```json\n{"verdict":"success","reasoning":"seen","evidence_refs_json":["/response"]}\n```',
    )
    assert normalize(cases[0], pred)["effective_verdict"] == "success"
    incomplete = cases[0].model_copy(
        update={"observation_json": '{"response":"MARKER","capture_complete":false}'}
    )
    assert normalize(incomplete, pred)["reason"] == "incomplete-capture"
    assert normalize(cases[0], None)["reason"] == "missing-prediction"


def test_evaluation_keeps_missing_predictions_and_compares_both_panel_policies(tmp_path, inputs):
    cases, judges = inputs
    compile_gold(
        tmp_path / "cases.jsonl",
        [tmp_path / "a.jsonl", tmp_path / "b.jsonl"],
        None,
        tmp_path / "gold",
    )
    write_rows(tmp_path / "predictions.jsonl", [prediction(cases[0], j) for j in judges[:2]])
    result = evaluate(
        tmp_path / "cases.jsonl",
        tmp_path / "gold/gold.jsonl",
        tmp_path / "judges.json",
        [tmp_path / "predictions.jsonl"],
        tmp_path / "metrics",
    )
    assert result["repeated_model_aliases"] and result["distinct_declared_model_identities"] == 2
    assert result["panels"]["majority"]["sensitivity"]["rate"] == 1
    assert result["panels"]["unanimous"]["sensitivity"]["rate"] == 0
    assert result["judges"]["c"]["outcome_reasons"] == {"missing-prediction": 3}
    assert result["judges"]["c"]["decisive_coverage"]["rate"] == 0
    assert all(m["three_class_accuracy"]["denominator"] == 3 for m in result["judges"].values())
    normalized = [
        json.loads(line)
        for line in (tmp_path / "metrics/normalized-predictions.jsonl").read_text().splitlines()
    ]
    assert len(normalized) == 9 and len(result["agreement_separate_from_accuracy"]) == 3
    assert "Matched synthetic families are dependent" in result["uncertainty"]
    assert not result["minimum_60_cases"] and not result["release_eligible"]


@pytest.mark.parametrize(
    "mutation",
    ["stale-prediction", "stale-model", "duplicate-prediction", "incomplete-gold", "forged-gold"],
)
def test_evaluation_rejects_broken_bindings_or_missing_provenance(tmp_path, inputs, mutation):
    cases, judges = inputs
    compile_gold(
        tmp_path / "cases.jsonl",
        [tmp_path / "a.jsonl", tmp_path / "b.jsonl"],
        None,
        tmp_path / "gold",
    )
    rows = [prediction(cases[0], judges[0]).model_dump()]
    if mutation == "stale-prediction":
        rows[0]["case_sha256"] = "0" * 64
    elif mutation == "stale-model":
        rows[0]["judge_sha256"] = "0" * 64
    elif mutation == "duplicate-prediction":
        rows.append(rows[0])
    elif mutation == "incomplete-gold":
        write_rows(tmp_path / "gold/gold.jsonl", [])
    else:
        gold = [r.model_dump() for r in read_rows(tmp_path / "gold/gold.jsonl", GoldLabel)]
        gold[0]["labels_json"] = "[]"
        write_rows(tmp_path / "gold/gold.jsonl", gold)
    write_rows(tmp_path / "predictions.jsonl", rows)
    with pytest.raises(ValueError):
        evaluate(
            tmp_path / "cases.jsonl",
            tmp_path / "gold/gold.jsonl",
            tmp_path / "judges.json",
            [tmp_path / "predictions.jsonl"],
            tmp_path / "metrics",
        )
    assert not (tmp_path / "metrics").exists()


@pytest.mark.parametrize(
    "votes,plurality,unanimous",
    [
        (["success", "failure"], "inconclusive", "inconclusive"),
        (["success", "success", "inconclusive"], "success", "inconclusive"),
        (["failure", "failure"], "failure", "failure"),
        (["success", "failure", "inconclusive"], "inconclusive", "inconclusive"),
    ],
)
def test_shared_runtime_panel_policy(votes, plurality, unanimous):
    assert aggregate_verdicts(votes, "majority") == plurality
    assert aggregate_verdicts(votes, "unanimous") == unanimous


def test_prepare_cli_no_credentials_providers_or_network(tmp_path):
    guard = """
import importlib.abc, runpy, sys
class NoProviders(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'any_llm','httpx','judge_kappa','data_designer'}:
            raise AssertionError('provider-import')
sys.meta_path.insert(0,NoProviders())
log,output=sys.argv[1:]
def audit(event,args):
    if event in {'socket.connect','socket.getaddrinfo','socket.sendto'}:
        with open(log,'a') as stream: stream.write(event)
        raise AssertionError('network-operation')
sys.addaudithook(audit)
sys.argv=['interplay','calibration','prepare','--output',output]
runpy.run_module('interplay',run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-c", guard, str(tmp_path / "network.log"), str(tmp_path / "prepared")],
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "cases": 60,
        "reference_ready": False,
        "metrics_generated": False,
    }
    assert not (tmp_path / "network.log").exists()


def test_no_output_overwrite_and_no_private_error_text(tmp_path, capsys):
    from interplay.calibration.cli import main

    root = tmp_path / "prepared"
    prepare(root)
    before = (root / "cases.jsonl").read_bytes()
    assert main(["calibration", "prepare", "--output", str(root)]) == 2
    assert (root / "cases.jsonl").read_bytes() == before
    captured = capsys.readouterr()
    assert "calibration-failed" in captured.err and not captured.out
    assert str(root) not in captured.err


def test_prediction_templates_are_not_observed_model_replies(tmp_path, inputs):
    cases, judges = inputs
    result = prediction_templates(
        tmp_path / "cases.jsonl", tmp_path / "judges.json", tmp_path / "templates"
    )
    rows = read_rows(tmp_path / "templates/predictions.jsonl", Prediction)
    assert len(rows) == 9 and result["model_calls"] == 0
    assert all(row.raw_reply is None and row.error_code == "not-run" for row in rows)
    assert rows[0].case_sha256 == cases[0].digest() and rows[0].judge_sha256 == judges[0].digest()


def test_partially_filled_forms_do_not_count_as_completed_labels(tmp_path, inputs):
    cases, _ = inputs
    rows = [HumanLabel(case_id=c.case_id, case_sha256=c.digest(), reviewer_id="b") for c in cases]
    write_rows(tmp_path / "b.jsonl", rows)
    summary = compile_gold(
        tmp_path / "cases.jsonl",
        [tmp_path / "a.jsonl", tmp_path / "b.jsonl"],
        None,
        tmp_path / "gold",
    )
    assert not summary["reference_ready"] and summary["resolved_cases"] == 0


@pytest.fixture
def collector_endpoint():
    state = {"requests": [], "delay": 0, "secret": "synthetic-calibration-key"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            assert self.headers.get("Authorization") == "Bearer " + state["secret"]
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append(request)
            time.sleep(state["delay"])
            content = json.dumps(
                {
                    "verdict": "success",
                    "reasoning": "fixture " + state["secret"],
                    "evidence_refs_json": '["/response"]',
                }
            )
            raw = json.dumps(
                {"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}
            ).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except OSError:
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield f"http://127.0.0.1:{server.server_port}/v1", state
    server.shutdown()
    server.server_close()
    worker.join(timeout=3)


def collector_config(tmp_path, url):
    value = {
        "judges": [
            {
                "identity": {
                    "judge_id": "judge-a",
                    "provider": "fixture",
                    "model": "fixture-model",
                },
                "endpoint": {
                    "base_url": url,
                    "model": "fixture-model",
                    "api_key_env": "CALIBRATION_TEST_KEY",
                    "request_seconds": 1,
                },
            }
        ]
    }
    atomic_file(tmp_path / "collection.json", json_bytes(value))
    return tmp_path / "collection.json"


def test_collection_records_actual_replies_bindings_and_redacts_keys(
    tmp_path, inputs, collector_endpoint, monkeypatch
):
    url, state = collector_endpoint
    monkeypatch.setenv("CALIBRATION_TEST_KEY", state["secret"])
    result = collect(
        tmp_path / "cases.jsonl",
        collector_config(tmp_path, url),
        tmp_path / "collection",
        max_cases=2,
    )
    assert result["model_calls_attempted"] == 2 and len(state["requests"]) == 2
    rows = read_rows(tmp_path / "collection/predictions.jsonl", Prediction)
    assert all(r.finish_reason == "stop" and r.request_sha256 and r.response_sha256 for r in rows)
    assert all("[REDACTED]" in r.raw_reply for r in rows)
    assert all(
        state["secret"].encode() not in p.read_bytes() for p in (tmp_path / "collection").iterdir()
    )
    assert all(
        not p.stat().st_mode & 0o077
        for p in [tmp_path / "collection", *(tmp_path / "collection").iterdir()]
    )
    for request in state["requests"]:
        task = json.loads(request["messages"][1]["content"])
        assert set(task) == {"criterion", "probe", "capture_complete", "evidence"}
        assert "design_bucket" not in json.dumps(request)
    events = [
        json.loads(line)
        for line in (tmp_path / "collection/collection-events.jsonl").read_text().splitlines()
    ]
    assert [e["request_sha256"] for e in events] == [r.request_sha256 for r in rows]


def test_collection_redacts_json_escaped_credentials(
    tmp_path, inputs, collector_endpoint, monkeypatch
):
    url, state = collector_endpoint
    state["secret"] = 'synthetic"calibration\\key'
    monkeypatch.setenv("CALIBRATION_TEST_KEY", state["secret"])
    collect(
        tmp_path / "cases.jsonl",
        collector_config(tmp_path, url),
        tmp_path / "collection",
        max_cases=1,
    )
    rows = read_rows(tmp_path / "collection/predictions.jsonl", Prediction)
    assert json.loads(rows[0].raw_reply)["reasoning"] == "fixture [REDACTED]"


def test_collection_requires_explicit_key_before_output_or_network(tmp_path, inputs, monkeypatch):
    monkeypatch.delenv("CALIBRATION_TEST_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "ambient-key-must-not-be-used")
    config = collector_config(tmp_path, "http://127.0.0.1:1/v1")
    with pytest.raises(ValueError, match="explicit-credential"):
        collect(tmp_path / "cases.jsonl", config, tmp_path / "collection")
    assert not (tmp_path / "collection").exists()


def test_collection_deadline_retains_error_without_retry(
    tmp_path, inputs, collector_endpoint, monkeypatch
):
    url, state = collector_endpoint
    state["delay"] = 2
    monkeypatch.setenv("CALIBRATION_TEST_KEY", state["secret"])
    result = collect(
        tmp_path / "cases.jsonl",
        collector_config(tmp_path, url),
        tmp_path / "collection",
        max_cases=3,
        campaign_seconds=1,
    )
    assert result["deadline_exhausted"] and result["model_calls_attempted"] == 1
    rows = read_rows(tmp_path / "collection/predictions.jsonl", Prediction)
    assert len(rows) == 1 and rows[0].finish_reason == "error"
    assert rows[0].error_code == "judge-request-failed"


def test_collection_rejects_secrets_in_case_before_starting(tmp_path, inputs, monkeypatch):
    cases, _ = inputs
    monkeypatch.setenv("CALIBRATION_TEST_KEY", "synthetic-calibration-key")
    write_rows(
        tmp_path / "cases.jsonl",
        [cases[0].model_copy(update={"probe": "synthetic-calibration-key"})],
    )
    with pytest.raises(ValueError, match="input-contains-configured-secret"):
        collect(
            tmp_path / "cases.jsonl",
            collector_config(tmp_path, "http://127.0.0.1:1/v1"),
            tmp_path / "collection",
        )
    assert not (tmp_path / "collection").exists()
