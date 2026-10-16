"""Private preparation, human-label resolution and provenance validation."""

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from ..assessment.storage import atomic_file, json_bytes, private_file
from ..report import _json
from .corpus import RUBRIC, seed_cases
from .models import Case, GoldLabel, HumanLabel, JudgeIdentity, Prediction


def read_rows(path, cls):
    raw = private_file(Path(path), limit=16 * 1024 * 1024)
    lines = raw.splitlines()
    if len(lines) > 20000 or any(len(line) > 512 * 1024 for line in lines):
        raise ValueError("calibration-input-limit")
    return [cls.model_validate(_json(line)) for line in lines]


def write_rows(path, rows):
    atomic_file(
        path,
        b"".join(
            json_bytes(r.model_dump(mode="json") if hasattr(r, "model_dump") else r) + b"\n"
            for r in rows
        ),
    )


def load_cases(path):
    cases = read_rows(path, Case)
    if not 1 <= len(cases) <= 1000 or len({c.case_id for c in cases}) != len(cases):
        raise ValueError("calibration-case-identities-invalid")
    return {c.case_id: c for c in cases}


def bound(row, cases):
    case = cases.get(row.case_id)
    if (
        case is None
        or row.case_sha256 != case.digest()
        or row.rubric_version != case.rubric_version
    ):
        raise ValueError("calibration-case-binding-invalid")


def prepare(output):
    output = Path(output)
    cases = seed_cases()
    output.mkdir(mode=0o700, exist_ok=False)
    write_rows(output / "cases.jsonl", cases)
    atomic_file(output / "rubric.md", RUBRIC.encode())
    atomic_file(output / "judges.json", b"[]\n")
    atomic_file(
        output / "collection.example.json",
        json_bytes(
            {
                "judges": [
                    {
                        "identity": JudgeIdentity(
                            judge_id=f"judge-{name}",
                            provider="openai-compatible",
                            model=f"replace-with-model-{name}",
                        ).model_dump(),
                        "endpoint": {
                            "base_url": "https://judge.example/v1",
                            "model": f"replace-with-model-{name}",
                            "api_key_env": f"JUDGE_{name.upper()}_KEY",
                            "request_seconds": 30,
                            "max_tokens": 1024,
                        },
                    }
                    for name in ("a", "b")
                ]
            }
        ),
    )
    for reviewer in ("review-a", "review-b"):
        packet = output / reviewer
        packet.mkdir(mode=0o700)
        write_rows(packet / "cases.jsonl", [{**c.task(), "case_sha256": c.digest()} for c in cases])
        write_rows(
            packet / "labels.jsonl",
            [HumanLabel(case_id=c.case_id, case_sha256=c.digest()) for c in cases],
        )
        atomic_file(packet / "rubric.md", RUBRIC.encode())
    summary = {
        "cases": len(cases),
        "design_buckets": dict(Counter(c.design_bucket for c in cases)),
        "human_labels": 0,
        "reference_ready": False,
        "metrics_generated": False,
        "rubric_sha256": hashlib.sha256(RUBRIC.encode()).hexdigest(),
    }
    atomic_file(output / "preparation.json", json_bytes(summary))
    return summary


def compile_gold(cases_path, label_paths, adjudications_path, output):
    cases = load_cases(cases_path)
    grouped = defaultdict(list)
    for path in label_paths:
        seen = set()
        for row in read_rows(path, HumanLabel):
            bound(row, cases)
            if row.case_id in seen:
                raise ValueError("calibration-duplicate-label-row")
            seen.add(row.case_id)
            if row.verdict is not None:
                grouped[row.case_id].append(row)
    decisions = {}
    for row in read_rows(adjudications_path, HumanLabel) if adjudications_path else []:
        bound(row, cases)
        if row.case_id in decisions or row.verdict is None:
            raise ValueError("calibration-adjudication-invalid")
        decisions[row.case_id] = row
    gold, pending, used = [], [], set()
    for case_id, case in cases.items():
        labels = grouped[case_id]
        if len(labels) > 2 or len({label.reviewer_id for label in labels}) != len(labels):
            raise ValueError("calibration-two-independent-reviewers-required")
        if len(labels) < 2:
            pending.append({"case_id": case_id, "reason": "missing-independent-labels"})
            continue
        disagree = labels[0].verdict != labels[1].verdict
        decision = decisions.get(case_id)
        if disagree and decision is None:
            pending.append({"case_id": case_id, "reason": "adjudication-required"})
            continue
        if decision is not None:
            used.add(case_id)
        gold.append(
            GoldLabel(
                case_id=case_id,
                case_sha256=case.digest(),
                verdict=decision.verdict if disagree else labels[0].verdict,
                labels_json=json.dumps([label.model_dump() for label in labels]),
                adjudication_json=decision.model_dump_json() if decision else None,
            )
        )
    if set(decisions) != used:
        raise ValueError("calibration-orphan-adjudication")
    output = Path(output)
    output.mkdir(mode=0o700, exist_ok=False)
    summary = {
        "cases": len(cases),
        "resolved_cases": len(gold),
        "reference_ready": not pending,
        "metrics_generated": False,
        "human_origin": "reviewer-attested; not authenticated by software",
        "pending": pending,
    }
    atomic_file(output / "label-status.json", json_bytes(summary))
    if not pending:
        write_rows(output / "gold.jsonl", gold)
    return summary


def load_judges(path):
    data = _json(private_file(Path(path), limit=65536))
    if not isinstance(data, list) or not 1 <= len(data) <= 16:
        raise ValueError("calibration-judge-roster-invalid")
    judges = [JudgeIdentity.model_validate(row) for row in data]
    if len({j.judge_id for j in judges}) != len(judges):
        raise ValueError("calibration-duplicate-judge-id")
    return {j.judge_id: j for j in judges}


def prediction_templates(cases_path, judges_path, output):
    cases, judges = load_cases(cases_path), load_judges(judges_path)
    output = Path(output)
    output.mkdir(mode=0o700, exist_ok=False)
    write_rows(
        output / "predictions.jsonl",
        [
            Prediction(
                case_id=c.case_id,
                case_sha256=c.digest(),
                judge_id=j.judge_id,
                judge_sha256=j.digest(),
                error_code="not-run",
            )
            for j in judges.values()
            for c in cases.values()
        ],
    )
    return {
        "cases": len(cases),
        "judges": len(judges),
        "model_calls": 0,
        "metrics_generated": False,
    }
