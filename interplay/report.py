"""Offline reports from retained exports; no provider imports or model calls."""

import argparse
import hashlib
import html
import json
from collections import Counter
from pathlib import Path

from .assessment.models import AssessmentRecord, JudgeOutput, Observation
from .assessment.runner import evidence_supported
from .assessment.storage import atomic_file, json_bytes, private_file
from .runner_records import RunnerRecord

SCHEMAS = {
    "interplay-assessment/1": AssessmentRecord,
    "interplay-assessment/2": AssessmentRecord,
    "interplay-runner/1": RunnerRecord,
    "interplay-runner/2": RunnerRecord,
}
LIMIT = 128 * 1024 * 1024
WARNING = "Private evidence: this report may contain sensitive prompts, responses and endpoints. Review before sharing."


def _json(value):
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("report-duplicate-json-key")
            result[key] = item
        return result

    return json.loads(
        value,
        object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
    )


def load_export(source: Path):
    """Read one immutable export snapshot; never read or recover its journal."""
    source = Path(source)
    if source.is_dir():
        source = source / "records.jsonl"
    raw = private_file(source, limit=LIMIT)
    declared = None
    if source.suffix == ".jsonl":
        lines = raw.splitlines()
        if len(lines) > 5000 or any(len(line) > 512 * 1024 for line in lines):
            raise ValueError("report-record-limit")
        rows = [_json(line) for line in lines]
    elif source.suffix in (".parquet", ".arrow"):
        import pyarrow as pa

        buffer = pa.BufferReader(raw)
        if source.suffix == ".parquet":
            import pyarrow.parquet as pq

            reader = pq.ParquetFile(buffer)
            if (
                reader.metadata.num_rows > 5000
                or sum(
                    reader.metadata.row_group(i).total_byte_size
                    for i in range(reader.metadata.num_row_groups)
                )
                > LIMIT
            ):
                raise ValueError("report-record-limit")
            table = reader.read()
        else:
            with pa.ipc.open_file(buffer) as reader:
                table = reader.read_all()
        if table.num_rows > 5000 or table.nbytes > LIMIT:
            raise ValueError("report-record-limit")
        declared = (table.schema.metadata or {}).get(b"schema_version", b"").decode()
        if declared not in SCHEMAS:
            raise ValueError("report-unsupported-schema")
        rows = table.to_pylist()
    else:
        raise ValueError("report-unsupported-format")
    records = []
    for row in rows:
        if not isinstance(row, dict) or row.get("schema_version") not in SCHEMAS:
            raise ValueError("report-unsupported-schema")
        records.append(SCHEMAS[row["schema_version"]].model_validate(row))
    # JSONL has no schema header; an empty file cannot identify an export family.
    if not records and declared is None:
        raise ValueError("report-empty-jsonl-use-arrow-or-parquet")
    families = {r.schema_version.split("/")[0] for r in records}
    if declared:
        families.add(declared.split("/")[0])
    identities = {getattr(r, "run_id", getattr(r, "campaign_id", None)) for r in records}
    if (
        len(families) != 1
        or len(identities) > 1
        or len({r.attempt_id for r in records}) != len(records)
        or len({r.ordinal for r in records}) != len(records)
    ):
        raise ValueError("report-export-binding-invalid")
    return sorted(records, key=lambda r: r.ordinal), {
        "format": source.suffix[1:],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "schema_versions": sorted({r.schema_version for r in records} or {declared}),
        "declared_schema": declared,
    }


def _structured(value, fallback):
    try:
        return _json(value) if value is not None else fallback
    except (ValueError, TypeError, RecursionError):
        return fallback


def _citation_check(record):
    """Check citation resolution, never infer semantic correctness from a pointer."""
    if record.status != "complete" or record.capture_complete is not True:
        return False
    try:
        judgment = JudgeOutput(
            verdict=record.judge_verdict,
            reasoning=record.judge_reasoning or "No retained reasoning",
            evidence_refs_json=record.evidence_refs_json,
        )
        observation = Observation(
            response=record.response,
            capture_complete=True,
            logs_json=getattr(record, "logs_json", None),
            traces_json=getattr(record, "traces_json", None),
            conversation_trace_json=record.conversation_trace_json,
        )
        return record.judge_verdict != "inconclusive" and evidence_supported(judgment, observation)
    except (ValueError, TypeError, RecursionError):
        return False


def _panel(record):
    trace = _structured(record.raw_judge_json, None)
    if not isinstance(trace, dict) or "judges" not in trace:
        return None
    judges = trace["judges"]
    if (
        not isinstance(judges, list)
        or not 2 <= len(judges) <= 16
        or any(
            not isinstance(j, dict)
            or not isinstance(j.get("judge_id"), str)
            or j.get("verdict") not in ("success", "failure", "inconclusive")
            for j in judges
        )
        or len({j["judge_id"] for j in judges}) != len(judges)
    ):
        return {"valid": False}
    return {
        "valid": True,
        "disagreement": len({j["verdict"] for j in judges}) > 1,
        "repeated_model_aliases": trace.get("repeated_model_aliases") is True,
        "judges": judges,
    }


def _metadata(record):
    value = _structured(getattr(record, "method_metadata_json", None), {})
    return value if isinstance(value, dict) else {}


def summarize(records, source):
    panels = [panel for r in records if (panel := _panel(r)) is not None]
    return {
        "schema_version": "interplay-report/1",
        "source": source,
        "records": len(records),
        "statuses": dict(sorted(Counter(r.status for r in records).items())),
        "recorded_verdicts": dict(sorted(Counter(r.judge_verdict for r in records).items())),
        "citation_resolved_complete_judgments": dict(
            sorted(Counter(r.judge_verdict for r in records if _citation_check(r)).items())
        ),
        "noncomplete_records": sum(r.status != "complete" for r in records),
        "errors": dict(sorted(Counter(r.error_code for r in records if r.error_code).items())),
        "panel_traces": len(panels),
        "panel_disagreements": sum(p.get("disagreement", False) for p in panels),
        "invalid_panel_traces": sum(not p["valid"] for p in panels),
        "panels_with_repeated_aliases": sum(p.get("repeated_model_aliases", False) for p in panels),
        "independent_effect_verification": "unavailable; not inferred from exports",
        "release_eligible": False,
    }


def _escape(value):
    return html.escape(str(value), quote=True)


def _pre(value):
    return "<pre>" + _escape(value if value is not None else "Not retained") + "</pre>"


def _table(headers, rows):
    return (
        "<table><thead><tr>"
        + "".join("<th scope='col'>" + _escape(h) + "</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "".join(
            "<tr>" + "".join("<td>" + _escape(v) + "</td>" for v in row) + "</tr>" for row in rows
        )
        + "</tbody></table>"
    )


def render_report(records, summary):
    """All captured values are text; only fixed markup and internal links execute."""
    sections = [
        """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Interplay campaign report</title><style>
body{font-family:system-ui,sans-serif;max-width:75rem;margin:2rem auto;padding:0 1rem;line-height:1.5;color:#202124;background:#fff}
table{border-collapse:collapse;width:100%;margin:1rem 0}th,td{border:1px solid #bbb;text-align:left;padding:.5rem;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f4f4;padding:1rem}article{border-top:2px solid #aaa;margin-top:2rem}
.warning{border:2px solid #8b4000;padding:1rem}summary{cursor:pointer}a{color:#174ea6}
</style></head><body><main><h1>Interplay campaign report</h1>""",
        "<p class='warning'>" + _escape(WARNING) + "</p>",
        "<p>Offline snapshot of retained records. Recorded verdicts are model conclusions. "
        "Citation resolution checks only that references point to retained evidence; it does not "
        "validate reasoning or judge accuracy. Search scores are diagnostics. Adapter-reported "
        "logs/traces do not establish independently verified effects, containment or release eligibility.</p>",
        "<h2>Summary</h2>"
        + _table(
            ["Measure", "Count"],
            [
                ("Retained attempts (including incomplete/search-only)", summary["records"]),
                ("Noncomplete attempts", summary["noncomplete_records"]),
                ("Panel traces", summary["panel_traces"]),
                ("Panel disagreements", summary["panel_disagreements"]),
                ("Invalid panel traces", summary["invalid_panel_traces"]),
                ("Panels with repeated model aliases", summary["panels_with_repeated_aliases"]),
            ],
        ),
    ]
    for title, key in (
        ("Statuses", "statuses"),
        ("Recorded verdicts", "recorded_verdicts"),
        ("Complete judgments with resolved citations", "citation_resolved_complete_judgments"),
        ("Errors", "errors"),
    ):
        sections.append("<h3>" + title + "</h3>" + _table([title, "Count"], summary[key].items()))
    sections.append(
        "<p>Missing panel traces do not imply agreement. Repeated aliases do not establish independence. "
        "No attack success rate is inferred from these counts.</p><h2>Attempts and lineage</h2><ol>"
    )
    for r in records:
        sections.append(
            f"<li><a href='#attempt-{r.attempt_id}'>Attempt {r.ordinal}</a>: "
            + _escape(r.status)
            + " / "
            + _escape(r.judge_verdict)
            + "</li>"
        )
    sections.append("</ol>")
    ids = {r.attempt_id for r in records}
    for r in records:
        parent = getattr(r, "parent_attempt_id", None) or _metadata(r).get("parent_id")
        parent_link = "Seed / no retained parent"
        if isinstance(parent, str):
            parent_link = (
                f"<a href='#attempt-{parent}'>" + _escape(parent) + "</a>"
                if parent in ids
                else _escape(parent) + " (not present in this export)"
            )
        sections.extend(
            [
                f"<article id='attempt-{r.attempt_id}'><h2>Attempt {r.ordinal}</h2>",
                "<p>Parent: " + parent_link + "</p>",
                _table(
                    ["Field", "Retained value"],
                    [
                        ("Attempt ID", r.attempt_id),
                        ("Status", r.status),
                        ("Capture complete", r.capture_complete),
                        ("Recorded verdict", r.judge_verdict),
                        ("Error", r.error_code or "None"),
                        (
                            "Citation resolution",
                            "Resolved; semantic correctness unverified"
                            if _citation_check(r)
                            else "Not established",
                        ),
                        ("Strategy", r.strategy),
                        ("Method", getattr(r, "method", "assessment")),
                    ],
                ),
                "<h3>Goal / criteria</h3>"
                + _pre(getattr(r, "goal", getattr(r, "success_criteria", None))),
                "<h3>Probe</h3>" + _pre(r.probe),
                f"<div id='evidence-{r.attempt_id}'><h3>Captured evidence</h3><h4>/response</h4>"
                + _pre(r.response),
            ]
        )
        for name in ("logs_json", "traces_json", "conversation_trace_json"):
            sections.append("<h4>" + _escape(name) + "</h4>" + _pre(getattr(r, name, None)))
        sections.extend(
            [
                "</div><h3>Judge reasoning</h3>" + _pre(r.judge_reasoning),
                "<p>Evidence references (into the captured surfaces above):</p>"
                + _pre(r.evidence_refs_json),
            ]
        )
        panel = _panel(r)
        if panel and panel["valid"]:
            sections.append(
                "<h3>Panel member verdicts</h3>"
                + _table(
                    ["Judge", "Model", "Verdict", "Reasoning", "Evidence references"],
                    [
                        (
                            j["judge_id"],
                            j.get("model"),
                            j["verdict"],
                            j.get("reasoning"),
                            j.get("evidence_refs_json"),
                        )
                        for j in panel["judges"]
                    ],
                )
            )
        elif panel:
            sections.append("<p>Invalid panel trace; disagreement unavailable.</p>")
        sections.append(
            "<details><summary>Retained diagnostics, search scores and provenance</summary>"
            "<p>Search diagnostics and endpoint/adapter reports are not independently verified effects.</p>"
        )
        # Preserve every source field, even malformed nested diagnostics, without reinterpreting it.
        sections.append(
            _pre(json.dumps(r.model_dump(mode="json"), ensure_ascii=True, indent=2))
            + "</details></article>"
        )
    sections.append(
        "<h2>Source snapshot</h2>"
        + _pre(json.dumps(summary["source"], indent=2))
        + "</main></body></html>"
    )
    return "\n".join(sections)


def generate_report(source: Path, output: Path):
    """Create a new 0700 report directory; leave the source export untouched."""
    records, provenance = load_export(source)
    summary = summarize(records, provenance)
    content = render_report(records, summary).encode()
    output = Path(output)
    output.mkdir(mode=0o700, exist_ok=False)
    atomic_file(output / "report.html", content)
    atomic_file(output / "summary.json", json_bytes(summary) + b"\n")
    return summary


class ReportParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, '{"error":"invalid-report-input"}\n')


def main(argv):
    parser = ReportParser(
        prog="interplay report", description="Create a private offline HTML campaign report."
    )
    parser.add_argument(
        "source", type=Path, help="campaign directory or records.jsonl/.parquet/.arrow"
    )
    parser.add_argument("--output", type=Path, required=True, help="new private report directory")
    args = parser.parse_args(argv[1:])
    import sys

    print(WARNING, file=sys.stderr)
    try:
        summary = generate_report(args.source, args.output)
        print(
            json.dumps(
                {"records": summary["records"], "report_created": True, "release_eligible": False}
            )
        )
        return 0
    except Exception:
        print('{"error":"report-failed","release_eligible":false}', file=sys.stderr)
        return 2
