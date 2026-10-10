# Crescendo

[← Attack methodologies](README.md) · [Methodology](../METHODOLOGY.md)

**Strategy**: Multi-turn benign-to-harmful escalation  
**Query Budget**: 5-10 turns  
**Key Feature**: Uses model's own responses to guide escalation

```python
from red_teaming import crescendo_attack
import asyncio


async def main():
    result = await crescendo_attack(
        goal="Your attack goal",
        target_url="https://your-target/v1",
        attacker_model="openai/gpt-4o-mini",
        max_turns=10,
    )
    print(f"Best ASR: {result.best_score}")
    print(f"Turns: {result.turns}")


asyncio.run(main())
```

## Notes

- Requires the `red-teaming` extra (`uv sync --extra red-teaming`) and the environment variables in the [README configuration section](../../README.md#configuration).
- Run only against targets you own or are authorized to test; see [SECURITY.md](../../SECURITY.md).

## Reference

- Russinovich et al., USENIX Security 2025 (arXiv:2404.01833)
