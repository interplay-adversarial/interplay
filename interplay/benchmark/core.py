"""Manifest validation, exact fixed-case imports and paired descriptive comparison."""

import hashlib
import importlib
import math
from collections import Counter
from pathlib import Path

from ..assessment.judgments import parse_judge_output
from ..assessment.models import JudgeOutput, Observation
from ..assessment.runner import evidence_supported
from ..assessment.storage import atomic_file, json_bytes, private_file
from ..calibration.workflow import write_rows
from ..report import _json, load_export
from .models import BenchmarkCase, BenchmarkRecord, Manifest, digest


def read_records(path):
    lines = private_file(Path(path)).splitlines()
    if len(lines) > 20000 or any(len(line) > 512 * 1024 for line in lines):
        raise ValueError("benchmark-record-limit")
    return [BenchmarkRecord.model_validate(_json(line)) for line in lines]


def implementation_digest():
    names = (
        "interplay.benchmark.models",
        "interplay.benchmark.core",
        "interplay.benchmark.run",
        "interplay.benchmark.cli",
        "interplay.assessment.http",
        "interplay.assessment.judgments",
        "interplay.assessment.models",
        "interplay.assessment.runner",
        "interplay.assessment.storage",
        "interplay.report",
        "interplay.runner_records",
        "interplay.calibration.models",
        "interplay.calibration.workflow",
        "interplay.calibration.collect",
    )
    return digest(
        {
            name: hashlib.sha256(
                Path(importlib.import_module(name).__file__).read_bytes()
            ).hexdigest()
            for name in names
        }
    )


def inputs(manifest_path, cases_path, *, executing=False):
    manifest = Manifest.model_validate(_json(private_file(Path(manifest_path), limit=128 * 1024)))
    raw = private_file(Path(cases_path), limit=16 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != manifest.cases_sha256:
        raise ValueError("benchmark-input-digest-changed")
    cases = [BenchmarkCase.model_validate(_json(line)) for line in raw.splitlines()]
    if not 1 <= len(cases) <= 1000 or len({c.case_id for c in cases}) != len(cases):
        raise ValueError("benchmark-case-identities-invalid")
    if executing and manifest.implementation_sha256 != implementation_digest():
        raise ValueError("benchmark-executing-source-changed")
    return manifest, cases[: manifest.max_cases]


def prepare(
    cases_path,
    baseline_path,
    candidate_path,
    judge_path,
    output,
    *,
    suite_id,
    source_revision,
    repeats=1,
    max_cases=5,
    campaign_seconds=600,
):
    baseline = private_file(Path(baseline_path), limit=32768).decode()
    candidate = private_file(Path(candidate_path), limit=32768).decode()
    judge = private_file(Path(judge_path), limit=32768).decode() if judge_path else None
    manifest = Manifest(
        suite_id=suite_id,
        source_revision=source_revision,
        cases_sha256=hashlib.sha256(
            private_file(Path(cases_path), limit=16 * 1024 * 1024)
        ).hexdigest(),
        implementation_sha256=implementation_digest(),
        baseline_json=baseline,
        candidate_json=candidate,
        judge_json=judge,
        repeats=repeats,
        max_cases=max_cases,
        campaign_seconds_per_variant=campaign_seconds,
    )
    output = Path(output)
    # Validate task content before creating any artifact.
    cases = [
        BenchmarkCase.model_validate(_json(line))
        for line in private_file(Path(cases_path)).splitlines()
    ]
    if not cases or len(cases) > 1000 or len({c.case_id for c in cases}) != len(cases):
        raise ValueError("benchmark-case-identities-invalid")
    output.mkdir(mode=0o700, exist_ok=False)
    atomic_file(output / "manifest.json", json_bytes(manifest.model_dump()))
    return {"cases": min(len(cases), max_cases), "repeats": repeats, "model_calls": 0}


def checked_judgment(response, complete, raw):
    if not complete or raw is None:
        return None
    try:
        judgment = parse_judge_output(raw)
        if evidence_supported(judgment, Observation(response=response, capture_complete=complete)):
            return judgment
    except (ValueError, TypeError, RecursionError):
        pass
    return None


def import_records(manifest_path, cases_path, variant, source, mapping_path, output):
    manifest, cases = inputs(manifest_path, cases_path)
    if variant not in ("baseline", "candidate"):
        raise ValueError("benchmark-variant-invalid")
    exported, source_info = load_export(Path(source))
    by_attempt = {r.attempt_id: r for r in exported}
    raw_mapping = _json(private_file(Path(mapping_path), limit=65536))
    if not isinstance(raw_mapping, list):
        raise ValueError("benchmark-mapping-invalid")
    planned = {(c.case_id, repeat): c for c in cases for repeat in range(manifest.repeats)}
    rows, seen, attempts = [], set(), set()
    for item in raw_mapping:
        if (
            not isinstance(item, dict)
            or set(item) != {"case_id", "repeat_index", "attempt_id"}
            or type(item["repeat_index"]) is not int
        ):
            raise ValueError("benchmark-mapping-invalid")
        pair = (item["case_id"], item["repeat_index"])
        record = by_attempt.get(item["attempt_id"])
        case = planned.get(pair)
        if case is None or record is None or pair in seen or record.attempt_id in attempts:
            raise ValueError("benchmark-import-binding-invalid")
        goal = getattr(record, "goal", getattr(record, "success_criteria", None))
        history = (
            _json(record.conversation_trace_json)
            if record.conversation_trace_json
            else [{"role": "user", "content": record.probe}]
        )
        if record.probe != case.prompt or goal != case.goal or history != case.messages():
            raise ValueError("benchmark-fixed-input-mismatch")
        seen.add(pair)
        attempts.add(record.attempt_id)
        judgment = None
        try:
            candidate = JudgeOutput(
                verdict=record.judge_verdict,
                reasoning=record.judge_reasoning or "Not retained",
                evidence_refs_json=record.evidence_refs_json,
            )
            if (
                record.status == "complete"
                and record.capture_complete is True
                and evidence_supported(candidate, Observation(response=record.response))
            ):
                judgment = candidate
        except (ValueError, TypeError):
            pass
        rows.append(
            BenchmarkRecord(
                manifest_sha256=manifest.digest(),
                profile_sha256=digest(_json(getattr(manifest, variant + "_json"))),
                case_id=case.case_id,
                case_sha256=case.digest(),
                repeat_index=item["repeat_index"],
                variant=variant,
                terminal=True,
                status="complete" if judgment is not None else "incomplete",
                response=record.response,
                capture_complete=record.capture_complete is True,
                judge_verdict=judgment.verdict if judgment else "inconclusive",
                judge_reasoning=record.judge_reasoning,
                evidence_refs_json=judgment.evidence_refs_json if judgment else "[]",
                raw_judge_json=record.raw_judge_json,
                error_code=record.error_code,
                source_json=json_bytes(
                    {
                        "kind": "legacy-import",
                        "export": source_info,
                        "attempt_id": record.attempt_id,
                        "original_record": record.model_dump(),
                    }
                ).decode(),
            )
        )
    output = Path(output)
    output.mkdir(mode=0o700, exist_ok=False)
    write_rows(output / "records.jsonl", rows)
    return {"records": len(rows), "actual_calls_available": False, "model_calls": 0}


def _known_sum(rows, field):
    values = [getattr(r, field) for r in rows]
    return sum(values) if values and all(v is not None for v in values) else None


def _usage_total(rows, field):
    total = 0
    observed = False
    if not rows:
        return None
    for row in rows:
        usage = _json(row.usage_json)
        if row.target_calls is None or row.judge_calls is None:
            return None
        for role in ("target", "judge"):
            if getattr(row, role + "_calls"):
                value = (
                    usage.get(role, {}).get(field) if isinstance(usage.get(role), dict) else None
                )
                if type(value) not in (int, float) or value < 0:
                    return None
                total += value
                observed = True
    return total if observed and math.isfinite(total) else None


def recover(manifest_path, cases_path, journal_path, output):
    manifest, cases = inputs(manifest_path, cases_path)
    planned = {
        (v, c.case_id, r): c
        for c in cases
        for r in range(manifest.repeats)
        for v in ("baseline", "candidate")
    }
    raw = private_file(Path(journal_path))
    truncated = bool(raw and not raw.endswith(b"\n"))
    lines = raw.splitlines()[:-1] if truncated else raw.splitlines()
    latest = {}
    for line in lines:
        row = BenchmarkRecord.model_validate(_json(line))
        key = (row.variant, row.case_id, row.repeat_index)
        case = planned.get(key)
        if (
            case is None
            or row.manifest_sha256 != manifest.digest()
            or row.case_sha256 != case.digest()
            or row.profile_sha256 != digest(_json(getattr(manifest, row.variant + "_json")))
        ):
            raise ValueError("benchmark-journal-binding-invalid")
        previous = latest.get(key)
        if previous and (
            previous.terminal
            and previous != row
            or previous.response is not None
            and previous.response != row.response
            or previous.target_calls is not None
            and row.target_calls != previous.target_calls
            or previous.judge_calls == 1
            and row.judge_calls != 1
            or previous.raw_judge_json is not None
            and previous.raw_judge_json != row.raw_judge_json
            or previous.capture_complete
            and not row.capture_complete
            or any(
                getattr(previous, role + "_latency_seconds") is not None
                and getattr(previous, role + "_latency_seconds")
                != getattr(row, role + "_latency_seconds")
                for role in ("target", "judge")
            )
            or any(
                key not in _json(row.source_json) or _json(row.source_json)[key] != value
                for key, value in _json(previous.source_json).items()
            )
            or any(
                key not in _json(row.usage_json) or _json(row.usage_json)[key] != value
                for key, value in _json(previous.usage_json).items()
            )
        ):
            raise ValueError("benchmark-journal-stage-changed")
        latest[key] = row
    rows = [
        r
        if r.terminal
        else r.model_copy(
            update={
                "terminal": True,
                "status": "incomplete",
                "judge_verdict": "inconclusive",
                "error_code": "interrupted",
            }
        )
        for r in latest.values()
    ]
    output = Path(output)
    output.mkdir(mode=0o700, exist_ok=False)
    write_rows(output / "records.jsonl", rows)
    summary = {
        "records": len(rows),
        "journal_truncated": truncated,
        "model_calls": 0,
        "source_journal_sha256": hashlib.sha256(raw).hexdigest(),
    }
    atomic_file(output / "recovery.json", json_bytes(summary))
    return summary


def compare(manifest_path, cases_path, record_paths, output):
    manifest, cases = inputs(manifest_path, cases_path)
    planned = {
        (variant, c.case_id, repeat): c
        for c in cases
        for repeat in range(manifest.repeats)
        for variant in ("baseline", "candidate")
    }
    retained = {}
    for path in record_paths:
        for row in read_records(path):
            key = (row.variant, row.case_id, row.repeat_index)
            case = planned.get(key)
            if (
                case is None
                or key in retained
                or row.manifest_sha256 != manifest.digest()
                or row.case_sha256 != case.digest()
                or row.profile_sha256 != digest(_json(getattr(manifest, row.variant + "_json")))
            ):
                raise ValueError("benchmark-record-binding-invalid")
            retained[key] = row
    paired = []

    def delta(a, b):
        return b - a if a is not None and b is not None else None

    for case in cases:
        for repeat in range(manifest.repeats):
            a, b = [retained.get((v, case.case_id, repeat)) for v in ("baseline", "candidate")]
            paired.append(
                {
                    "case_id": case.case_id,
                    "case_sha256": case.digest(),
                    "repeat_index": repeat,
                    "baseline": a.model_dump() if a else None,
                    "candidate": b.model_dump() if b else None,
                    "response_changed": a.response != b.response
                    if a and b and a.response is not None and b.response is not None
                    else None,
                    "recorded_verdict_changed": a.judge_verdict != b.judge_verdict
                    if a and b
                    else None,
                    "target_latency_delta_seconds": delta(
                        a.target_latency_seconds, b.target_latency_seconds
                    )
                    if a and b
                    else None,
                    "target_calls_delta": delta(a.target_calls, b.target_calls)
                    if a and b
                    else None,
                    "total_tokens_delta": delta(
                        _usage_total([a], "total_tokens"), _usage_total([b], "total_tokens")
                    )
                    if a and b
                    else None,
                    "cost_usd_delta": delta(
                        _usage_total([a], "cost_usd"), _usage_total([b], "cost_usd")
                    )
                    if a and b
                    else None,
                }
            )
    variants = {}
    per_variant = len(cases) * manifest.repeats
    for variant in ("baseline", "candidate"):
        rows = [r for r in retained.values() if r.variant == variant]
        missing = per_variant - len(rows)
        counts = Counter(
            r.judge_verdict if r.status == "complete" else "inconclusive" for r in rows
        )
        counts["inconclusive"] += missing
        variants[variant] = {
            "planned_cases_including_repeats": per_variant,
            "retained_records": len(rows),
            "missing_records": missing,
            "statuses": dict(Counter(r.status for r in rows)),
            "citation_resolved_model_judgments": dict(counts),
            "target_calls": _known_sum(rows, "target_calls") if not missing else None,
            "judge_calls": _known_sum(rows, "judge_calls") if not missing else None,
            "target_latency_seconds": _known_sum(rows, "target_latency_seconds")
            if not missing
            else None,
            "tokens": {
                name: _usage_total(rows, name) if not missing else None
                for name in ("prompt_tokens", "completion_tokens", "total_tokens")
            },
            "cost_usd": _usage_total(rows, "cost_usd") if not missing else None,
        }
    summary = {
        "schema_version": "interplay-benchmark-comparison/1",
        "manifest_sha256": manifest.digest(),
        "planned_equal_query_budgets": True,
        "planned_calls_per_variant": {
            "target": per_variant,
            "judge": per_variant if manifest.judge_json else 0,
        },
        "call_count_basis": "Client attempts committed before dispatch; not provider billing. Legacy import counts and budget compliance are unverified.",
        "variants": variants,
        "paired_cases": len(paired),
        "accuracy": None,
        "accuracy_unavailable_reason": "Requires independently reviewed JUDGE-01 calibration; these are citation-checked model judgments, not measured correctness.",
        "uncertainty": "Sampling, serving state and request ordering can change replies even at temperature zero. Repeats are paired observations, not independent samples; no confidence or population improvement claim is inferred.",
        "source_revision_status": "operator-declared; executing implementation digest is checked on run",
        "release_eligible": False,
    }
    output = Path(output)
    output.mkdir(mode=0o700, exist_ok=False)
    atomic_file(output / "comparison.json", json_bytes(summary))
    write_rows(output / "paired-cases.jsonl", paired)
    return summary
