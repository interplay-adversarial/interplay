# Description-driven research assessments

[← Documentation map](README.md) · [Methodology](METHODOLOGY.md)

Use [`interplay report`](campaign-reports.md) to inspect retained exports offline
as a private HTML report, including incomplete attempts and evidence references.

For workflow selection and dependency responsibilities, see the
[tools and use-case guide](tools-and-use-cases.md).

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
    "base_url": "https://example.com/target/v1",
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

The assessment extra requires DataDesigner 0.9.5 or later (below 0.11), whose engine
permits patched fsspec; CI and `uv.lock` run 0.10.0. DataDesigner 0.10 itself requires
Pillow 13, so an environment that pins Pillow below 13 must stay on DataDesigner 0.9.x.
It cannot share an environment with Garak's older dependency constraints;
use a separate Garak installation. Existing cultural pipelines and attack runners
remain available through their original interfaces.

## Request identity

Every request to the target, from `interplay assess` and from the method runners
(`runner-run`), carries a `User-Agent`. The default is `Interplay-Assessment/1.0`, so a
defender can write one stable rule for it. Before this setting the library default
(`python-httpx/<version>`) went out unrecorded.

Set `identity` on the **target** endpoint to change it. It is rejected on the adversarial
and judge roles, on runner attacker/evaluator/judge roles and in `interplay benchmark` and
`interplay calibration` endpoints, because none of those send target traffic.

```json
{ "target": { "base_url": "https://example.com/target/v1", "model": "target-model",
    "identity": { "mode": "declared", "user_agent": "Interplay-Assessment/1.0 (engagement=EX-42)" } } }
```

```json
{ "target": { "base_url": "https://example.com/target/v1", "model": "target-model",
    "identity": { "mode": "browser-pool", "id": "detection-check-1", "entry": "chrome-windows" } } }
```

`browser-pool` takes its `User-Agent` and the companion headers that a real browser of
that family sends (`Accept-Language` and, for Chromium browsers, the matching `sec-ch-ua*`
set) from the named pool `browser-ua-pool/1`. Pin one with `entry`, or pass a `seed` to
select one reproducibly; with neither, the profile `id` is the seed. The same profile
always resolves to the same entry, so a replayed campaign sends the same identity.

Use the browser pool to check whether a detection depends on the client label instead of
on behavior: run the same campaign with `declared` and `browser-pool` and compare what the
defender saw. Use it only against systems you are authorized to test.

What does not change:

- The label is never an authorization input. A target that allows or blocks traffic by
  `User-Agent` has not authorized anything, and the label proves nothing about who sent it.
- Only `User-Agent` and the fixed companion headers of the chosen entry are added.
  `Authorization`, `Content-Type`, `Accept-Encoding` and the other protocol headers are
  never configurable and are applied last.
- The pool holds generic browser families only, no crawlers, vendor agents or named
  services. It is a frozen snapshot and does not claim to track current browser releases.
  A refreshed pool is published as a new name (`browser-ua-pool/2`), never edited in place.

Known limits: requests still send `Accept-Encoding: identity`, so a defender keying on
that difference from a real browser still sees it; selection is per profile, not per
request or per session; and adversary and judge model calls made through Data Designer or
the judge scorer are not covered.

The identity that was actually sent is retained: `provenance_json` carries
`target_identity` (assessments) and `role_provenance_json` carries `identity` under the
`target` role (runners), each with the profile, pool entry and full header set.

## Observations and judgments

The built-in target adapter calls an OpenAI-compatible chat endpoint once per
probe, with no retries or redirects. It collects `choices[0].message.content` and
optional top-level JSON `logs` and `traces` fields. A request/message conversation
trace is retained separately: it is not an agent's internal execution trace.
Endpoint-provided logs/traces are labeled `endpoint-reported`, not independently
attested. Other systems can implement `TargetAdapter.observe(probe, attempt_id,
deadline=...) -> Observation` with adapter-observed logs/traces. The optional
[NeMo Gym target](nemo-gym-target.md) captures native SimpleAgent tool activity and
a separately observed environment outcome through this Python interface.

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
  analysis records with schema `interplay-assessment/2`.
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

## Adaptive feedback search

Batch generation remains the default. Enable bounded sequential refinement in
`assessment` configuration:

```json
{
  "search_mode": "adaptive",
  "probe_count": 10,
  "stop_on_success": true
}
```

In adaptive mode, `probe_count` is the total attempt budget, including the initial
seed. DataDesigner generates one seed, the target executes it, and the judge
validates its captured evidence. After a supported failure, DataDesigner receives
a bounded projection of the committed response, logs/traces, verdict, explanation
and citations to generate the next candidate. Set `stop_on_success: false` to
continue refining after supported success until the budget is spent. There is one
chain, no beam ranking or parallel branches; each target call uses a fresh probe,
not an automatically accumulated target conversation.

The manifest reports `search_mode` and `stop_reason`. A supported success can stop
early with `assessment_complete: true`; `requested_probes` remains the maximum
budget while `records` reports actual attempts. Budget exhaustion means processing
completed, not that an attack succeeded. Inconclusive judgment, missing required
evidence, incomplete capture, generation failure or deadline exhaustion withholds
completion and stops adaptive refinement. A failed target action is never retried.

Schema `interplay-assessment/2` adds `round_index`, `parent_attempt_id`,
`selection_reason` and `feedback_json` to each row. The feedback column records
exactly the projection supplied to refinement, with `truncated_fields` identifying
excerpts. Embedded feedback is untrusted model input; it provides no independent
execution or containment attestation. Each final parent stage commits before its
child is generated. Recovery exports committed lineage without resuming search or
making model calls, and still reads legacy version-1 journals without changing them.

The reusable target interface can support a future NeMo Gym adapter for stateful
agent rollouts and verifier observations. Gym is not a dependency of this search
loop, and that assessment target adapter remains unimplemented.
