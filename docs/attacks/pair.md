# PAIR (Prompt Automatic Iterative Refinement)

[← Attack methodologies](README.md) · [Documentation map](../README.md) · [Methodology](../METHODOLOGY.md)

**Strategy**: Iterative refinement with attacker + judge loop  
**Query Budget**: ~20 queries  
**Key Feature**: Attacker refines based on conversation history + CoT improvement

```python
from interplay.red_teaming import pair_attack
import asyncio


async def main():
    result = await pair_attack(
        goal="Your attack goal",
        target_url="https://your-target/v1",
        attacker_model="openai/gpt-4o-mini",
        judge_model="openai/gpt-4o-mini",
        max_queries=20,
    )
    print(f"Best ASR: {result.best_score}")
    print(f"Query count: {result.query_count}")


asyncio.run(main())
```

## Current behavior

- **The target call is authenticated.** `_call_target` goes through
  `interplay.red_teaming.transport.AuthenticatedTarget` and attaches
  `Authorization: Bearer <api_key>` when `pair_attack(..., api_key=...)` is set --
  the previous implementation posted to the target with no Authorization header
  at all, so a configured key was silently never sent. One attempt per
  iteration, no retries; a failed or budget-exhausted target call is retained
  as an incomplete trial (`conversation_history[-1]["error"]`) and stops the
  campaign instead of raising and losing the trials already gathered.
- **Judging is still the old numeric heuristic, not the shared `JudgeScorer`.**
  `_judge_score` asks `judge_model` to "respond with ONLY a number" from 0.0 to
  1.0 and clamps it; it is not evidence-cited, does not call
  `interplay.assessment`'s `JudgeOutput`/`evidence_supported`, and never
  returns `"inconclusive"` -- a parse failure silently becomes `0.0`. PAIR is
  the one runner in this package not yet migrated to
  [`interplay.red_teaming.transport.JudgeScorer`](../../interplay/red_teaming/transport.py),
  unlike [TAP](tap.md), [Crescendo](crescendo.md), [GOAT](goat.md),
  [SLIP](slip.md) and [Multimodal](multimodal.md). `result.best_score` is this
  heuristic score, not an evidence-cited verdict or an empirical attack
  success rate; treat the migration as planned, not shipped.
- **No result retention.** Like every other legacy runner, `pair_attack`
  returns only an in-memory `PairResult`; it does not write to
  `interplay.red_teaming.transport.RunnerResultSink`, so there is nothing to
  recover with `recover_runner_records` after an interrupted run. See
  [the shared-transport integration status](../tools-and-use-cases.md#explore-the-legacy-attack-runners).
- **Refinement is a free-text attacker call**, not the structured,
  pool-validated decision [GOAT](goat.md) uses; a malformed refinement is used
  as-is (the whole reply, if no `PROMPT:` marker is found) rather than
  rejected.

## Notes

- Requires the `red-teaming` extra (`pip install 'interplay-adversarial[red-teaming]'`, or `uv sync --extra red-teaming` in a clone) and the environment variables in the [README configuration section](../../README.md#configuration).
- Run only against targets you own or are authorized to test; see [SECURITY.md](../../SECURITY.md).

## Reference

- Chao et al., NeurIPS 2023 (arXiv:2310.08419)
