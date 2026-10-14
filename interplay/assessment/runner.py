"""Composable generation -> observation -> judgment, retaining incomplete work."""

import json
import re
import time
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from .models import AssessmentRecord, AssessmentSpec, JudgeOutput, Observation, Probe
from .storage import AssessmentStore, atomic_file, json_bytes


class ProbeGenerator(Protocol):
    def generate(
        self, spec: AssessmentSpec, *, deadline: float
    ) -> list[tuple[Probe, str | None]]: ...


class TargetAdapter(Protocol):
    def observe(self, probe: Probe, attempt_id: str, *, deadline: float) -> Observation: ...


class Judge(Protocol):
    def judge(
        self, spec: AssessmentSpec, probe: Probe, observation: Observation, *, deadline: float
    ) -> tuple[JudgeOutput, str | None]: ...


def redact(value, secrets):
    """Known transport credentials never enter journal, dataset or judge context."""
    if isinstance(value, str):
        for secret in sorted((s for s in secrets if s), key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, tuple):
        return tuple(redact(v, secrets) for v in value)
    if isinstance(value, dict):
        return {redact(k, secrets): redact(v, secrets) for k, v in value.items()}
    return value


def redact_fields(value, secrets):
    cleaned = redact(value, secrets)
    for key, original in value.items():
        if key.endswith("_json") and original is not None:
            cleaned[key] = json_bytes(redact(json.loads(original), secrets)).decode()
    return cleaned


def evidence_supported(judgment, observation):
    refs = json.loads(judgment.evidence_refs_json)
    if judgment.verdict != "inconclusive" and not refs:
        return False
    for ref in refs:
        value = observation.evidence()
        try:
            for part in ref.split("/")[1:]:
                part = part.replace("~1", "/").replace("~0", "~")
                if isinstance(value, list):
                    if not re.fullmatch(r"0|[1-9][0-9]*", part):
                        return False
                    value = value[int(part)]
                else:
                    value = value[part]
            if value is None or value == "" or value == [] or value == {}:
                return False
        except (KeyError, ValueError, TypeError, IndexError):
            return False
    return True


def run_assessment(spec, generator, target, judge, output, *, provenance=None, secrets=()):
    """Callbacks cooperate with deadlines; host hard bounds need an external owner.

    No target action is retried. Model conclusions stay distinct from independent
    effect/containment evidence. Explanations are concise evidence-based reasons,
    not requests for a model's hidden chain of thought.
    """
    spec = AssessmentSpec.model_validate(spec)
    spec = AssessmentSpec.model_validate(redact(spec.model_dump(), secrets))
    store = AssessmentStore(output)
    deadline = time.monotonic() + spec.campaign_seconds
    campaign_id = uuid4().hex
    records = []
    manifest = {
        "schema_version": "interplay-assessment/1",
        "campaign_id": campaign_id,
        "assessment_complete": False,
        "records": 0,
        "requested_probes": spec.probe_count,
        "successes": 0,
        "failures": 0,
        "inconclusive": 0,
        "release_eligible": False,
    }
    try:
        atomic_file(store.root / "manifest.json", json_bytes(manifest))
        try:
            probes = generator.generate(spec, deadline=deadline)
        except Exception:
            manifest["error_code"] = "probe-generation-failed"
            probes = []
        if len(probes) != spec.probe_count:
            manifest["error_code"] = "probe-generation-incomplete"
        for ordinal, (raw_probe, trace) in enumerate(probes[: spec.probe_count]):
            probe = Probe.model_validate(
                redact(Probe.model_validate(raw_probe).model_dump(), secrets)
            )
            record = AssessmentRecord(
                campaign_id=campaign_id,
                attempt_id=uuid4().hex,
                ordinal=ordinal,
                assessment_description=redact(spec.description, secrets),
                success_criteria=redact(spec.success_criteria, secrets),
                **probe.model_dump(),
                generation_trace_json=redact_fields({"trace_json": trace}, secrets)["trace_json"],
                created_at=datetime.now(UTC).isoformat(),
                provenance_json=json_bytes(redact(provenance or {}, secrets)).decode(),
            )
            store.stage(record)
            try:
                if time.monotonic() >= deadline:
                    raise TimeoutError
                observation = Observation.model_validate(
                    target.observe(probe, record.attempt_id, deadline=deadline)
                )
                observation = Observation.model_validate(
                    redact_fields(observation.model_dump(), secrets)
                )
                record = record.model_copy(
                    update={
                        **observation.model_dump(exclude={"origin"}),
                        "observation_origin": observation.origin,
                        "status": "observed",
                    }
                )
                # Commit response/logs/traces before the judge can fail or hang.
                store.stage(record)
            except Exception:
                record = record.model_copy(
                    update={"status": "incomplete", "error_code": "target-observation-failed"}
                )
            else:
                try:
                    if time.monotonic() >= deadline:
                        raise TimeoutError
                    judgment, judge_trace = judge.judge(spec, probe, observation, deadline=deadline)
                    judgment = JudgeOutput.model_validate(
                        redact_fields(JudgeOutput.model_validate(judgment).model_dump(), secrets)
                    )
                    missing = [
                        s for s in spec.required_surfaces if observation.evidence()[s] is None
                    ]
                    if not observation.capture_complete:
                        missing.append("complete-capture")
                    supported = evidence_supported(judgment, observation)
                    record = record.model_copy(
                        update={
                            "raw_judge_json": judgment.model_dump_json(),
                            "judge_trace_json": redact_fields({"trace_json": judge_trace}, secrets)[
                                "trace_json"
                            ],
                            "judge_verdict": judgment.verdict
                            if not missing and supported
                            else "inconclusive",
                            "judge_reasoning": judgment.reasoning,
                            "evidence_refs_json": judgment.evidence_refs_json,
                            "status": "complete" if not missing and supported else "incomplete",
                            "error_code": "required-evidence-missing"
                            if missing
                            else None
                            if supported
                            else "judge-evidence-unsupported",
                        }
                    )
                except Exception:
                    record = record.model_copy(
                        update={"status": "incomplete", "error_code": "judge-failed"}
                    )
            store.stage(record)
            records.append(record)
        store.export(records)
        manifest.update(
            {
                "records": len(records),
                "assessment_complete": not manifest.get("error_code")
                and len(records) == spec.probe_count
                and all(r.status == "complete" for r in records),
                "successes": sum(r.judge_verdict == "success" for r in records),
                "failures": sum(r.judge_verdict == "failure" for r in records),
                "inconclusive": sum(r.judge_verdict == "inconclusive" for r in records),
            }
        )
        atomic_file(store.root / "manifest.json", json_bytes(manifest))
        return manifest
    finally:
        store.close()
