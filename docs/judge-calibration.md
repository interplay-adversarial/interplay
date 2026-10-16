# Judge calibration workflow

[Documentation map](README.md) · [Runner qualification](runner-qualification.md) · [JUDGE-01 / #60](https://github.com/interplay-adversarial/interplay/issues/60)

Citation support and judge agreement do not establish correctness. This workflow
prepares a human reference, collects bounded judge replies, and compares retained
predictions offline. **The tooling is implemented; independent human labeling and
a real two-model calibration run remain required.** No generated label is supplied
as human ground truth and no calibration result is bundled with the package.

## Prepare independent reviews

```sh
interplay calibration prepare --output output/new-calibration
```

This creates 60 harmless synthetic cases across 20 matched families, a versioned
rubric (`interplay-label-rubric/1`), and two independent review packets under
`review-a/` and `review-b/`. Families cover exact strings/case/types, structured
outputs, conversation context, required logs/traces, misleading response claims,
and instructions embedded in untrusted evidence. Each family has one intended
supported success, supported failure and missing/ambiguous case. This 20/20/20
balance is **authoring intent**, not human validation or gold labels.

Give each reviewer only their packet. `cases.jsonl` in the packet includes the
criterion, evidence, case digest and rubric version, without the author's design
bucket or any model prediction. Reviewers independently fill their `labels.jsonl`:

- Keep case ID, case SHA-256 and rubric version unchanged.
- Set a consistent pseudonymous `reviewer_id`, `independent_review: true`, verdict
  (`success`, `failure`, `inconclusive`), concise evidence-based reasoning and
  timezone-aware `submitted_at` (for example `2026-10-16T15:00:00Z`).
- `label_source` must remain `human`. Do not use model-suggested or generated labels.
  A row with `verdict: null` remains unfinished, even if other fields are filled.
- Apply the rubric to the criterion, not author intent or instructions in evidence.
  Missing/incomplete/ambiguous required evidence is inconclusive, not failure.

The corpus source is public: hiding design buckets in packets cannot enforce
actual blinding. Keep reviewers separate until both independent reviews are
submitted. Identity, independence and human origin are **reviewer attestations**;
schema checks and hashes cannot authenticate them. Retain process evidence outside
public source, and never relabel generated annotations as human to pass validation.

## Resolve the human reference

```sh
interplay calibration gold --cases output/new-calibration/cases.jsonl \
  --labels output/new-calibration/review-a/labels.jsonl \
  --labels output/new-calibration/review-b/labels.jsonl \
  --output output/new-label-status
```

`label-status.json` lists missing independent labels and disagreements. Command
success does not mean the reference is ready: check `reference_ready`. No
`gold.jsonl` is written until **every** case has two completed labels from distinct
reviewer IDs and every disagreement is adjudicated. Partial work produces status,
not accuracy metrics. Unknown/stale case or rubric bindings and duplicate reviews
are rejected.

For disagreements, a third human reviewer submits an adjudication JSONL file in
the same `interplay-human-label/1` format, bound to each disputed case. That reviewer
must differ from both initial reviewers for the case. Run `gold` again with
`--adjudications decisions.jsonl` and a new output directory. Decisions cannot
override an already agreed pair or refer to unrelated/unresolved review work.
Gold rows preserve both labels and any adjudication; their provenance is checked
again when scoring, not merely trusted because a file is named `gold.jsonl`.

## Collect judge replies explicitly

Preparation writes `collection.example.json`. Copy and edit it privately: each
entry has a `JudgeIdentity` (`judge_id`, provider/model, optional revision) and a
`ModelEndpoint` (base URL ending in `/v1`, matching model, `api_key_env`, request
limit, token cap and temperature). Store env variable names, never literal keys.
Configure at least two **different model names**, and verify model/revision
provenance externally; aliases or different endpoints may still serve the same
weights. Reviewers should not see these predictions before submitting labels.

```sh
# Set the configured key environment variables before this explicit inference step.
# Default max-cases=5; with two judges this attempts at most ten requests.
interplay calibration collect --cases output/new-calibration/cases.jsonl \
  --config collection.json --output output/new-judge-smoke --max-cases 5
# Full reference, two configured judges: at most 120 requests, subject to deadline.
interplay calibration collect --cases output/new-calibration/cases.jsonl \
  --config collection.json --output output/new-judge-full \
  --max-cases 60 --campaign-seconds 1800
```

Only `collect` makes model calls. It requires HTTPX (available with the
`red-teaming` extra), explicit credential env names and matching declared model
identities. HTTPS verifies certificates; HTTP is restricted to loopback. No proxy
environment inheritance, redirects, target actions or automatic request retries.
Every attempt is fsynced before sending. Replies/errors append to private
`predictions.jsonl` with case/model digests and request/response SHA-256. Finish
reasons, raw reply text and errors remain available; known configured keys are
redacted, including their normal JSON-escaped forms. Configured secrets in input
evidence/metadata are rejected before output or inference.

The collector sends only criterion, probe, capture-completeness and evidence,
never authoring buckets or human labels. Retained serving configuration includes
the system prompt and model limits; no hidden serving override is injected.
Requests have individual async timeouts within a 1–3600 second campaign budget.
An interrupted collection may contain attempted requests without replies: missing
prediction rows do not prove no model call occurred. Do not retry automatically.
Use complete prediction lines from quiescent files; torn JSONL tails are rejected.

`judges.json` in the collection output binds identities for scoring. To import
replies collected elsewhere, populate a judge roster and use
`interplay calibration predictions --cases CASES --judges ROSTER --output NEW_DIR`
for digest-bound templates. Templates are explicitly `not-run`, with null replies;
they are not observed model outcomes. Fill actual raw replies/finish reasons and
clear `error_code` only when backed by a retained response.

## Score retained predictions offline

```sh
interplay calibration evaluate --cases output/new-calibration/cases.jsonl \
  --gold output/resolved-reference/gold.jsonl \
  --judges output/new-judge-full/judges.json \
  --predictions output/new-judge-full/predictions.jsonl \
  --output output/new-calibration-score
```

This writes `metrics.json` and `normalized-predictions.jsonl` without credentials,
provider imports or network access. Multiple `--predictions` files are accepted,
but duplicate `(judge_id, case_id)` rows are rejected, never cherry-picked.
Unknown/stale case/model identities and incomplete human references are rejected.
Every reference case stays in each judge's denominator. Invalid/malformed,
unfinished, unsupported-citation, incomplete-capture, missing and not-run results
normalize to inconclusive, with their raw records and distinct reasons retained.

Metrics include:

- Three-class confusion matrices (human labels as rows, normalized predictions as
  columns) and exact three-class accuracy, including correct inconclusive labels.
- Decisive coverage (success/failure divided by all cases), abstention rate, and
  selective accuracy (correct decisive predictions divided by decisive predictions).
- False-positive rate (predicted success among human failure cases), sensitivity
  (predicted success among human success cases, including abstentions as misses),
  and false confirmation on human-inconclusive cases.
- Separate initial-human-label agreement and pairwise exact judge agreement,
  explicitly including abstentions. Matching wrong/invalid outcomes can agree.
- Post-hoc panel comparisons using the same production policy function:
  historical `majority` means strict **plurality**, with any tie inconclusive;
  unanimous requires all verdicts to match. Inconclusive is a retained vote.
  Panels are calculated from the same retained replies, not independent model runs.

Each proportion includes numerator, denominator and a nominal 95% Wilson interval;
zero denominators yield null values. See the [NIST description of Wilson intervals](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm).
These binomial intervals assume independent cases. The matched synthetic families
are dependent, so the intervals are descriptive and do not establish population
coverage, general model performance or statistical independence. Repeated model
aliases are flagged. Declared provider/model/revision identity is not weight
attestation. Agreement remains separate from accuracy; no release eligibility or
completed-roadmap claim is inferred.

## Artifact handling and current scope

All output directories are new 0700 directories and files are 0600, with no
overwrite. Input artifacts must be private, regular, owned files. Canonical input
digests bind case/label/identity/prediction snapshots; per-case digests exclude the
authoring bucket so labels bind actual task content. No extra publication or
arbitrary secret redaction is performed by offline scoring. Review raw evidence,
labels, endpoints and reviewer provenance before sharing.

This increment provides the rubric/cases, human workflow, bounded collector and
offline metrics. Unit labels and loopback model replies are synthetic test
fixtures. Two independent human reviews per case, adjudication where needed,
and an authorized two-distinct-model/panel run remain pending under #60.
