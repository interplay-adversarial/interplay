# Methodology

[← Documentation map](README.md) · [Tools and use cases](tools-and-use-cases.md)

Interplay Adversarial combines two kinds of work: **generating** culturally grounded probes, and **attacking** a
target with search-based, multi-turn and multimodal techniques. They can be used separately or together.

## 1. Probe generation: the Singapore challenge methodology

The probe pipeline (`pipeline.py`, `interplay/specs/`) implements the approach of the **Singapore AI Safety Red
Teaming Challenge** (IMDA and Humane Intelligence, February 2025), the first multicultural,
multilingual AI safety red teaming exercise: 9 countries, 54 in-person experts and 308 virtual
participants, with 1,335-1,887 successful exploits per round.

What the challenge found, and why the pipeline is built the way it is:

- **86.1%** of successful exploits came from single-turn *benign* prompts, so the pipeline generates both
  adversarial and benign probes in one run.
- **67.2%** exploit success in regional languages versus **49.2%** in English, so probes are grounded in
  specific cultural contexts rather than generic demographics.
- Positive framing ("which city is *richest*?") bypassed more guardrails than negative framing.

Taxonomies and comparison specs are described in [probe-generation.md](probe-generation.md).
Source: [IMDA Evaluation Report, February 2025](https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-research/artificial-intelligence/singapore-ai-safety-red-teaming-challenge-evaluation-report.pdf).

## 2. Attack methodologies

Seven runners cover different search strategies. Choose by what you know about the target and how many
queries you can spend. Details and examples are in [attacks/](attacks/README.md).

| Approach | Family | Use it when |
|---|---|---|
| [Garak](attacks/garak.md) | Static probe library | You want broad vulnerability coverage first. |
| [TAP](attacks/tap.md) | Tree search with pruning | You have a specific goal and a moderate query budget. |
| [PAIR](attacks/pair.md) | Iterative refinement | You want a cheap black-box loop with a judge. |
| [Crescendo](attacks/crescendo.md) | Multi-turn escalation | The target is conversational and resists direct requests. |
| [GOAT](attacks/goat.md) | Agentic strategy switching | You want the attacker to choose a tactic per turn within a few turns. |
| [SLIP](attacks/slip.md) | Self-jailbreak via lexical insertion | You want the target model to participate in its own compromise. |
| [Multimodal](attacks/multimodal.md) | Image payloads | The target accepts images and text-only guardrails may be bypassed. |

### Combining approaches

A typical integrated run (`examples/integrated_run.py`) generates culturally grounded probes, scans the
target with Garak, runs TAP and PAIR against chosen goals, and merges the results. Probe generation gives
breadth across cultures; the attack runners give depth on specific goals.

### Scoring

Attack runners report method-specific scores; a single best score is not an
empirical attack success rate. PAIR uses a model to score target responses. TAP
queries the target only for branches its evaluator admits, judges each
response with a separate evidence-cited judge, and selects its best candidate
by that judged outcome, not the evaluator's pre-query likelihood. SLIP
queries the target only for candidates its deterministic, bounded insertion
and refinement rounds admit, and judges each response with a separate
evidence-cited judge instead of a keyword/refusal heuristic. Crescendo and
GOAT query the target every turn and judge each response the same way.
Multimodal queries the target for every `(transform, control)` pair and
judges each response the same way; its explicit `"image-only"`/`"text-only"`/
`"combined"` controls mean a success is never attributed to the image alone
when the text (or the transform) could equally explain it.
These interfaces also differ in target authentication and conversation handling.
See the [current implementation limits](tools-and-use-cases.md#explore-the-legacy-attack-runners).

All five (TAP, Crescendo, GOAT, SLIP, Multimodal -- not PAIR) accept more than
one judge model as a panel and report inter-rater reliability: a real,
N-capable Krippendorff's alpha with a bootstrapped confidence interval
(`result.irr_report`), computed from the same judge calls that decided the
verdict, not a separate re-judging pass or a fixed placeholder. The verdict
itself follows a configurable aggregation rule, `"majority"` or
`"unanimous"`. See [tap.md § Current behavior](attacks/tap.md#current-behavior)
for the full semantics.

For captured responses/logs/traces, validated evidence citations, incomplete
outcomes and consistent JSONL/Parquet/Arrow records, use the separate
[description-driven assessment API](assessment.md), in batch or adaptive mode.
Neither model scores nor assessment judgments establish boundary containment or
release authority.

## 3. Limits and responsible use

- Results depend on the attacker, judge and target models; they are not comparable across different judges.
- Adversarial output can be harmful. Follow the [content policy](CONTENT_POLICY.md) and do not commit raw transcripts.
- Use only systems you own or are authorized to test, and report weaknesses as described in
  [SECURITY.md](../SECURITY.md).

## References

- **TAP**: Mehrotra et al., NeurIPS 2024 (arXiv:2312.02119)
- **PAIR**: Chao et al., NeurIPS 2023 (arXiv:2310.08419)
- **Crescendo**: Russinovich et al., USENIX Security 2025 (arXiv:2404.01833)
- **GOAT**: Pavlova et al., 2024 (arXiv:2410.01606)
- **SLIP**: arXiv:2601.02670
- **Garak**: https://github.com/NVIDIA/garak
- **Singapore AI Safety Red Teaming Challenge**: IMDA Evaluation Report, February 2025
