# SLIP (Self-Jailbreaking via Lexical Insertion)

[← Attack methodologies](README.md) · [Methodology](../METHODOLOGY.md)

**Strategy**: Target model guides its own compromise via BFS  
**Query Budget**: ~8 iterations  
**Key Feature**: Lexical insertion of goal words into benign prompts

```python
from red_teaming import slip_attack
import asyncio


async def main():
    result = await slip_attack(
        goal="Your attack goal",
        target_url="https://your-target/v1",
        target_model="your-model",
        max_iterations=8,
    )
    print(f"Best ASR: {result.best_score}")
    print(f"Iterations: {result.iterations}")


asyncio.run(main())
```

## Notes

- Requires the `red-teaming` extra (`uv sync --extra red-teaming`) and the environment variables in the [README configuration section](../../README.md#configuration).
- Run only against targets you own or are authorized to test; see [SECURITY.md](../../SECURITY.md).

## Reference

- arXiv:2601.02670
