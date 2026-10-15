# GOAT (Generative Offensive Agent Tester)

[← Attack methodologies](README.md) · [Documentation map](../README.md) · [Methodology](../METHODOLOGY.md)

**Strategy**: Dynamic strategy switching driven by captured outcomes and real judging
**Query Budget**: ≤ `max_turns` (1-20) target queries, one per turn
**Key Feature**: Every turn's strategy and prompt come from one structured, validated
attacker decision -- a malformed or out-of-pool decision is rejected outright, never
executed, and the strategy recorded on a trial always matches the prompt actually sent
for it.

```python
from interplay.red_teaming import goat_attack
import asyncio


async def main():
    result = await goat_attack(
        goal="Your attack goal",
        target_url="https://your-target/v1",
        attacker_model="openai/gpt-4o-mini",
        judge_model="openai/gpt-4o-mini",
        max_turns=5,
    )
    print(f"Judge-confirmed success: {result.confirmed_success}")
    print(f"Stop reason: {result.stop_reason}")
    print(f"Executed turns: {[(t['turn'], t['strategy']) for t in result.trials]}")


asyncio.run(main())
```

## Current behavior

- **Strategy selection is structured and validated.** Each turn after the first (the
  first turn always sends `goal` itself, recorded with `strategy: "seed"`), the attacker
  is shown every captured outcome so far -- the prompt sent, the response observed and
  the validated judge verdict -- and must return a single JSON object naming one
  strategy verbatim from `strategy_pool` plus the next prompt. A response that fails to
  parse, or that names a strategy outside the pool, stops the campaign
  (`stop_reason` starts with `"attacker-output-invalid:"`) instead of being executed as
  a prompt or silently relabeled `"unknown"`.
- **The executed trajectory is `result.trials`, not a separate list.** Each trial binds
  the strategy and prompt actually sent to its parent trial's `attempt_id`, so a
  strategy decision that is generated but never executed (for example, because a
  budget or deadline stopped the campaign first) never appears as if it ran.
- **Judging replaces the old keyword/refusal heuristic.** Without `judge_model`, every
  turn stays `judge_verdict: "inconclusive"` (`error_code: "no-judge-configured"`); the
  runner never fabricates a success from response text alone. `result.confirmed_success`
  is the only field asserting that the judge, with captured evidence, called a turn's
  response a success; `result.best_score` is a diagnostic derived from the selected
  trial's verdict (success=1.0, inconclusive=0.5, failure=0.0), not an attack success
  rate.
- **`target_mode` makes the request semantics explicit.** `"conversation"` (the
  default) sends every prior turn's prompt and the target's own reply back to the
  target each turn, so the target sees a real multi-turn conversation; `"stateless"`
  sends only the current turn's prompt, with no memory of prior turns. Either mode
  only ever sends the attacker-generated prompt text -- operator-owned target
  configuration (base URL, model, credentials) is never replaced by generated content.
- **Success is terminal.** Once a turn's judge verdict is `"success"` on a complete
  capture, the campaign stops immediately; no further attacker call is made to decide
  a next turn that will never run.
- **No automatic retries.** A target or judge call that fails, times out, or exceeds
  `campaign_seconds` stops the campaign where it is (`result.stop_reason` explains why)
  and still returns every turn executed so far, including an incomplete final trial
  when a target call itself failed.

## Notes

- Requires the `red-teaming` extra (`pip install 'interplay-adversarial[red-teaming]'`, or `uv sync --extra red-teaming` in a clone) and the environment variables in the [README configuration section](../../README.md#configuration).
- Run only against targets you own or are authorized to test; see [SECURITY.md](../../SECURITY.md).

## Reference

- Pavlova et al., 2024 (arXiv:2410.01606)
