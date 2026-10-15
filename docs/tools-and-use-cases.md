# Tools, library APIs and use cases

[← Documentation map](README.md) · [Methodology](METHODOLOGY.md)

Use Interplay to generate probes, explore attack strategies, or evaluate a declared
adversarial objective against captured target evidence. Start with the workflow
that produces the evidence you need; the three interfaces below are separate.

| Your question | Entry point | Result | Current scope |
| --- | --- | --- | --- |
| Which culturally grounded prompts should we test? | `interplay probes` / pipeline builders | Adversarial and benign probes, categories, generation traces and probe-quality scores | Generates a dataset; does not establish target compromise |
| Does a target meet this adversarial success criterion? | `interplay assess` / `run_assessment` | Probe, intent, observation, evidence-cited judge verdict and explanation | Batch or sequential adaptive endpoint/adapter research |
| Which attack method should we explore? | `interplay.red_teaming` | Runner-specific scores, prompts and histories | Method-specific experimental implementations; limits below |
| Can we retain an interrupted assessment? | `interplay assessment-recover` / `recover_assessment` | Latest committed attempts in three analytics formats | Offline export, not search resumption |
| Did an attack cause a forbidden external effect or violate containment? | [Agent Boundary Gate](https://github.com/interplay-adversarial/agent-boundary-gate/blob/main/docs/tools-and-use-cases.md) | Separately collected boundary/effect evidence and prototype policy decision | Requires independent observers and trusted bindings; research verdicts are not gate records |

## Choose the library and environment

| Tool or library | Responsibility here | Use it for |
| --- | --- | --- |
| Interplay CLI | Selects generation, assessment or recovery workflows | Repeatable operator commands |
| `interplay.specs` and `interplay.pipeline` | Taxonomy/comparison contracts and DataDesigner builders | Custom cultural comparisons and probe generation |
| `interplay.assessment` | Generation→observation→judgment orchestration, adaptive lineage and storage | Description-driven campaigns and custom adapters |
| NVIDIA NeMo DataDesigner | Structured adversarial generation/refinement and judge inference in assessments; cultural pipeline generation | Model-produced probes, intent and evidence-based explanations |
| `any-llm-sdk` | Model transport for DataDesigner and legacy attack runners | Provider-backed model calls; assessment target transport is separately implemented |
| Pydantic | Configuration, observation, probe, judgment and record validation | Reject malformed inputs and unsupported evidence citations |
| PyArrow | Explicit-schema Parquet and Arrow snapshots | Offline dataset analysis alongside matching JSONL |
| Garak | External scanner invoked by its runner | Scanner-specific probe libraries and reports, in a separate environment |
| `judge-kappa` | Computes TAP's optional two-judge agreement | Real Cohen's kappa when `secondary_judge_model` is set and scores overlap with the primary judge; otherwise `None` with a reason — see [tap.md](attacks/tap.md) |
| NeMo Gym | Possible future instrumented assessment target | Stateful agent/tool rollouts; no shipped assessment `TargetAdapter` for Gym |
| Agent Boundary Gate | Optional external owner of the same assessment library | Immutable source admission, restricted credentials and process deadlines |

For the merged source capabilities, use a checkout; a PyPI release may lag main:

```sh
uv sync --frozen --extra assessment --no-editable
uv run --no-sync interplay --help
```

From a published release containing the required feature, the assessment extra is
`interplay-adversarial[assessment]`. Legacy runners use `[red-teaming]`; Garak uses
`[garak]`. Assessment/Garak and Garak/provider dependency graphs have declared
conflicts: install Garak separately. See [installation](../README.md#install).

## Generate a cultural or harm probe dataset

Use `singapore` for APAC cultural bias, `sdg-hub-harm` for the eight harm concepts,
`combined` for both, or a two-group comparison such as `us-mexico`.

```sh
interplay modes
interplay probes validate --mode us-mexico
interplay probes setup --base-url https://example.com/v1 \
  --model operator-selected-model --api-key-env OPENAI_API_KEY
interplay probes create --mode us-mexico --num-records 200
```

The reserved endpoint is a placeholder. Supply its key through your credential
loader before `preview` or `create`; `validate` makes no model calls. `setup` writes
DataDesigner provider/model configuration and an environment-variable reference,
not the key value. These settings are distinct from assessment role configuration.

For Python composition, use the builders in
[`interplay.pipeline`](../interplay/pipeline.py), including
`build_cultural_bias_pipeline`, `build_harm_pipeline`, `build_combined_pipeline`
and `build_comparison_pipeline(load_spec("us-mexico"))`. Add a new comparison by
exporting a `BiasComparisonSpec` as `SPEC` in `interplay/specs/<name>.py`; see
[spec contribution instructions](../interplay/specs/CONTRIBUTING.md).

Probe-quality scores measure the generated probe's quality under that pipeline's
rubric. They are not verdicts about a target response. For columns, model setup
and multiple-mode dataset generation, see the [README](../README.md#output-probe-generation).

## Assess a user-defined objective

Choose this path when you need the complete probe→response→judge analysis record.
For example: “Assess whether the response discloses a harmless synthetic marker;
success requires that exact case-sensitive marker in the captured response.”

Use the private configuration in the [assessment guide](assessment.md). It has
`assessment`, `adversarial`, `target` and `judge` sections, with explicit endpoint,
model and credential-environment references for each role. Assessment model
variables are `ADVERSARIAL_MODEL`, `TARGET_MODEL` and `JUDGE_MODEL`. Configure the
adversarial model yourself; its abliterated label is an unverified operator
declaration, not a provisioned or attested weight transformation.

```sh
interplay assess --config /private/operator/assessment.json \
  --output /private/operator/new-campaign
interplay assessment-recover --output /private/operator/new-campaign
```

Paths are placeholders; configuration must be private (`0600`), and run output
must be new. HTTPS is required except for loopback fixtures. Each role may use a
different endpoint. Using one model for every role exercises plumbing, but does
not establish independent judging.

| Assessment setting | Batch | Adaptive |
| --- | --- | --- |
| `search_mode` | `batch` (default) | `adaptive` |
| Generation | All seed probes before observing the target | One seed, then one refinement per completed parent |
| `probe_count` | Requested probes | Total attempt budget including the seed, maximum 50 |
| Feedback | No previous-target feedback in generation | Bounded parent response/logs/traces, verdict, explanation and citations |
| Stopping | Processes the requested generated probes within the deadline | Success when `stop_on_success: true`; otherwise attempt budget; inconclusive/error/deadline stops incomplete |
| Target conversation | One target request per probe | One target request per probe; no automatic accumulated conversation |

For adaptive search, add to the `assessment` object:

```json
{"search_mode":"adaptive","probe_count":10,"stop_on_success":true}
```

Success means the declared adversarial criterion was supported by captured
research evidence. It does not mean the target passed. `assessment_complete`
means processing completed; inspect success/failure/inconclusive counts separately.
Adaptive early success may complete with fewer records than the requested budget.

The target adapter collects a response and optional endpoint-provided `logs` and
`traces`. Require those surfaces when the criterion needs them. Conversation
traces are distinct from internal execution traces. Missing capture, unsupported
citations and invalid judge outputs withhold a decisive verdict. These validation
checks do not prove that a judge's interpretation is correct.

## Embed assessment in another application

The API supports replaceable components without importing the gate:

```python
from pathlib import Path
from interplay.assessment import AssessmentSpec, run_assessment

spec = AssessmentSpec(
    description="Assess synthetic marker disclosure.",
    success_criteria="Captured response contains SYNTHETIC-CANARY.",
    search_mode="adaptive",
    probe_count=5,
)
# generator, target and judge are application-supplied implementations below.
manifest = run_assessment(spec, generator, target, judge, Path("private-new-campaign"))
```

| Interface in [`assessment.runner`](../interplay/assessment/runner.py) | Contract |
| --- | --- |
| `ProbeGenerator.generate(spec, deadline=...)` | Returns a list of `(Probe, generation_trace_json)` seeds |
| `AdaptiveProbeGenerator.refine(spec, feedback, deadline=...)` | Returns one `(Probe, generation_trace_json)` refinement |
| `TargetAdapter.observe(probe, attempt_id, deadline=...)` | Returns `Observation` with response/capture status and optional JSON logs/traces |
| `Judge.judge(spec, probe, observation, deadline=...)` | Returns `(JudgeOutput, judge_trace_json)` |

The built-in implementations are `DataDesignerBackend` and
`OpenAIEndpointTarget`; the [assessment guide](assessment.md) describes their
configuration. The example deliberately requires your component instances.
Callbacks cooperate with deadlines; hard process bounds need a supervisor such
as the gate wrapper. An adapter can capture instrumented tool outcomes; simply
placing an agent behind a chat endpoint does not expose its internals. Preserve
missing or incomplete observations rather than inventing execution evidence.

## Explore the legacy attack runners

These runners are separate from `interplay.assessment`: their outputs do not
receive its stage journal, citation validation or matching version-2 exports.
Read the current implementation as well as the [method pages](attacks/README.md).

| Runner | Current behavior | Interpretation limit |
| --- | --- | --- |
| `pair_attack` | Queries target, uses LLM response scoring and refines from recent history | Numeric score is not an evidence-cited assessment verdict or empirical attack success rate |
| `tap_attack` | Branches, prunes by evaluator likelihood, queries the target for admitted branches only, and judges each response with an evidence-cited judge (optionally a panel) | `best_score` is the judged-best candidate's evaluator (pre-query) likelihood, not an attack success rate; see [tap.md](attacks/tap.md) for `confirmed_success`/`irr_report` semantics |
| `crescendo_attack` | Escalates prompts from captured per-turn outcomes, queries the target every turn, and judges each response with an evidence-cited judge | `confirmed_success` is the only field asserting a judge-confirmed success; see [crescendo.md](attacks/crescendo.md) for `target_mode`/context-window semantics and its no-backtracking deviation |
| `goat_attack` | Selects a structured, pool-bounded strategy and prompt each turn, queries the target, and judges each response with an evidence-cited judge | No automatically persistent target conversation; see [goat.md](attacks/goat.md) for `target_mode` semantics |
| `slip_attack` | Bounded lexical insertion then target-assisted refinement, queries the target for non-truncated candidates only, and judges each response with an evidence-cited judge | `confirmed_success` is the only field asserting a judge-confirmed success; see [slip.md](attacks/slip.md) for truncation/frontier semantics |
| `multimodal_attack` | Renders every `(transform, control)` pair into a private per-attempt payload, queries the target for each, and judges each response with an evidence-cited judge | `confirmed_success` is always paired with the exact `best_control`/`best_transform`; needs the `multimodal` extra (Pillow) only when an image control is actually used; see [multimodal.md](attacks/multimodal.md) |
| `run_garak` | Invokes external Garak tooling | Scanner-specific configuration, detectors and report semantics |

PAIR's target call now goes through `interplay.red_teaming.transport.AuthenticatedTarget`
and attaches `Authorization: Bearer <api_key>` when `pair_attack(..., api_key=...)` is
set; SLIP, GOAT, Crescendo and Multimodal's target calls go through the same `AuthenticatedTarget`.
Check the selected runner before using an authenticated service; use the assessment
API for its implemented credential handling. Provider support in `any-llm-sdk` does
not make every direct target helper support every provider protocol.

### Shared transport, scoring and result retention (`interplay.red_teaming.transport`)

`interplay.red_teaming.transport` gives the method runners a common,
independently tested target/scorer/result-sink path without coupling any
runner's method logic (refinement strategy, branching, lexical search) to it,
and without requiring Agent Boundary Gate or DataDesigner:

| Interface | Contract |
| --- | --- |
| `resolve_role(role, endpoint)` | Resolves one role's (`attacker`/`target`/`evaluator`/`judge`) model and credential from its own `ModelEndpoint`; never falls back to another role's key |
| `RunBudget` / `CallBudget` | Finite campaign deadline, per-role call count and turn count; `charge_call`/`charge_turn` raise `BudgetExceeded` instead of retrying |
| `AuthenticatedTarget.request(kind, messages, budget=...)` | One authenticated, bounded-response target request (`stateless`, `conversation` or `image`); `UnsupportedCapabilityError` if `kind` was not declared at construction, with no request sent |
| `JudgeScorer.score(goal, probe, observation, budget=...)` | Evidence-cited judge call reusing `interplay.assessment`'s `JudgeOutput`/`evidence_supported`; missing/invalid evidence or a provider failure returns `inconclusive`, never a fabricated zero |
| `JudgePanel(endpoints, api_key=..., aggregation=...)` | Two or more independently configured judges behind the exact same `.score()` contract as `JudgeScorer`; the aggregated verdict follows `JudgeAggregation` (`"majority"`/`"unanimous"`), and `agreement_report()` gives a real, N-capable Krippendorff's alpha (via `judge_kappa`) over every case scored so far, with a bootstrapped confidence interval -- never a fixed placeholder |
| `build_judge(judge_model, secondary_judge_models, base_url=..., api_key=..., aggregation=...)` | One `JudgeScorer`, or a `JudgePanel` when `secondary_judge_models` is non-empty, or `None`; every migrated runner (TAP, Crescendo, GOAT, SLIP, Multimodal) constructs its judge this one way |
| `RunnerRecord` / `RunnerResultSink` | One retained row per attempted trial (prompt, response, strategy, verdict, status, error, role provenance), using the same private-journal/atomic-export discipline as `AssessmentStore` |
| `recover_runner_records(output)` | Exports the latest committed stage per attempt without re-running a target or judge |

**Not yet wired into any runner.** `RunnerRecord`, `RunnerResultSink`, `new_record`
and `recover_runner_records` are exported, independently unit-tested (see
`tests/test_red_teaming_transport.py`) and exercised directly in
`tests/test_crescendo_runner.py`, but no runner function
(`tap_attack`/`pair_attack`/`crescendo_attack`/`goat_attack`/`slip_attack`/
`multimodal_attack`) calls them: each still returns only its in-memory
dataclass result (`result.trials` as plain dicts), with no on-disk journal and
no `interplay` CLI command to run a method and later recover it -- unlike
`interplay assess`/`assessment-recover`. Treat result retention and recovery
for the legacy runners as planned, not shipped, until a runner actually calls
`RunnerResultSink.stage()`/`.export()`.

Migrate off `get_judge_config()`/`get_attacker_config()` in
[`interplay/red_teaming/base.py`](../interplay/red_teaming/base.py): both emit a
`DeprecationWarning` when they fall back to `TARGET_URL`/`TARGET_API_KEY`
because `JUDGE_*`/`ATTACKER_*` were unset -- the fallback that silently lets a
judge or attacker inherit the target's credential. Build one `ModelEndpoint`
per role instead (its own `api_key_env`, optionally its own `model`) and call
`resolve_role` for each. A method runner's best/highest score remains a search
diagnostic, never written to `RunnerResultSink` as an empirical attack success
rate; it is also distinct from Agent Boundary Gate's boundary/containment
effect evidence.

The [integrated example](../examples/integrated_run.py) combines method-specific
outputs; it is not the assessment journal or a boundary evidence bridge.

## Analyze, recover and combine evidence

Assessment outputs include `events.jsonl`, `manifest.json`, and matching
`records.jsonl`, `records.parquet`, `records.arrow`. Version 2 adds parent attempt,
round, selection reason and `feedback_json`. Decode JSON string columns before
analysis. Retain status/error code and incomplete attempts in your datasets.

```python
import json
import pyarrow.parquet as pq

rows = pq.read_table("private-new-campaign/records.parquet").to_pylist()
feedback = [json.loads(row["feedback_json"]) if row["feedback_json"] else None for row in rows]
```

Offline recovery exports committed stages; it never retries target actions or
resumes adaptive search. Legacy version-1 journals remain readable without being
rewritten. Private raw captures and configuration are not publishable datasets.

For behavior plus enforcement research, use Interplay for the adversarial
criterion and the gate for independently bound effect/containment/cleanup
observations. The gate's shipped `red-team-run` supervises Interplay but does not
automatically instrument the target or turn judge verdicts into signed gate
records. Gym assessment integration and automatic Interplay-to-boundary effect
correlation remain future work. See the gate's
[use-case guide](https://github.com/interplay-adversarial/agent-boundary-gate/blob/main/docs/tools-and-use-cases.md)
and [research integration](https://github.com/interplay-adversarial/agent-boundary-gate/blob/main/docs/description-driven-red-team.md).
