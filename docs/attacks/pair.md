# PAIR (Prompt Automatic Iterative Refinement)

[← Attack methodologies](README.md) · [Methodology](../METHODOLOGY.md)

**Strategy**: Iterative refinement with attacker + judge loop  
**Query Budget**: ~20 queries  
**Key Feature**: Attacker refines based on conversation history + CoT improvement

```python
from red_teaming import pair_attack
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

## Notes

- Requires the `red-teaming` extra (`uv sync --extra red-teaming`) and the environment variables in the [README configuration section](../../README.md#configuration).
- Run only against targets you own or are authorized to test; see [SECURITY.md](../../SECURITY.md).

## Reference

- Chao et al., NeurIPS 2023 (arXiv:2310.08419)
