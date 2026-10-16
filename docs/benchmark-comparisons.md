# Reproducible model and configuration comparisons

[Documentation map](README.md) · [Roadmap BENCH-01](ROADMAP.md) · [Judge calibration](judge-calibration.md)

`interplay benchmark` freezes fixed probes, runs two explicit target configurations
under equal query caps, and writes paired descriptive comparisons. Install the
`red-teaming` extra for `run`; prepare, import, compare and recover work offline.
This first method is `fixed-probe`: adaptive attacker generation, image execution,
Garak native reports and independently instrumented agent effects are separate work.

A manifest binds the case-file bytes, goal/prompt/history digests, explicit model
and endpoint configurations, source revision, executing implementation digest,
repeats, request budgets and ordering. The Git revision is operator-declared; `run`
checks the implementation digest against the installed code. It does not prove
remote model weights or serving settings match an operator revision label.

## Prepare and run

Create a private JSONL case file (one object per line):

```json
{"case_id":"canary-a","goal":"Response contains CANARY-A exactly.","prompt":"Reply exactly CANARY-A."}
```

Optional `messages_json` holds a fixed chat history ending in the exact prompt.
Create `baseline.json` and `candidate.json` profiles:

```json
{"endpoint":{"base_url":"https://target.example/v1","model":"model-one","api_key_env":"BENCHMARK_API_KEY","request_seconds":30,"max_tokens":512,"temperature":0.0},"extra_body_json":"{}"}
```

Change the candidate's model or configuration as needed. Both targets must have
the same `max_tokens` and `request_seconds`. Optional `operator_revision` identifies
a serving/weight revision as declared by the operator. Permitted extra request keys
are `seed`, `top_p`, `min_tokens`, `chat_template_kwargs` and `stop`; reserved model,
message, streaming and multiple-completion overrides are rejected. Provider-specific
extras must be recorded here, including any chat-template override. No transport
adapter should silently change the request.

A shared judge profile uses the same format. It remains a model judgment; using the
same model as the target does not establish independent judging. Credentials must
be set in each explicitly named environment variable; ambient provider keys are not
used as fallback. Keep files private (`chmod 600`) and directories private (`chmod 700`).

```bash
interplay benchmark prepare --cases cases.jsonl \
  --baseline baseline.json --candidate candidate.json --judge judge.json \
  --suite-id canaries --source-revision FULL_GIT_COMMIT \
  --max-cases 2 --repeats 1 --campaign-seconds 120 --output prepared
interplay benchmark run --manifest prepared/manifest.json \
  --cases cases.jsonl --output run
interplay benchmark compare --manifest prepared/manifest.json \
  --cases cases.jsonl --records run/records.jsonl --output comparison
```

Every selected case/repeat permits one target request and at most one shared judge
request per variant, with no retries. Variant ordering alternates per case/repeat.
`--campaign-seconds` is a separate equal **cumulative request-time budget** for each
variant, shared between its target and judge calls. It is not a wall-clock process
limit; filesystem work adds time. Use an external supervisor if a total wall-clock
limit is required. No tools or actions returned by a model are executed.

The runner records request intent before dispatch, then fsyncs the actual target
response before judging. `target_calls`/`judge_calls` count committed client attempts,
which may include an interrupted dispatch; they are not provider billing counts.
Raw judge replies and request/response hashes are retained. Timeouts, truncated
captures, malformed judgments and unresolved citations remain inconclusive. A run
without a judge retains responses with inconclusive judgments.

## Imports and interrupted work

`import` reads assessment/runner v1/v2 JSONL, Parquet or Arrow snapshots, with an
explicit mapping JSON list:

```json
[{"case_id":"canary-a","repeat_index":0,"attempt_id":"0123456789abcdef0123456789abcdef"}]
```

```bash
interplay benchmark import --manifest prepared/manifest.json --cases cases.jsonl \
  --variant baseline --records legacy/records.jsonl --mapping mapping.json --output imported
```

The goal, prompt and fixed conversation must match exactly. Duplicate mappings and
changed digests are rejected. Native source records, export hashes and attempt IDs
are retained. Legacy exports cannot establish actual calls, latency, usage or budget
compliance; those measurements stay unavailable. Search scores are never converted
into success rates. Importing an adaptive runner's final observation does not establish
that its attacker search used the same resources as another configuration.

```bash
interplay benchmark recover --manifest prepared/manifest.json --cases cases.jsonl \
  --journal run/events.jsonl --output recovered
interplay benchmark compare --manifest prepared/manifest.json --cases cases.jsonl \
  --records recovered/records.jsonl --output partial-comparison
```

Recovery uses only committed full journal lines, preserves terminal records and
captured observations, and marks unfinished rows inconclusive/incomplete. It reports
an ignored torn trailing line. It creates a new output directory and never resumes
inference or changes the source journal. Missing planned rows remain in comparison
denominators. Outputs cannot overwrite an existing directory. Inputs/exports are
bounded (1,000 cases, 10 repeats, 128 MiB records/journal); an export-size stop is
recoverable offline.

## Read the comparison

`comparison.json` reports success/failure/inconclusive model-judgment counts,
complete/incomplete/not-run statuses, missing rows, call counts, measured target
latency and observed token/cost totals. `paired-cases.jsonl` retains both records,
response/verdict changes, and candidate-minus-baseline latency/call/token/cost deltas.
Provider usage fields are retained only when explicitly returned and valid. Cost
is accepted only from an explicit `usage.cost_usd`; it is never estimated from price
lists or tokens. Missing observations produce `null`, including aggregate totals
when a required component is unavailable.

These are descriptive paired observations. Citation resolution does not establish
semantic correctness; `accuracy` is always `null` pending independently reviewed
[JUDGE-01 calibration](judge-calibration.md). Sampling, serving state and ordering
can change replies even at temperature zero. Repeats are not independent samples;
no confidence interval, population improvement or release decision is inferred.
All artifacts contain private evidence and endpoint metadata; review before sharing.

Constructed HTTP fixture tests cover paired outcomes, resource availability,
input/source binding and interruption recovery. A [bounded installed-CLI live check](evidence/benchmark-live-20261016.json) on
2026-10-16 compared temperature 0.0 with 0.6 on the same self-hosted model: two
harmless marker cases, eight upstream chat requests, two success judgments per
variant, 444 observed total tokens per variant, and unavailable cost. Raw private
packets match every request/response digest and usage count. Offline comparison
ran with network/provider-import guards and no credentials; the tunnel was closed
and cleanup/privacy checks passed. The same-model judge is not independent; this
check does not establish accuracy or general robustness.
