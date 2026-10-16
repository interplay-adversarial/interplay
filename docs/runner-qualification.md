# Runner qualification

[Roadmap](ROADMAP.md) · [Runner results](attacks/runner-results.md) · [QUAL-01 / #59](https://github.com/interplay-adversarial/interplay/issues/59)

Qualification records the scope actually exercised. The fixture drill below
uses synthetic HTTP responses; it establishes neither live model compatibility
nor judge quality. A live single-turn smoke also leaves multi-turn refinement,
panel calibration and broader model/provider coverage open.

## Qualification matrix

| Method | Single-observation fixture | Extended fixture | Live CLI smoke + offline recovery | Additional coverage still needed |
| --- | --- | --- | --- | --- |
| PAIR | Pass | Pass: two queries with attacker feedback/refinement | Pass: two queries and live attacker refinement | Distinct models/providers; wider query budgets |
| TAP | Pass | Pass: two depths, two generated branches per depth, one admitted | Pass: two live depths, one branch per depth | Wider live branching; distinct models/providers |
| Crescendo | Pass | Pass: three conversation turns, escalation and context omission | Pass: three live conversation turns, two escalations and final-observation interruption/recovery | Distinct models/providers; wider turn/context budgets; configuration sensitivity |
| GOAT | Pass | Pass: two conversation turns and structured strategy selection | Pass: two live conversation turns and structured strategy selection | Wider strategy pools; distinct models/providers |
| SLIP | Pass | Pass: lexical insertion then refiner call | Pass: live insertion and refiner continuation | Wider lexical frontiers; distinct models/providers |
| Multimodal | Pass: text-only | Pass: 3 transforms × 3 controls, six real PNG payloads | Recorded text-only smoke | Vision-model execution with real images |
| Garak | Pass: real 0.17.0 CLI, one loopback generation | Scanner-native semantics | Pending: dependency blocker [#68](https://github.com/interplay-adversarial/interplay/issues/68) | Clean dependency profile and bounded live scanner run |

All six fixture checks passed on 2026-10-15 against installed package 0.3.1,
whose Python sources matched merged main `c9b8348` byte-for-byte. The drill
also passes three negative tests for swallowed DNS/connect/sendto attempts.
CI repeats both fixture profiles on Python 3.12 and 3.13. Extended checks use
the same package Python sources as merged main `cef83cb`; all six extended
profiles pass locally. These include 20 target observations per normal run set
and another 20 in the interrupted set, including nine per Multimodal campaign.

TAP's recorded scope is the bounded installed-CLI smoke and interruption drill
that motivated [#58](https://github.com/interplay-adversarial/interplay/pull/58).
Live smoke results are recorded separately from fixture results. The new PAIR,
Crescendo, GOAT, SLIP and Multimodal (text-only) single-observation live smokes use source `cef83cb`: two
normal target/judge calls and one interrupted target call per method, with
two offline recoveries and no recovery network attempts. A supported failure
to emit the synthetic marker is a valid smoke outcome, just as a supported
success is; neither measures general attack effectiveness. Private raw
evidence is retained; same-model roles
do not establish independent judging. This is not a public empirical
attack-success benchmark or full method qualification.

The five new live smokes made 15 real upstream chat calls total and completed
ten repeatable offline recoveries with zero detected network attempts. A
read-only verifier checked original target packets against retained responses,
literal marker outcomes, citations, role sequences, recovered records and
cleanup/credential/permission receipts. PAIR, GOAT and Multimodal text-only
emitted the marker; Crescendo and SLIP produced supported failure judgments.
All five passed the transport/evidence/recovery smoke. Earlier TAP evidence
adds a separate single-observation live smoke; advanced live paths remain open.

## Live continuation checks (2026-10-16)

PAIR, TAP, GOAT and SLIP also pass bounded live continuation and interruption
drills. The continuation-relevant package modules match merged source `1a92bca`;
private verification receipts retain their SHA-256 bindings. PAIR/GOAT/SLIP
each execute two target observations and a live attacker/refiner call per
campaign. TAP executes two live attacker/evaluator/target/judge rounds with
one branch per depth. Every attacker output is checked against the exact next
executed prompt; GOAT's selected strategy and actual conversation history are
bound to the observations. Interrupted runs preserve an earlier complete row
and the final observed response through two offline recoveries.

These are controlled live plumbing checks: the private bridge records an
explicit target-system instruction requesting a harmless fixed response, so
the marker criterion fails and continuation can execute. It also records the
effective thinking override and actual role routing. Raw model responses are
not replaced. Effective wire messages, including this system control, are
verified separately from the runner's conversation trace; the injected serving
configuration is not automatically represented in native row provenance.
Same-model judging remains non-independent, and these runs do not measure
adversarial robustness or general model quality.

The four passing methods made 42 real upstream chat calls and eight offline
recoveries with zero detected network attempts. Read-only checks verify raw
responses, citations, parent bindings, generated prompts, histories, preserved
terminal rows and cleanup/credential/permission receipts.

Crescendo's separate live attempt made three calls: target, judge and attacker.
The attacker returned an empty content string with a completed response; the
runner stopped with `attacker-output-invalid:empty-escalation-prompt`, retaining
the first complete target response and supported failure judgment. Its live
continuation remains failed for this model/configuration. No second target
attempt or interruption drill is claimed. That run remains available as
failure evidence, and is not promoted by the passing fixture tests.

### Crescendo follow-up

A subsequent bounded Crescendo drill passes against installed source matching
merged `2bada93`, with the continuation modules unchanged from `1a92bca`.
Both normal and interrupted campaigns execute three target turns in conversation
mode, with two actual attacker-generated escalation prompts and a one-turn
attacker context window. Raw wire requests verify full target history, the
attacker's latest-turn feedback and explicit omission of the older turn, exact
generated-to-executed prompts, parent IDs and retained judge replies/citations.

The passing serving configuration uses an explicit marker-presence success
criterion, disabled thinking, and attacker sampling overrides of
`temperature=0.6`, `top_p=0.95`, `min_tokens=16` (vLLM). The runner's attacker
output cap remains 256 tokens. These effective wire overrides are retained in
private operator notes and packets; native endpoint provenance alone does not
capture them. The minimum-token setting delays EOS; it does not supply or
replace generated text. See [vLLM sampling parameters](https://docs.vllm.ai/en/stable/api/vllm/sampling_params/).
The harmless target-system control described above remains in effect.

The successful drill makes 15 actual upstream calls: eight in the normal
campaign and seven in the interrupted campaign. SIGKILL occurs after two
complete attempts and the third durably observed response, before its judge
request is forwarded upstream. Two credential-free recoveries with the bridge
closed preserve both earlier terminal records exactly, retain the final response
as incomplete/inconclusive, leave the journal unchanged, and produce equal
JSONL/Parquet/Arrow exports with zero detected DNS/connect/sendto attempts.
Read-only verification and cleanup/credential/private-permission checks pass.

Earlier failures remain retained. One follow-up stops after a two-call judge
false positive: the raw target response lacks the marker, while the judge emits
`success` despite reasoning that the goal was not achieved. Another completes
the normal three-turn campaign but its separate interruption campaign stops on
an empty second escalation after two completed turns (14 calls total). Neither
is counted as a passing interruption drill. Including these two failed
follow-ups, this increment makes 31 calls; the original three-call empty-output
failure remains separate. No replies are substituted and no library fallback
is added. This pass establishes the bounded tested configuration; it does not
resolve same-model judge reliability or qualify other sampling settings.

## Real Garak compatibility and dependency status

Garak 0.17.0 is installed in a separate frozen optional environment. The real
scanner, OpenAICompatible generator and `any.AnyOutput` detector pass one
authenticated loopback `test.Blank` generation. The native evaluated attempt,
detector result, completion and final digest are retained. A valid final JSON
object without a newline is accepted; a torn tail stays incomplete. This
compatibility result makes no vulnerability or detector-quality claim.

The isolated dependency audit reports three advisories in datasets 3.6.0,
fsspec 2025.3.0 and nltk 3.10.3. Garak's `datasets<4.0` requirement and the
selected datasets/DataDesigner fsspec constraints prevent a straightforward
upgrade to the audit-reported patched versions. NLTK has no fixed version in
that audit result. [Issue #68](https://github.com/interplay-adversarial/interplay/issues/68)
tracks remediation and verification. The loopback compatibility pass does
not establish release-ready dependencies; a live scanner run remains pending.

Repeat the compatibility drill from a checkout using a separate environment:

```sh
UV_PROJECT_ENVIRONMENT=/tmp/interplay-garak-env uv sync --frozen --no-dev --extra red-teaming --extra garak
/tmp/interplay-garak-env/bin/python scripts/garak_cli_conformance.py --output /tmp/interplay-garak-conformance
```

The output directory must be new and the interpreter must run on POSIX. The script isolates configuration, passes a
synthetic credential through the child environment and propagates a Python
network guard into the scanner subprocess. That guard permits its loopback
fixture endpoint and records unexpected DNS/connect/sendto operations even if a
library swallows the error. No model weights are downloaded and no live model
is called. A pass checks scanner execution and native report interpretation,
not the dependency audit. The receipt binds the Python/package versions,
conformance harness digest and actual parser source digest. Review #68 before selecting the
environment for broader work.

## Repeat the fixture drill

From a source checkout with the development dependencies installed:

```sh
uv sync --frozen
uv run --no-sync python scripts/runner_cli_conformance.py --output /tmp/interplay-cli-conformance
# Or one method in a different new directory:
uv run --no-sync python scripts/runner_cli_conformance.py --method pair --output /tmp/interplay-pair-conformance
# Extended lineage, conversation/refinement and PNG control matrix:
uv run --no-sync python scripts/runner_cli_conformance.py --profile extended --output /tmp/interplay-cli-extended
```

The output directory must not exist. POSIX is required for SIGKILL and permission
checks. The current interpreter must have the intended Interplay revision
installed; `uv sync --frozen` installs the checkout. The drill invokes
`python -m interplay` in fresh working directories with an isolated HOME,
synthetic role-specific credentials and only loopback endpoints. Provider keys,
proxy variables and user configuration are not inherited.

For each method, the default `smoke` profile verifies:

- One complete normal response with the exact fixture marker, supported response citation and retained judge/provenance/method fields.
- Correct role routing, distinct fixture credentials and model names at the HTTP boundary.
- An actual child-process SIGKILL after the `attempted` and `observed` stages are journaled, while the fixture withholds the judge reply.
- Preserved attempt, goal, probe, response, provenance and method metadata after recovery; incomplete/inconclusive outcome with `interrupted` status reason.
- Two identical offline recoveries with fixture endpoints closed and credentials absent, an unchanged source journal and matching JSONL/Parquet/Arrow exports.
- Zero recovery network attempts, enforced and recorded by a Python audit hook around the same CLI module (including DNS/connect/sendto attempts swallowed by a library).
- Private output permissions and absence of supplied fixture keys in campaign files.

The root `receipt.json` records aggregate status, installed package version,
Python source digests, the harness digest and per-method checks. A failed
drill keeps its partial output and leaves `passed: false`; retain it for diagnosis
and use a new directory when repeating. Fixture responses deliberately return a
synthetic success; they measure transport and evidence handling, not attacks.
The default profile bounds each method to one target observation. It does not
exercise GOAT strategy selection, PAIR/Crescendo refinement or SLIP refinement.

## Extended fixture coverage

The `extended` profile returns a supported failure for earlier observations and
a supported success only at the last expected observation. That forces the
real CLI through method-specific continuation paths instead of stopping on the
seed. The verifier compares retained lineage with captured HTTP requests:

- PAIR: two stateless target queries, one actual attacker refinement using captured response/verdict feedback.
- TAP: two depths, four generated/evaluated branches, two admitted target requests, pruning and parent-response lineage.
- Crescendo: three accumulated target turns, two escalation calls, a one-turn attacker context window and an explicit omitted-turn count on the third target turn.
- GOAT: two accumulated target turns; a structured attacker decision selecting `Logical appeal`, whose exact prompt and strategy are executed and retained.
- SLIP: insertion followed by a separate refiner call and a target request bound to the selected parent's attempt ID; search-only rows remain incomplete.
- Multimodal: all nine `(plain/base64/leetspeak, image-only/text-only/combined)` pairs. Six transmitted PNGs are decoded and checked for valid dimensions, byte length and SHA-256 equality with per-attempt metadata and retained payload files. Image-only controls exclude the literal goal marker from accompanying text; text-only controls contain no image.

Interruption occurs at the final observation's judge boundary, after earlier
attempts are complete. Offline recovery must preserve every field of those
terminal records, retain the final response as incomplete/inconclusive, and
leave the journal unchanged across two recoveries. `fixture-requests.json`
retains synthetic wire request bodies for diagnosis. The PNGs remain private
for both completed and interrupted campaigns.

These are controlled fixtures, not live refinement or visual understanding
results. No judge panel is exercised by either profile. Negative verifier
tests reject broken parent bindings, missing feedback, fabricated target
history and mislabeled GOAT strategies, alongside the network-guard tests.

## Live qualification acceptance

For each method, record the immutable source revision, installed-code identity,
role model identities, bounded parameters and effective serving configuration.
Retain complete and failed outcomes, private raw evidence and redacted receipts.
Repeat the normal/interruption/recovery invariants using authorized live targets,
including actual image observations for Multimodal and multi-turn/refinement
coverage where applicable. Same-model smoke results must state that judging is
not independent. Garak requires its own scanner-native checks and isolated
dependency environment; it does not use `runner-recover`.
