# Runner qualification

[Roadmap](ROADMAP.md) · [Runner results](attacks/runner-results.md) · [QUAL-01 / #59](https://github.com/interplay-adversarial/interplay/issues/59)

Qualification records the scope actually exercised. The fixture drill below
uses synthetic HTTP responses; it establishes neither live model compatibility
nor judge quality. A live single-turn smoke also leaves multi-turn refinement,
panel calibration and broader model/provider coverage open.

## Qualification matrix

| Method | Fixture CLI normal + hard-kill/offline recovery | Live CLI smoke + offline recovery | Additional coverage still needed |
| --- | --- | --- | --- |
| PAIR | Pass | Pending | Live execution; attacker refinement |
| TAP | Pass | Recorded for #58 candidate (same model for every role) | Wider branching; distinct models/providers |
| Crescendo | Pass | Pending | Live execution; multi-turn conversation and escalation |
| GOAT | Pass | Pending | Live execution; structured strategy selection after seed |
| SLIP | Pass | Pending | Live execution; lexical frontier and refinement |
| Multimodal | Pass; text-only control | Pending | Real images/transforms; vision-model execution |
| Garak | Separate scanner path; not in this drill | Pending | Isolated install, live scanner run and native report checks |

All six fixture checks passed on 2026-10-15 against installed package 0.3.1,
whose Python sources matched merged main `c9b8348` byte-for-byte. The drill
also passes three negative tests for swallowed DNS/connect/sendto attempts.
CI repeats the full fixture drill on Python 3.12 and 3.13.

TAP's recorded scope is the bounded installed-CLI smoke and interruption drill
that motivated [#58](https://github.com/interplay-adversarial/interplay/pull/58).
This is not a public empirical attack-success benchmark. No other runner is
promoted to live-qualified by the fixture matrix.

## Repeat the fixture drill

From a source checkout with the development dependencies installed:

```sh
uv sync --frozen
uv run --no-sync python scripts/runner_cli_conformance.py --output /tmp/interplay-cli-conformance
# Or one method in a different new directory:
uv run --no-sync python scripts/runner_cli_conformance.py --method pair --output /tmp/interplay-pair-conformance
```

The output directory must not exist. POSIX is required for SIGKILL and permission
checks. The current interpreter must have the intended Interplay revision
installed; `uv sync --frozen` installs the checkout. The drill invokes
`python -m interplay` in fresh working directories with an isolated HOME,
synthetic role-specific credentials and only loopback endpoints. Provider keys,
proxy variables and user configuration are not inherited.

For each method it verifies:

- One complete normal response with the exact fixture marker, supported response citation and retained judge/provenance/method fields.
- Correct role routing, distinct fixture credentials and model names at the HTTP boundary.
- An actual child-process SIGKILL after the `attempted` and `observed` stages are journaled, while the fixture withholds the judge reply.
- Preserved attempt, goal, probe, response, provenance and method metadata after recovery; incomplete/inconclusive outcome with `interrupted` status reason.
- Two identical offline recoveries with fixture endpoints closed and credentials absent, an unchanged source journal and matching JSONL/Parquet/Arrow exports.
- Zero recovery network attempts, enforced and recorded by a Python audit hook around the same CLI module (including DNS/connect/sendto attempts swallowed by a library).
- Private output permissions and absence of supplied fixture keys in campaign files.

The root `receipt.json` records aggregate status, installed package version and
Python source digests, and per-method checks. A failed
drill keeps its partial output and leaves `passed: false`; retain it for diagnosis
and use a new directory when repeating. Fixture responses deliberately return a
synthetic success; they measure transport and evidence handling, not attacks.
The first drill bounds each method to one target observation, so GOAT strategy
selection, PAIR/Crescendo refinement and SLIP refinement are not exercised.

## Live qualification acceptance

For each method, record the immutable source revision, installed-code identity,
role model identities, bounded parameters and effective serving configuration.
Retain complete and failed outcomes, private raw evidence and redacted receipts.
Repeat the normal/interruption/recovery invariants using authorized live targets,
including actual image observations for Multimodal and multi-turn/refinement
coverage where applicable. Same-model smoke results must state that judging is
not independent. Garak requires its own scanner-native checks and isolated
dependency environment; it does not use `runner-recover`.
