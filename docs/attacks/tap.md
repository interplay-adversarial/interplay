# TAP (Tree of Attacks with Pruning)

[← Attack methodologies](README.md) · [Methodology](../METHODOLOGY.md)

**Strategy**: Branch-and-prune search with evaluator pruning  
**Query Budget**: ~15-30 queries  
**Key Feature**: Evaluator LLM prunes weak branches before target query

```python
from interplay.red_teaming import tap_attack
import asyncio


async def main():
    result = await tap_attack(
        goal="Your attack goal",
        target_url="https://your-target/v1",
        attacker_model="openai/gpt-4o-mini",
        evaluator_model="openai/gpt-4o-mini",
        n_iterations=5,
        beam_width=10,
        branching_factor=3,
    )
    print(f"Best ASR: {result.best_score}")
    print(f"Search trajectory: {len(result.search_trajectory)} iterations")


asyncio.run(main())
```

## Notes

- Requires the `red-teaming` extra (`pip install 'interplay-adversarial[red-teaming]'`, or `uv sync --extra red-teaming` in a clone) and the environment variables in the [README configuration section](../../README.md#configuration).
- Run only against targets you own or are authorized to test; see [SECURITY.md](../../SECURITY.md).

## Reference

- Mehrotra et al., NeurIPS 2024 (arXiv:2312.02119)
