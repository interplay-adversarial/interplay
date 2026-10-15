# SLIP (Self-Jailbreaking via Lexical Insertion)

[← Attack methodologies](README.md) · [Documentation map](../README.md) · [Methodology](../METHODOLOGY.md)

**Strategy**: Bounded lexical word insertion, then target-assisted refinement, both
with real target execution and evidence-cited judging
**Query Budget**: up to `(max_words + refine_rounds) * max_candidates_per_round`
target queries, only for non-truncated candidates
**Key Feature**: Candidate generation, deduplication and truncation are all
deterministic (first-occurrence order, never `set()` order), and every generated
candidate -- truncated away or queried -- is retained with a stable parent id.

```python
from interplay.red_teaming import slip_attack
import asyncio


async def main():
    result = await slip_attack(
        goal="Your attack goal",
        target_url="https://your-target/v1",
        target_model="your-model",
        refiner_model="openai/gpt-4o-mini",
        judge_model="openai/gpt-4o-mini",
        secondary_judge_models=["anthropic/claude-3-haiku"],  # optional: forms a panel
        judge_aggregation="unanimous",
        max_words=8,
        refine_rounds=3,
    )
    print(f"Judge-confirmed success: {result.confirmed_success}")
    print(f"Stop reason: {result.stop_reason}")
    print(f"Search trajectory: {len(result.search_trajectory)} rounds")
    print(f"Every generated (truncated or queried) candidate: {len(result.trials)}")
    print(f"Inter-rater reliability: {result.irr_report}")


asyncio.run(main())
```

## Current behavior

- **Two distinct phases, never mixed.** Each round either inserts the next bounded,
  deduplicated content word from the goal into every surviving candidate (at the fixed
  position order `start`, `end`, `middle`), or -- once insertion words run out -- asks
  the `refiner_model` for one small refinement of the current best candidate. A round
  is one phase or the other, and `result.search_trajectory[i]["phase"]` records which.
- **Content-word extraction is defined and bounded.** Tokens are `\w+` runs, lowercased;
  stop words and tokens of length <= 2 are dropped; a repeated word (for example "write
  write a keylogger keylogger") is inserted only once, at its first occurrence. A goal
  with no content words at all (empty, punctuation-only, or entirely stop words), or
  `max_words=0`, skips insertion entirely and the first round goes straight to
  target-assisted refinement.
- **Deduplication and truncation are deterministic, not `set()`-based.** Candidates are
  deduplicated by first occurrence in generation order (parent order, then position
  order), then capped to `max_candidates_per_round`; anything past that cap is retained
  in `result.trials` with `pruned: true` and `prune_reason: "round-breadth-exceeded"`,
  and never queries the target. Every seed is likewise retained with
  `prune_reason: "search-seed"` -- a seed is a search starting point, never queried itself.
- **Best-candidate selection uses the judged outcome, never generation order alone.** A
  judge-confirmed success always outranks a judge-failed or inconclusive candidate.
  `result.confirmed_success` is the only field asserting that the judge, with captured
  evidence, called a queried candidate's response a success.
- **Without `judge_model`**, every queried candidate stays
  `judge_verdict: "inconclusive"` (`error_code: "no-judge-configured"`); since only a
  judge-confirmed `complete` candidate can seed the next round's frontier, the search
  stops after the first round it runs (`stop_reason: "frontier-exhausted"`) instead of
  continuing on an unjudged basis.
- **A judge panel and its aggregation rule (`judge_aggregation`) are configurable the
  same way as every other migrated runner** -- see [tap.md § Current behavior](tap.md#current-behavior)
  for the full semantics (`JudgePanel`, `"majority"`/`"unanimous"`, `irr_report`,
  `judge_panel_json`), which apply here unchanged.
- **Without `refiner_model`**, a round that would need refinement (because insertion
  words are exhausted but `refine_rounds` has rounds left) stops the search instead of
  silently skipping refinement (`stop_reason: "no-refiner-configured"`).
- **No automatic retries.** A target or judge call that fails, times out, or exceeds
  `campaign_seconds` stops the search where it is (`result.stop_reason` explains why)
  and still returns every candidate generated so far, truncated or queried.
- **Deviation from the original paper**: SLIP's published method uses the target model
  itself as its own refinement guide. This implementation routes refinement through an
  explicitly configured `refiner_model` instead, separate from the target and the
  judge, so no role's credentials are ever reused for another role's call.

## Notes

- Requires the `red-teaming` extra (`pip install 'interplay-adversarial[red-teaming]'`, or `uv sync --extra red-teaming` in a clone) and the environment variables in the [README configuration section](../../README.md#configuration).
- Run only against targets you own or are authorized to test; see [SECURITY.md](../../SECURITY.md).

## Reference

- arXiv:2601.02670
