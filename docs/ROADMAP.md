# Roadmap

[Documentation map](README.md) · [Qualification matrix](runner-qualification.md)

This roadmap tracks proposed work and its acceptance criteria. An implemented
method, a fixture pass, a live smoke pass and validated evaluation quality are
separate milestones. Status below is recorded on 2026-10-16; linked issues own
the current task state. There are no delivery-date commitments.

## Delivery sequence

| Order | Item | Outcome | Status | Dependencies |
| --- | --- | --- | --- | --- |
| 1 | [QUAL-01 / #59](https://github.com/interplay-adversarial/interplay/issues/59) | Repeatable CLI conformance and bounded live qualification for every runner, with interruption/recovery where supported | In progress: live PAIR/TAP/Crescendo/GOAT/SLIP continuation passes in recorded configurations; real Garak loopback passes; vision and Garak live remain pending | Existing evidence contracts; Garak dependency blocker [#68](https://github.com/interplay-adversarial/interplay/issues/68) |
| 2 | [JUDGE-01 / #60](https://github.com/interplay-adversarial/interplay/issues/60) | Human-labeled calibration of single judges and panels, with accuracy, coverage and uncertainty | In progress: rubric, 60 synthetic cases, human-label workflow, bounded collector and offline metrics; actual human reviews and two-model run pending | QUAL-01; independent human labels |
| 3 | [BENCH-01 / #61](https://github.com/interplay-adversarial/interplay/issues/61) | Reproducible paired comparisons of models/configurations under equal query budgets | Implemented in this increment: fixed-probe manifests, paired runner/imports, offline recovery and bounded live comparison | QUAL-01; JUDGE-01 for accuracy-sensitive conclusions |
| 4 | [AGENT-01 / #62](https://github.com/interplay-adversarial/interplay/issues/62) | Optional instrumented NeMo Gym TargetAdapter with captured tool and environment outcomes | Implemented in this increment: optional pinned target, native fixtures and bounded live receiver-effect rollout | QUAL-01; optional Gym environment |
| 5 | [REPORT-01 / #63](https://github.com/interplay-adversarial/interplay/issues/63) | Offline readable reports with lineage, citations, errors and judge disagreements | Completed in merged [#71](https://github.com/interplay-adversarial/interplay/pull/71) | QUAL-01 schemas |
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

The extended fixture profile covers actual attacker refinement, multi-turn
conversations, TAP pruning/lineage and the full PNG image-control matrix. All
six native methods have bounded single-observation live smokes and recovery
checks. Live continuation is also recorded for PAIR, TAP, Crescendo, GOAT and SLIP using an explicit
synthetic target-system control and retained wire evidence. Crescendo passes
three turns and final-observation interruption/recovery with recorded attacker
sampling overrides. Its empty-escalation and judge-false-positive failures
remain preserved; this does not establish judge reliability. Installed Garak 0.17.0 loopback compatibility
exposed and now covers valid final JSON without a newline; its separate
dependency audit remains blocked in #68. Remaining work includes
vision coverage, distinct models/providers, wider method budgets and isolated
Garak live qualification. See the qualification matrix for the
current method-specific scope rather than treating implementation or a fixture
pass as full live qualification.
The existing TAP live smoke exercises plumbing using one model for every role;
it does not establish judge independence or adversarial robustness.

## Offline reports: REPORT-01

`interplay report` creates a private standalone HTML report and JSON summary
from one retained export snapshot, without provider imports or model calls.
It includes incomplete/error outcomes, attack lineage, citation-resolution checks
and retained panel disagreements. Captured values are escaped; search scores and
model judgments do not establish independently verified environment effects.
See [campaign reports](campaign-reports.md) for supported schemas, privacy and
recovery requirements. Judge calibration and wider qualification remain separate.

## Judge calibration: JUDGE-01

`interplay calibration prepare` creates 60 matched synthetic tasks and two
review packets with no prefilled human verdicts. Gold compilation requires two
distinct attested human reviewers per case and a third reviewer for disagreements.
An explicit bounded collector retains model replies; offline scoring compares
single judges and the existing plurality/unanimous policies with confusion,
coverage, error, agreement and uncertainty summaries. Design intent and test
fixtures are not human gold. Actual human reviews and a real two-model run
remain pending. See [judge calibration](judge-calibration.md).

## Paired comparisons: BENCH-01

`interplay benchmark` freezes fixed probes and two explicit configurations under
equal target query/token/timeout caps, with an optional shared judge. It retains
partial outcomes, observed resources and paired deltas, and can import exact-match
native exports or recover interrupted journals offline. Legacy resource usage is
unavailable. Adaptive search parity and calibrated accuracy are not established.
The fixture regression and an eight-request installed-CLI live comparison pass.
See [benchmark comparisons](benchmark-comparisons.md) and its sanitized machine-readable
receipt; private raw captures are not published.

## Instrumented agent target: AGENT-01

The optional `NeMoGymTarget` plugs into the assessment Python API using a
fresh pinned SimpleAgent session per attempt. It retains tool dispatches/native
trajectories and a separately observed environment outcome, with cooperative
deadlines and incomplete capture handling. It does not enforce containment or
change infrastructure itself. Native complete/exhausted/truncated fixtures and
a bounded live automatic-tool receiver-effect rollout pass. Earlier unavailable/
unsupported attempts remain retained; the existing model service was separately
configured for tool calling at the user’s direction. See [NeMo Gym target](nemo-gym-target.md).

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
