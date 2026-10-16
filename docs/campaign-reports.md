# Offline campaign reports

[Documentation map](README.md) · [Assessment exports](assessment.md) · [Runner exports](attacks/runner-results.md) · [REPORT-01 / #63](https://github.com/interplay-adversarial/interplay/issues/63)

Generate a standalone HTML report from retained campaign exports:

```sh
interplay report output/completed-campaign --output output/new-report
# Or select one export explicitly:
interplay report output/completed-campaign/records.parquet --output output/new-parquet-report
interplay report output/recovered-campaign/records.arrow --output output/new-recovered-report
```

Open `new-report/report.html` locally in a browser. It includes status/verdict
counts, incomplete/search-only attempts, errors, parent links, prompts, captured
responses/logs/traces, conversation history, judge reasoning, evidence references
and retained panel member verdicts. Expand an attempt's diagnostics for every
original field, including search scores, provenance and raw judge replies.
Missing parents are labeled as absent from the selected export.

`summary.json` contains the same counts and the SHA-256 of the exact source
snapshot. No success rate or release decision is inferred. A report describes
only that snapshot; it does not assert that the campaign finished or all intended
attempts executed. Export files and journals are unchanged.

## Interpreting results

- **Statuses / recorded verdicts:** every row is counted, including incomplete
  and search-only rows. An unfinished verdict is not promoted to a complete judgment.
- **Complete judgments with resolved citations:** the attempt and capture are
  complete, its verdict is success/failure, and the citation schema and referenced
  values pass the existing evidence-resolution check. This checks pointers, not
  semantic correctness. A judge can cite a real response and still be wrong.
- **Panel disagreements:** valid retained panel traces whose member verdicts
  differ. Missing traces do not establish agreement. Invalid traces are counted
  separately. Repeated model aliases remain flagged and do not establish
  independent judgment. Reports do not rerun judges or compute calibration.
- **Search diagnostics:** retained method scores are shown separately from
  captured evidence and model judgments.
- **Environment effects:** adapter/endpoint-reported logs and traces remain
  captured evidence. Independently verified effects and containment are
  unavailable from these exports alone; reports do not infer them.

## Input and recovery

Supported versions are `interplay-assessment/1`, `interplay-assessment/2`,
`interplay-runner/1` and `interplay-runner/2`, in JSONL, Parquet or Arrow IPC file
format. No inference-provider imports, credentials or network access are needed.
Parquet/Arrow decoding uses the existing PyArrow dependency. Historical version-1
rows exported by recovery with version-2 file metadata remain readable within the
same schema family; both identities are recorded.

A directory selects `records.jsonl`. Reporting does not read `events.jsonl` or
repair campaigns. If a hard interruption left only a journal, first recover it:

```sh
interplay runner-recover output/interrupted-run
# Description-driven assessment:
interplay assessment-recover --output output/interrupted-assessment
```

Then report the recovered export. Empty JSONL has no schema header; use the
schema-bearing Parquet/Arrow export for empty campaigns. Garak native scanner
reports and aggregate `summary.json` files are unsupported in this increment.

The reader rejects unknown schemas, mixed campaign identities/schema families,
duplicate IDs/ordinals, malformed/duplicate-key JSON, nonfinite JSON numbers and
invalid row fields. It does not discard malformed trailing export lines as
journal recovery does. Source files must be owned by the current user, private
(no group/other access), regular files and not direct symlinks. Input is capped
at 128 MiB and 5,000 rows; JSONL rows are capped at 512 KiB. Expanded Arrow/Parquet
tables are also checked against size/row limits.

## Private output

The CLI warns before exporting: reports can contain sensitive prompts, responses,
endpoints and diagnostics. It creates a **new** 0700 directory with 0600
`report.html` and `summary.json` files and refuses to overwrite an existing
directory. There is no automatic publication or additional secret redaction.
Review the entire artifact before sharing it.

Captured content, including judge IDs and diagnostic fields, is escaped as text.
HTML has no JavaScript, remote fonts/assets, image loads or captured HTML
execution. A restrictive content-security policy adds defense in depth; lineage
links point only to validated attempt IDs inside the document. The CLI prints
counts only and uses a generic error without source content.

For Python callers:

```python
from pathlib import Path
from interplay.report import generate_report

summary = generate_report(Path("output/campaign/records.jsonl"), Path("output/new-report"))
print(summary["records"], summary["noncomplete_records"])
```

Tests demonstrate complete, interrupted and panel-disagreement exports, every
supported version/format, inert captured markup, source/output permissions, and
a credential-free CLI subprocess with provider imports and DNS/connect/sendto
operations forbidden.
