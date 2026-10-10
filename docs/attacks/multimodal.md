# Multimodal (Image Payload)

[← Attack methodologies](README.md) · [Methodology](../METHODOLOGY.md)

**Strategy**: Embed harmful instruction in image  
**Query Budget**: 1-3 transforms  
**Key Feature**: Bypass text-only guardrails

```python
from interplay.red_teaming import multimodal_attack
import asyncio


async def main():
    result = await multimodal_attack(
        goal="Your attack goal",
        vision_target_url="https://vision-target/v1",
        vision_model="openai/gpt-4o",
        transforms=["plain", "base64", "leetspeak"],
    )
    print(f"Best ASR: {result.best_score}")
    print(f"Image path: {result.image_path}")


asyncio.run(main())
```

## Notes

- Requires the `red-teaming` extra (`pip install 'interplay-adversarial[red-teaming]'`, or `uv sync --extra red-teaming` in a clone) and the environment variables in the [README configuration section](../../README.md#configuration).
- Run only against targets you own or are authorized to test; see [SECURITY.md](../../SECURITY.md).
