# Runner qualification

[Roadmap](ROADMAP.md) · [Runner results](attacks/runner-results.md) · [QUAL-01 / #59](https://github.com/interplay-adversarial/interplay/issues/59)

Qualification records the scope actually exercised. The fixture drill below
uses synthetic HTTP responses; it establishes neither live model compatibility
nor judge quality. A live single-turn smoke also leaves multi-turn refinement,
panel calibration and broader model/provider coverage open.

## Qualification matrix

| Method | Single-observation fixture | Extended fixture | Live CLI smoke + offline recovery | Additional coverage still needed |
| --- | --- | --- | --- | --- |
| PAIR | Pass | Pass: two queries with attacker feedback/refinement | Recorded single-observation smoke | Live attacker refinement; distinct models/providers |
| TAP | Pass | Pass: two depths, two generated branches per depth, one admitted | Recorded for #58 candidate | Wider live branching; distinct models/providers |
| Crescendo | Pass | Pass: three conversation turns, escalation and context omission | Recorded single-observation smoke | Live multi-turn conversation and escalation |
| GOAT | Pass | Pass: two conversation turns and structured strategy selection | Recorded single-observation smoke | Live structured strategy selection after seed |
| SLIP | Pass | Pass: lexical insertion then refiner call | Recorded single-observation smoke | Live lexical frontier and refinement |
| Multimodal | Pass: text-only | Pass: 3 transforms × 3 controls, six real PNG payloads | Recorded text-only smoke | Vision-model execution with real images |
| Garak | Separate scanner path | Not in this drill | Pending | Isolated install, live scanner run and native report checks |

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
