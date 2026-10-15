# Crescendo

[← Attack methodologies](README.md) · [Methodology](../METHODOLOGY.md)

**Strategy**: Multi-turn benign-to-harmful escalation
**Query Budget**: ≤ `max_turns` (1-20) target queries, one per turn
**Key Feature**: Turn 0 always sends a fixed benign framing of the goal; every later
turn's prompt is generated from the captured outcomes of every turn executed so far,
including the validated judge verdict, never a keyword/refusal heuristic.

```python
from interplay.red_teaming import crescendo_attack
import asyncio


async def main():
    result = await crescendo_attack(
        goal="Your attack goal",
        target_url="https://your-target/v1",
        attacker_model="openai/gpt-4o-mini",
        judge_model="openai/gpt-4o-mini",
        max_turns=10,
    )
    print(f"Judge-confirmed success: {result.confirmed_success}")
    print(f"Stop reason: {result.stop_reason}")
    print(f"Executed turns: {[(t['turn'], t['prompt']) for t in result.trials]}")


asyncio.run(main())
```

## Current behavior

- **Turn 0 is always the same fixed benign template, not attacker-generated.** Every
  later turn's escalation prompt comes from a free-text attacker call shown the
  captured outcomes of a bounded window of the most recently executed turns --
  prompt sent, response observed and the validated judge verdict. An escalation call
  that returns empty text stops the campaign (`stop_reason` starts with
  `"attacker-output-invalid:empty-escalation-prompt"`) instead of being executed as a
  prompt.
- **The attacker's own context window is independently bounded and self-reporting.**
  `context_window` (1-10, default 3) caps how many prior turns the attacker is shown
  when deciding the next escalation; once more turns have executed than the window
  holds, the attacker's prompt explicitly states how many earlier turns were omitted
  (`result.trials[i]["context_omitted_turns"]`), rather than silently dropping them.
  This is separate from `target_mode`'s own target-side history, which is unbounded.
- **`target_mode` makes the target request semantics explicit and verifiable.**
  `"conversation"` (the default) sends every prior turn's prompt and the target's own
  reply back to the target each turn, so the target sees a real multi-turn
  conversation; `"stateless"` sends only the current turn's prompt, with no memory of
  prior turns. Either mode only ever sends the attacker-generated prompt text --
  operator-owned target configuration (base URL, model, credentials) is never replaced
  by it. The exact message list sent for a turn is retained verbatim on that trial
  (`result.trials[i]["messages_sent_json"]`), so the mode actually used for a run is
  checkable from the record, not just from configuration.
- **Judging replaces the old keyword/refusal heuristic.** Without `judge_model`, every
  turn stays `judge_verdict: "inconclusive"` (`error_code: "no-judge-configured"`); the
  runner never fabricates a success from response text alone. `result.confirmed_success`
  is the only field asserting that the judge, with captured evidence, called a turn's
  response a success; `result.best_score` is a diagnostic derived from the selected
  trial's verdict (success=1.0, inconclusive=0.5, failure=0.0), not an attack success
  rate.
- **Success is terminal.** Once a turn's judge verdict is `"success"` on a complete
  capture, the campaign stops immediately; no further attacker call is made to decide
  an escalation that will never run.
- **No backtracking.** Russinovich et al. describe retrying an unproductive turn with a
  different phrasing before advancing; this implementation always continues forward
  from a failed or inconclusive turn's state instead, the same discipline
  [`goat_attack`](goat.md) uses for strategy switches. There is no notion here of
  reverting to an earlier turn and resending a different escalation for it.
- **No automatic retries.** A target or judge call that fails, times out, or exceeds
  `campaign_seconds` stops the campaign where it is (`result.stop_reason` explains why)
  and still returns every turn executed so far, including an incomplete final trial
  when a target call itself failed.

## Notes

- Requires the `red-teaming` extra (`pip install 'interplay-adversarial[red-teaming]'`, or `uv sync --extra red-teaming` in a clone) and the environment variables in the [README configuration section](../../README.md#configuration).
- Run only against targets you own or are authorized to test; see [SECURITY.md](../../SECURITY.md).

## Reference

- Russinovich et al., USENIX Security 2025 (arXiv:2404.01833)
