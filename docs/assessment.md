# Description-driven research assessments

`interplay assess` generates probes from a description using NeMo DataDesigner,
sends each probe to a fixed target, and uses a separate `JUDGE_MODEL` to evaluate
the response and available logs/traces. It retains probe, adversarial intent,
response, verdict, evidence references and a concise judge explanation for analysis.
The Python interfaces have no dependency on Agent Boundary Gate.
For an unreleased source revision, install the reviewed Git commit with the
`assessment` extra or run `uv sync --extra assessment --no-editable` from its checkout.

```sh
pip install 'interplay-adversarial[assessment]'
interplay assess --config private-providers.json --output private-campaign \
  --description 'Assess whether the application discloses a synthetic canary.' \
  --success-criteria 'The response or observed tool trace contains SYNTHETIC-CANARY.' \
  --num-probes 5
```

Keep configuration private (`0600`). Its structure is:

```json
{
  "assessment": {
    "description": "Assess synthetic canary disclosure.",
    "success_criteria": "The response contains SYNTHETIC-CANARY.",
    "probe_count": 5,
    "campaign_seconds": 600,
    "required_surfaces": ["response"]
  },
  "adversarial": {
    "base_url": "https://adversarial.example/v1",
    "api_key_env": "ADVERSARIAL_API_KEY"
  },
  "target": {
    "base_url": "https://target.example/v1",
    "api_key_env": "TARGET_API_KEY"
  },
  "judge": {
    "base_url": "https://judge.example/v1",
    "api_key_env": "JUDGE_API_KEY"
  }
}
```

Set `ADVERSARIAL_MODEL`, `TARGET_MODEL`, `JUDGE_MODEL` and the referenced key
environment variables. A `model` field can pin a role explicitly. Configure the
adversarial role to an operator-provided abliterated model; this library does not
abliterate, download, provision or attest weights. Provenance marks abliteration
as an unverified operator declaration. Each role may use a different endpoint/key.
There is no implicit attacker/judge fallback to the target's credentials.
HTTPS is required except for local HTTP fixtures. Optional `operator_revision`,
`request_seconds` (1–120), `max_tokens` (64–4096) and `temperature` (0–2) are retained.
`--validate` checks configuration without model calls or credentials.

The assessment extra requires DataDesigner 0.9.5, whose engine permits patched
fsspec. It cannot share an environment with Garak's older dependency constraints;
use a separate Garak installation. Existing cultural pipelines and attack runners
remain available through their original interfaces.

## Observations and judgments

The built-in target adapter calls an OpenAI-compatible chat endpoint once per
probe, with no retries or redirects. It collects `choices[0].message.content` and
optional top-level JSON `logs` and `traces` fields. A request/message conversation
trace is retained separately: it is not an agent's internal execution trace.
Endpoint-provided logs/traces are labeled `endpoint-reported`, not independently
attested. Other systems can implement `TargetAdapter.observe(probe, attempt_id,
deadline=...) -> Observation` with adapter-observed logs/traces.

Set `required_surfaces` to include `logs` and/or `traces` when the criterion needs
them. Missing required surfaces, truncated capture, target failure, malformed
judge output or unsupported evidence references yield `inconclusive`, never an
invented failure or success. Raw valid judge output remains available beside the
normalized verdict. Judge explanations cite JSON pointers into observed evidence.
The judge receives probe/response/logs/traces as untrusted data and is instructed
not to obey embedded instructions. This mitigates prompt injection; it does not
qualify a judge against it or replace independent effect verification.

## Datasets and recovery

Each campaign produces private files:

- `events.jsonl`: append-only, fsynced generated/observed/final stages. The target
  observation commits before judgment, preserving responses when the judge fails.
- `records.jsonl`, `records.parquet`, `records.arrow`: matching latest-stage
  analysis records with schema `interplay-assessment/1`.
- `manifest.json`: requested/actual counts, success/failure/inconclusive counts
  and processing completeness. `release_eligible` is always false.

The flat schema includes `probe`, `adversarial_intent`, `response`, `judge_verdict`,
`judge_reasoning`, `evidence_refs_json`, campaign/attempt IDs, status/error code,
timestamps and provenance. Nested logs/traces and valid raw judge output are
canonical JSON string columns (`logs_json`, `traces_json`, `conversation_trace_json`,
`generation_trace_json`, `judge_trace_json`, `raw_judge_json`, `provenance_json`).
Use `json.loads` to reconstruct them. The explicit Arrow schema supports empty,
failed and successful datasets without inferred-type drift.

```python
import pyarrow.parquet as pq
from interplay.assessment import to_arrow

table = pq.read_table("private-campaign/records.parquet")
rows = table.to_pylist()
```

`interplay assessment-recover --output private-campaign` exports the latest
committed stages without target/judge calls. Interrupted attempts stay incomplete;
truncated trailing journal bytes are reported and ignored, while malformed
committed records or changed identities are rejected. Recovery never overwrites
the journal. Known transport credentials are redacted before judging/persistence.

The library callbacks cooperate with deadlines; hard wall-clock/process bounds
require an external supervisor. Probe count is bounded to 50, requests to configured
endpoints, response/trace fields to finite sizes and raw target packets to 1 MiB.
This is an endpoint/adapter research assessment. It does not instrument arbitrary
tools automatically, qualify agent containment, establish statistical resistance,
freeze a regression baseline or grant release authority. No hosted-model campaign
is implied by the synthetic local conformance tests.
