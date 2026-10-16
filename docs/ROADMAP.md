# Roadmap

[Documentation map](README.md) · [Qualification matrix](runner-qualification.md)

This roadmap tracks proposed work and its acceptance criteria. An implemented
method, a fixture pass, a live smoke pass and validated evaluation quality are
separate milestones. Status below is recorded on 2026-10-15; linked issues own
the current task state. There are no delivery-date commitments.

## Delivery sequence

| Order | Item | Outcome | Status | Dependencies |
| --- | --- | --- | --- | --- |
| 1 | [QUAL-01 / #59](https://github.com/interplay-adversarial/interplay/issues/59) | Repeatable CLI conformance and bounded live qualification for every runner, with interruption/recovery where supported | In progress: both fixture profiles and six native single-observation live smokes recorded; advanced live paths/Garak pending | Existing runner evidence contracts |
| 2 | [JUDGE-01 / #60](https://github.com/interplay-adversarial/interplay/issues/60) | Human-labeled calibration of single judges and panels, with accuracy, coverage and uncertainty | Planned | QUAL-01; independent human labels |
| 3 | [BENCH-01 / #61](https://github.com/interplay-adversarial/interplay/issues/61) | Reproducible paired comparisons of models/configurations under equal query budgets | Planned | QUAL-01; JUDGE-01 for accuracy-sensitive conclusions |
| 4 | [AGENT-01 / #62](https://github.com/interplay-adversarial/interplay/issues/62) | Optional instrumented NeMo Gym TargetAdapter with captured tool and environment outcomes | Planned | QUAL-01; optional Gym environment |
| 5 | [REPORT-01 / #63](https://github.com/interplay-adversarial/interplay/issues/63) | Offline readable reports with lineage, citations, errors and judge disagreements | Planned; can proceed alongside calibration | QUAL-01 schemas |
| 6 | [BOUNDARY-01 / #64](https://github.com/interplay-adversarial/interplay/issues/64) | Reviewed gate source admission and explicit bindings to independently observed effects | Planned; coordinate gate-side work | QUAL-01; AGENT-01 where applicable |
| 7 | [CULTURE-01 / #65](https://github.com/interplay-adversarial/interplay/issues/65) | Matched multilingual benign/adversarial datasets with native-speaker review | Planned | JUDGE-01; qualified reviewers |

Each issue defines scope and measurable acceptance criteria. In particular,
JUDGE-01 starts with at least 60 independently labeled reference cases, and
CULTURE-01 proposes at least 20 matched pairs per selected context-language cell.
Reviewer availability is a dependency, not an assumed completed activity.

## First increment: QUAL-01

`scripts/runner_cli_conformance.py` invokes the actual runner CLI in child
processes against an authenticated loopback fixture. It checks one normal
observation and a SIGKILL after the response is durably observed but before the
judge returns, then performs repeated offline recovery. See the
[qualification matrix and instructions](runner-qualification.md).

The next increment adds an extended fixture profile with actual attacker
refinement, multi-turn conversations, TAP pruning/lineage and the full PNG
image-control matrix. Five additional bounded live single-observation smokes
(PAIR, Crescendo, GOAT, SLIP and Multimodal text-only) and their offline recovery
checks pass, alongside the earlier TAP smoke. Remaining work includes live
refinement/multi-turn and vision coverage, distinct models/providers, and
isolated Garak qualification with its scanner-specific report semantics.
The existing TAP live smoke exercises plumbing using one model for every role;
it does not establish judge independence or adversarial robustness.

## Release checkpoint

[Runner hardening #57](https://github.com/interplay-adversarial/interplay/pull/57)
and [judge-format compatibility #58](https://github.com/interplay-adversarial/interplay/pull/58)
merged after the v0.3.1 release. Cut a subsequent patch release through the
[TestPyPI-first process](RELEASING.md) after reviewing the intended release scope
and package smoke results. Source-main capability must not be inferred from an
older published version. This roadmap does not itself publish a release.

## Research tracks

Keep the existing research issues rather than duplicating them:

- [#25: User-belief auditing](https://github.com/interplay-adversarial/interplay/issues/25) — potential extension of cultural evaluation; coordinate with JUDGE-01 and CULTURE-01.
- [#24: Recursive self-improvement safety taxonomy](https://github.com/interplay-adversarial/interplay/issues/24) — scope and taxonomy research before expanding evaluation coverage.

Behavior verdicts, independently observed effects and containment decisions
remain separate. Garak retains its separate dependency environment and native
report format throughout this work.
