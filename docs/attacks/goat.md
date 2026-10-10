# GOAT (Generative Offensive Agent Tester)

[← Attack methodologies](README.md) · [Methodology](../METHODOLOGY.md)

**Strategy**: Dynamic strategy switching with reasoning  
**Query Budget**: ≤5 turns  
**Key Feature**: Attacker reasons about best strategy per turn

```python
from interplay.red_teaming import goat_attack
import asyncio


async def main():
    result = await goat_attack(
        goal="Your attack goal",
        target_url="https://your-target/v1",
        attacker_model="openai/gpt-4o-mini",
        max_turns=5,
    )
    print(f"Best ASR: {result.best_score}")
    print(f"Strategy trajectory: {result.strategy_trajectory}")


asyncio.run(main())
```

## Notes

- Requires the `red-teaming` extra (`uv sync --extra red-teaming`) and the environment variables in the [README configuration section](../../README.md#configuration).
- Run only against targets you own or are authorized to test; see [SECURITY.md](../../SECURITY.md).

## Reference

- Pavlova et al., 2024 (arXiv:2410.01606)
