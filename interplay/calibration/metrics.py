"""Offline paired metrics; agreement is not accuracy or model independence."""

import hashlib
import itertools
import math
from collections import Counter
from pathlib import Path

from ..assessment.judgments import aggregate_verdicts, parse_judge_output
from ..assessment.runner import evidence_supported
from ..assessment.storage import atomic_file, json_bytes
from .models import GoldLabel, Prediction
from .workflow import bound, load_cases, load_judges, read_rows, write_rows

VERDICTS = ("success", "failure", "inconclusive")


def proportion(numerator, denominator):
    """Nominal 95% Wilson binomial interval; dependence limits are reported."""
    if not 0 <= numerator <= denominator:
        raise ValueError("calibration-invalid-proportion")
    if denominator == 0:
        return {"numerator": 0, "denominator": 0, "rate": None, "wilson_95": None}
    z = 1.959963984540054
    p = numerator / denominator
    scale = 1 + z * z / denominator
    center = (p + z * z / (2 * denominator)) / scale
    half = z * math.sqrt(p * (1 - p) / denominator + z * z / (4 * denominator**2)) / scale
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": p,
        "wilson_95": [max(0.0, center - half), min(1.0, center + half)],
    }


def classification_metrics(gold, predicted):
    if len(gold) != len(predicted):
        raise ValueError("calibration-paired-cases-required")
    matrix = {actual: {guess: 0 for guess in VERDICTS} for actual in VERDICTS}
    for actual, guess in zip(gold, predicted, strict=True):
        matrix[actual][guess] += 1
    correct = sum(actual == guess for actual, guess in zip(gold, predicted, strict=True))
    answered = sum(v != "inconclusive" for v in predicted)
    return {
        "confusion_matrix": matrix,
        "three_class_accuracy": proportion(correct, len(gold)),
        "decisive_coverage": proportion(answered, len(gold)),
        "abstention_rate": proportion(len(gold) - answered, len(gold)),
        "selective_accuracy": proportion(
            sum(a == p and p != "inconclusive" for a, p in zip(gold, predicted, strict=True)),
            answered,
        ),
        "false_positive_rate": proportion(matrix["failure"]["success"], gold.count("failure")),
        "sensitivity": proportion(matrix["success"]["success"], gold.count("success")),
        "ambiguous_false_confirmation_rate": proportion(
            matrix["inconclusive"]["success"], gold.count("inconclusive")
        ),
    }


def normalize(case, prediction):
    reason = None
    raw_verdict = None
    effective = "inconclusive"
    if prediction is None:
        reason = "missing-prediction"
    elif prediction.error_code:
        reason = "not-run" if prediction.error_code == "not-run" else "recorded-provider-error"
    elif prediction.finish_reason != "stop" or prediction.raw_reply is None:
        reason = "unfinished-or-missing-reply"
    else:
        try:
            judgment = parse_judge_output(prediction.raw_reply)
            raw_verdict = judgment.verdict
            observation = case.observation()
            if not observation.capture_complete:
                reason = "incomplete-capture"
            elif not evidence_supported(judgment, observation):
                reason = "unsupported-citations"
            else:
                effective = judgment.verdict
        except (ValueError, TypeError, RecursionError):
            reason = "invalid-model-output"
    return {
        "case_id": case.case_id,
        "case_sha256": case.digest(),
        "effective_verdict": effective,
        "raw_verdict": raw_verdict,
        "reason": reason,
        "prediction_json": prediction.model_dump_json() if prediction else None,
    }


def _canonical_digest(rows):
    return hashlib.sha256(json_bytes([r.model_dump(mode="json") for r in rows])).hexdigest()


def evaluate(cases_path, gold_path, judges_path, prediction_paths, output):
    cases, judges = load_cases(cases_path), load_judges(judges_path)
    gold_rows = read_rows(gold_path, GoldLabel)
    gold = {}
    for row in gold_rows:
        bound(row, cases)
        if row.case_id in gold:
            raise ValueError("calibration-duplicate-gold")
        gold[row.case_id] = row
    if set(gold) != set(cases):
        raise ValueError("calibration-complete-human-reference-required")
    raw, keyed = [], {}
    for path in prediction_paths:
        for row in read_rows(path, Prediction):
            bound(row, cases)
            judge = judges.get(row.judge_id)
            if judge is None or judge.digest() != row.judge_sha256:
                raise ValueError("calibration-judge-binding-invalid")
            key = (row.judge_id, row.case_id)
            if key in keyed:
                raise ValueError("calibration-duplicate-prediction")
            keyed[key] = row
            raw.append(row)
    actual = [gold[c].verdict for c in cases]
    normalized, predicted, metrics = [], {}, {}
    for judge_id in judges:
        rows = [
            dict(normalize(c, keyed.get((judge_id, c.case_id))), judge_id=judge_id)
            for c in cases.values()
        ]
        normalized.extend(rows)
        values = [r["effective_verdict"] for r in rows]
        predicted[judge_id] = values
        metrics[judge_id] = {
            "identity": judges[judge_id].model_dump(),
            "outcome_reasons": dict(Counter(r["reason"] for r in rows if r["reason"])),
            **classification_metrics(actual, values),
        }
    panels = {}
    if len(judges) >= 2:
        for policy in ("majority", "unanimous"):
            panel_values = [
                aggregate_verdicts(list(votes), policy)
                for votes in zip(*predicted.values(), strict=True)
            ]
            panels[policy] = classification_metrics(actual, panel_values)
    agreements = [
        {
            "judges": [a, b],
            "exact_agreement_including_abstentions": proportion(
                sum(x == y for x, y in zip(predicted[a], predicted[b], strict=True)), len(cases)
            ),
        }
        for a, b in itertools.combinations(judges, 2)
    ]
    model_count = len({j.model_key() for j in judges.values()})
    summary = {
        "schema_version": "interplay-calibration-score/1",
        "cases": len(cases),
        "human_origin": "reviewer-attested; identity/independence/origin not authenticated by software",
        "reference_verdicts": dict(Counter(actual)),
        "judges": metrics,
        "panels": panels,
        "agreement_separate_from_accuracy": agreements,
        "distinct_declared_model_identities": model_count,
        "repeated_model_aliases": len({j.model for j in judges.values()}) < len(judges),
        "repeated_declared_model_identities": model_count < len(judges),
        "initial_human_label_agreement": proportion(
            sum(GoldLabel.model_validate(r).adjudication_json is None for r in gold_rows),
            len(cases),
        ),
        "scope": "Offline scoring of retained predictions, not a live model run or completed roadmap qualification.",
        "retained_prediction_records": len(raw),
        "retained_reply_records": sum(r.raw_reply is not None for r in raw),
        "missing_or_not_run": sum(
            r["reason"] in ("missing-prediction", "not-run") for r in normalized
        ),
        "uncertainty": "Nominal 95% Wilson binomial intervals assume independent cases. Matched synthetic families are dependent: intervals are descriptive and do not establish population coverage or general model performance.",
        "identity_limit": "Model/provider/revision identity is operator declared; different names do not prove independent weights or errors.",
        "minimum_60_cases": len(cases) >= 60,
        "at_least_two_declared_models": len({j.model for j in judges.values()}) >= 2,
        "canonical_input_sha256": {
            "cases": _canonical_digest(list(cases.values())),
            "gold": _canonical_digest(gold_rows),
            "judges": _canonical_digest(list(judges.values())),
            "predictions": _canonical_digest(raw),
        },
        "release_eligible": False,
    }
    output = Path(output)
    output.mkdir(mode=0o700, exist_ok=False)
    atomic_file(output / "metrics.json", json_bytes(summary) + b"\n")
    write_rows(output / "normalized-predictions.jsonl", normalized)
    return summary
