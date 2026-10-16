"""Reports preserve incomplete evidence, validate bindings, and render inert HTML offline."""

import hashlib
import json
import os
import subprocess
import sys
from html.parser import HTMLParser

import pytest

from interplay.assessment.models import AssessmentRecord
from interplay.assessment.storage import json_bytes, to_arrow
from interplay.report import generate_report, load_export
from interplay.runner_records import RunnerRecord


def runner(**updates):
    return RunnerRecord(
        **{
            "run_id": "a" * 32,
            "attempt_id": "b" * 32,
            "ordinal": 0,
            "method": "crescendo",
            "strategy": "direct",
            "goal": "Return a synthetic marker",
            "probe": "Synthetic probe",
            "response": "Synthetic response",
            "status": "complete",
            "judge_verdict": "failure",
            "judge_reasoning": "Marker absent",
            "evidence_refs_json": '["/response"]',
            "role_provenance_json": "{}",
            "created_at": "2026-01-01T00:00:00Z",
            **updates,
        }
    )


def write_jsonl(path, rows):
    path.write_bytes(b"".join(json_bytes(r.model_dump(mode="json")) + b"\n" for r in rows))
    path.chmod(0o600)
    return path


class ParsedHTML(HTMLParser):
    def __init__(self, content):
        super().__init__(convert_charrefs=True)
        self.tags, self.attributes, self.text = [], [], []
        self.feed(content)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attributes.extend(attrs)

    def handle_data(self, data):
        self.text.append(data)


def test_complete_interrupted_search_and_panel_totals(tmp_path):
    panel = {
        "judges": [
            {
                "judge_id": "a",
                "model": "same",
                "verdict": "success",
                "reasoning": "yes",
                "evidence_refs_json": '["/response"]',
            },
            {
                "judge_id": "b",
                "model": "same",
                "verdict": "failure",
                "reasoning": "no",
                "evidence_refs_json": '["/response"]',
            },
        ],
        "aggregation": "majority",
        "repeated_model_aliases": True,
    }
    rows = [
        runner(),
        runner(
            attempt_id="c" * 32,
            ordinal=1,
            judge_verdict="inconclusive",
            raw_judge_json=json.dumps(panel),
            method_metadata_json=json.dumps({"parent_id": "b" * 32}),
        ),
        runner(
            attempt_id="d" * 32,
            ordinal=2,
            status="incomplete",
            judge_verdict="success",
            error_code="interrupted",
        ),
        runner(
            attempt_id="e" * 32,
            ordinal=3,
            status="incomplete",
            response=None,
            judge_verdict="inconclusive",
            error_code="not-queried",
            method_metadata_json='{"evaluator_score":0.9}',
        ),
    ]
    source = write_jsonl(tmp_path / "records.jsonl", rows)
    before = source.read_bytes()
    summary = generate_report(source, tmp_path / "report")
    assert summary["records"] == 4
    assert summary["statuses"] == {"complete": 2, "incomplete": 2}
    assert summary["recorded_verdicts"] == {"failure": 1, "inconclusive": 2, "success": 1}
    assert summary["citation_resolved_complete_judgments"] == {"failure": 1}
    assert summary["noncomplete_records"] == 2
    assert summary["errors"] == {"interrupted": 1, "not-queried": 1}
    assert summary["panel_disagreements"] == summary["panel_traces"] == 1
    assert summary["panels_with_repeated_aliases"] == 1
    assert summary["source"]["sha256"] == hashlib.sha256(before).hexdigest()
    assert source.read_bytes() == before
    document = (tmp_path / "report/report.html").read_text()
    assert "evaluator_score" in document and "Panel member verdicts" in document
    assert f"href='#attempt-{'b' * 32}'" in document
    assert "independently verified effects" in document
    assert json.loads((tmp_path / "report/summary.json").read_text()) == summary
    assert (tmp_path / "report").stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in (tmp_path / "report").iterdir())


@pytest.mark.parametrize("version", ["interplay-assessment/1", "interplay-assessment/2"])
@pytest.mark.parametrize("extension", ["jsonl", "parquet", "arrow"])
def test_assessment_exports_versions_and_evidence(tmp_path, version, extension):
    record = AssessmentRecord(
        schema_version=version,
        campaign_id="a" * 32,
        attempt_id="b" * 32,
        ordinal=0,
        assessment_description="Synthetic assessment",
        success_criteria="marker",
        probe="Synthetic probe",
        adversarial_intent="Test criterion",
        strategy="direct",
        response="marker",
        capture_complete=True,
        logs_json='{"effect":"adapter reported"}',
        observation_origin="adapter-observed",
        judge_verdict="success",
        judge_reasoning="marker present",
        evidence_refs_json='["/response", "/logs/effect"]',
        status="complete",
        created_at="2026-01-01T00:00:00Z",
        provenance_json="{}",
    )
    source = write_export(tmp_path, [record], extension, version)
    summary = generate_report(source, tmp_path / "report")
    assert summary["citation_resolved_complete_judgments"] == {"success": 1}
    assert summary["independent_effect_verification"].startswith("unavailable")
    assert summary["source"]["schema_versions"] == [version]
    text = " ".join(ParsedHTML((tmp_path / "report/report.html").read_text()).text)
    assert "adapter reported" in text and "observation_origin" in text


def write_export(tmp_path, rows, extension, version):
    source = tmp_path / ("records." + extension)
    if extension == "jsonl":
        return write_jsonl(source, rows)
    import pyarrow as pa
    import pyarrow.parquet as pq

    cls = AssessmentRecord if version.startswith("interplay-assessment") else RunnerRecord
    table = to_arrow(
        rows,
        record_cls=cls,
        schema_version=version,
        int_fields=("ordinal",) if cls is RunnerRecord else ("ordinal", "round_index"),
        bool_fields=("capture_complete",)
        if cls is RunnerRecord
        else ("capture_complete", "release_eligible"),
    )
    if extension == "parquet":
        pq.write_table(table, source)
    else:
        with pa.ipc.new_file(str(source), table.schema) as writer:
            writer.write_table(table)
    source.chmod(0o600)
    return source


@pytest.mark.parametrize("version", ["interplay-runner/1", "interplay-runner/2"])
@pytest.mark.parametrize("extension", ["jsonl", "parquet", "arrow"])
def test_runner_formats_and_versions_agree(tmp_path, version, extension):
    record = runner(schema_version=version)
    source = write_export(tmp_path, [record], extension, version)
    records, provenance = load_export(source)
    assert records == [record] and provenance["schema_versions"] == [version]


def test_captured_content_cannot_create_markup_or_remote_assets(tmp_path):
    payload = '</pre><script>alert("x")</script><img src="https://evil.example/x"><a href="javascript:alert(1)">x</a>&"'
    record = runner(
        probe=payload,
        response=payload,
        judge_reasoning=payload,
        error_code=payload,
        method_metadata_json=json.dumps({"parent_id": payload}),
        raw_judge_json=json.dumps(
            {
                "judges": [
                    {"judge_id": payload, "verdict": "failure", "reasoning": payload},
                    {"judge_id": "b", "verdict": "failure", "model": payload},
                ]
            }
        ),
    )
    generate_report(write_jsonl(tmp_path / "records.jsonl", [record]), tmp_path / "report")
    document = (tmp_path / "report/report.html").read_text()
    parsed = ParsedHTML(document)
    assert "script" not in parsed.tags and "img" not in parsed.tags
    assert not any(
        k.startswith("on") or k == "src" or (k == "href" and not v.startswith("#"))
        for k, v in parsed.attributes
    )
    assert payload in "".join(parsed.text)
    assert "default-src 'none'" in document


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate-id",
        "duplicate-ordinal",
        "mixed-campaign",
        "unknown-schema",
        "mixed-family",
        "invalid-row",
        "torn-tail",
    ],
)
def test_invalid_exports_fail_without_output_or_private_error_text(tmp_path, mutation, capsys):
    from interplay.report import main

    first = runner()
    second = runner(attempt_id="c" * 32, ordinal=1)
    data = [first.model_dump(), second.model_dump()]
    if mutation == "duplicate-id":
        data[1]["attempt_id"] = first.attempt_id
    elif mutation == "duplicate-ordinal":
        data[1]["ordinal"] = 0
    elif mutation == "mixed-campaign":
        data[1]["run_id"] = "d" * 32
    elif mutation == "unknown-schema":
        data[1]["schema_version"] = "interplay-runner/999"
    elif mutation == "mixed-family":
        data[1]["schema_version"] = "interplay-assessment/2"
    elif mutation == "invalid-row":
        data[1]["probe"] = None
    source = tmp_path / "records.jsonl"
    source.write_bytes(
        b"\n".join(json_bytes(row) for row in data)
        + (b'\n{"PRIVATE-DIAGNOSTIC"' if mutation == "torn-tail" else b"\n")
    )
    source.chmod(0o600)
    assert main(["report", str(source), "--output", str(tmp_path / "report")]) == 2
    captured = capsys.readouterr()
    assert "report-failed" in captured.err and "PRIVATE-DIAGNOSTIC" not in captured.err
    assert not (tmp_path / "report").exists() and not captured.out


def test_private_source_and_no_overwrite(tmp_path):
    source = write_jsonl(tmp_path / "records.jsonl", [runner()])
    source.chmod(0o644)
    with pytest.raises(ValueError):
        generate_report(source, tmp_path / "report")
    source.chmod(0o600)
    link = tmp_path / "linked.jsonl"
    link.symlink_to(source)
    with pytest.raises(OSError):
        generate_report(link, tmp_path / "report")
    generate_report(source, tmp_path / "report")
    before = (tmp_path / "report/report.html").read_bytes()
    with pytest.raises(FileExistsError):
        generate_report(source, tmp_path / "report")
    assert (tmp_path / "report/report.html").read_bytes() == before


def test_empty_exports_and_invalid_diagnostics_are_explicit(tmp_path):
    source = write_export(tmp_path, [], "arrow", "interplay-runner/2")
    assert generate_report(source, tmp_path / "empty")["records"] == 0
    source = write_jsonl(
        tmp_path / "records.jsonl",
        [
            runner(
                evidence_refs_json='["/missing"]',
                raw_judge_json='{"judges":[]}',
                method_metadata_json="broken diagnostics",
            )
        ],
    )
    summary = generate_report(source, tmp_path / "invalid")
    assert summary["invalid_panel_traces"] == 1
    assert summary["citation_resolved_complete_judgments"] == {}
    assert "broken diagnostics" in (tmp_path / "invalid/report.html").read_text()


def test_cli_is_offline_and_does_not_import_provider_packages(tmp_path):
    source = write_jsonl(tmp_path / "records.jsonl", [runner()])
    log = tmp_path / "network.log"
    script = """
import importlib.abc, runpy, sys
class NoProviders(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'any_llm', 'httpx', 'judge_kappa', 'data_designer'}:
            raise AssertionError('provider-imported')
sys.meta_path.insert(0, NoProviders())
def guard(event, args):
    if event in {'socket.connect', 'socket.getaddrinfo', 'socket.sendto'}:
        with open(sys.argv[1], 'a') as stream:
            stream.write(event)
        raise AssertionError('network-during-report')
sys.addaudithook(guard)
sys.argv = ['interplay', 'report', sys.argv[2], '--output', sys.argv[3]]
runpy.run_module('interplay', run_name='__main__')
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(log), str(source), str(tmp_path / "report")],
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["records"] == 1
    assert "Private evidence" in result.stderr and not log.exists()


def test_original_runner_import_remains_compatible():
    from interplay.red_teaming.transport import RunnerRecord as Original

    assert Original is RunnerRecord


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"{}\n" * 5001,
        b"x" * (512 * 1024 + 1),
        b'{"schema_version":"interplay-runner/1","schema_version":"interplay-runner/2"}\n',
        b'{"score":NaN}\n',
    ],
)
def test_jsonl_limits_empty_and_ambiguous_json_are_rejected(tmp_path, data):
    source = tmp_path / "records.jsonl"
    source.write_bytes(data)
    source.chmod(0o600)
    with pytest.raises(ValueError):
        generate_report(source, tmp_path / "report")
    assert not (tmp_path / "report").exists()


def test_legacy_rows_with_new_export_metadata_and_rejected_unknown_metadata(tmp_path):
    import pyarrow as pa

    record = runner(schema_version="interplay-runner/1")
    # Recovery exports old rows using current schema metadata; retain both identities.
    source = write_export(tmp_path, [record], "arrow", "interplay-runner/2")
    records, provenance = load_export(source)
    assert records == [record] and provenance["declared_schema"] == "interplay-runner/2"
    table = to_arrow(
        [record],
        record_cls=RunnerRecord,
        schema_version="interplay-runner/999",
        int_fields=("ordinal",),
        bool_fields=("capture_complete",),
    )
    with pa.ipc.new_file(str(source), table.schema) as writer:
        writer.write_table(table)
    with pytest.raises(ValueError, match="unsupported-schema"):
        load_export(source)
