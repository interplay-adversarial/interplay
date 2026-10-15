# TAP (Tree of Attacks with Pruning)

[← Attack methodologies](README.md) · [Documentation map](../README.md) · [Methodology](../METHODOLOGY.md)

**Strategy**: Branch-and-prune search with evaluator pruning, real target execution and
evidence-cited judging
**Query Budget**: beam_width (1-10) x n_iterations (1-10), only for admitted branches
**Key Feature**: The evaluator's likelihood score is pruning signal only; it never
becomes a verdict. Only the admitted (non-pruned) branches query the target through
the shared authenticated transport ([interplay.red_teaming.transport](../../interplay/red_teaming/transport.py)),
and only a separate evidence-cited judge call decides success/failure/inconclusive.

```python
from interplay.red_teaming import tap_attack
import asyncio


async def main():
    result = await tap_attack(
        goal="Your attack goal",
        target_url="https://your-target/v1",
        attacker_model="openai/gpt-4o-mini",
        evaluator_model="openai/gpt-4o-mini",
        judge_model="openai/gpt-4o-mini",
        secondary_judge_models=["anthropic/claude-3-haiku"],  # optional: forms a panel, see below
        judge_aggregation="unanimous",
        n_iterations=5,
        beam_width=10,
        branching_factor=3,
    )
    print(f"Evaluator score of the judged-best candidate: {result.best_score}")
    print(f"Judge-confirmed success: {result.confirmed_success}")
    print(f"Stop reason: {result.stop_reason}")
    print(f"Search trajectory: {len(result.search_trajectory)} iterations")
    print(f"Every attempted (pruned or queried) branch: {len(result.trials)}")
    print(f"Inter-rater reliability: {result.irr_report}")


asyncio.run(main())
```

## Current behavior

- **Branching and pruning are distinct from judging.** Each iteration expands every
  surviving branch into `branching_factor` variants (1-5), the evaluator scores each
  variant's likelihood of achieving the goal, and only the top `beam_width` (1-10) by
  that score are admitted. Pruned branches are retained in `result.trials` with
  `pruned: true` and never query the target.
- **Best-candidate selection uses the judged outcome, not the evaluator score.** A
  judge-confirmed success always outranks a judge-failed branch, even one with a much
  higher evaluator score; `result.confirmed_success` is the only field asserting that
  the judge, with captured evidence, called a response a success. `result.best_score`
  remains the evaluator's pre-query likelihood for whichever branch was selected -- a
  search diagnostic, not an attack success rate.
- **Without `judge_model`**, every admitted branch stays `judge_verdict: "inconclusive"`
  (`error_code: "no-judge-configured"`); the runner never fabricates a success from the
  evaluator's score alone.
- **A judge panel is optional, and its aggregation rule is configurable.** Pass one or
  more `secondary_judge_models` alongside `judge_model` to form a panel
  ([`interplay.red_teaming.transport.JudgePanel`](../../interplay/red_teaming/transport.py)):
  every configured judge scores each admitted branch independently, and
  `judge_aggregation` decides how their verdicts combine into the branch's one verdict --
  `"majority"` (a strict plurality winner; any tie, including every 2-judge split, is
  `inconclusive`) or `"unanimous"` (every judge must agree; identical to `"majority"` at
  exactly 2 judges). `result.irr_report` is a real, N-capable Krippendorff's alpha (with a
  bootstrapped confidence interval) across every branch the panel judged, computed from
  those same calls -- never a fixed placeholder, and never requiring a second,
  diagnostic-only re-judging pass. Without at least two total judges, `irr_report` is
  `None` with `irr_unavailable_reason` set (for example `"insufficient-judges"`). Every
  judge's individual verdict and reasoning for a branch is retained on that branch's
  trial as `judge_panel_json`, not collapsed away by the aggregation.
- **No automatic retries.** A target or judge call that fails, times out, or exceeds
  `campaign_seconds` stops the search where it is (`result.stop_reason` explains why)
  and still returns every branch attempted so far, pruned or queried.
- **Paper note**: this implements the branch/prune/judge control flow described by
  Mehrotra et al.; it does not reproduce their published attack-success-rate numbers,
  and `best_score`/`confirmed_success` should not be read as a comparable metric.

## Notes

- Requires the `red-teaming` extra (`pip install 'interplay-adversarial[red-teaming]'`, or `uv sync --extra red-teaming` in a clone) and the environment variables in the [README configuration section](../../README.md#configuration).
- Run only against targets you own or are authorized to test; see [SECURITY.md](../../SECURITY.md).

## Reference

- Mehrotra et al., NeurIPS 2024 (arXiv:2312.02119)
