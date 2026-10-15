# Multimodal (Image Payload)

[← Attack methodologies](README.md) · [Documentation map](../README.md) · [Methodology](../METHODOLOGY.md)

**Strategy**: Embed a transformed instruction in an image, with explicit text/image controls
**Query Budget**: `len(transforms) * len(controls)` target queries (default 3×3 = 9)
**Key Feature**: Every `(transform, control)` pair is queried and judged independently, so a
success is never attributed to "the image" when the text alone could equally explain it.

```python
from interplay.red_teaming import multimodal_attack
import asyncio


async def main():
    result = await multimodal_attack(
        goal="Your attack goal",
        vision_target_url="https://vision-target/v1",
        vision_model="openai/gpt-4o",
        judge_model="openai/gpt-4o-mini",
        transforms=("plain", "base64", "leetspeak"),
        controls=("image-only", "text-only", "combined"),
    )
    print(f"Judge-confirmed success: {result.confirmed_success}")
    print(f"Best control/transform: {result.best_control} / {result.best_transform}")
    print(f"Every attempted pair: {[(t['control'], t['transform']) for t in result.trials]}")


asyncio.run(main())
```

## Controls

Each `transform` (`plain`, `base64`, `leetspeak`) is tried under three `control`s, so a result
can say exactly what was tested instead of implicitly crediting the image:

- `"image-only"`: the goal (transformed) is embedded in the image; the accompanying text is a
  fixed, goal-agnostic instruction. The target never sees the goal as text.
- `"text-only"`: no image is sent at all; the (transformed) goal is sent as plain text. This is
  the control that isolates whether the transform alone, independent of being in an image,
  causes compliance.
- `"combined"`: both the image and a goal-revealing text prompt are sent, matching the original,
  unlabeled behavior this runner had before.

## Scoring and evidence

Every attempt is judged by a separate evidence-cited judge (`judge_model`); without one, every
trial stays `inconclusive` (`error_code="no-judge-configured"`), never a keyword-matched score.
`result.trials` retains every attempted pair, not only the best one, and `result.confirmed_success`
is always paired with the exact `best_control`/`best_transform` that produced it.

## Payloads

Rendered images are written to a private (0700 directory, 0600 file), per-run directory with
collision-resistant names (`<attempt_id>.png`); a sha256 digest and byte size are recorded on
every trial. The directory is removed after the run unless `preserve_payloads=True`. A payload
that does not fit the bounded canvas at any attempted font size is still rendered, sent and
scored, marked `image_truncated=True` on its trial, rather than silently resized until it reads
as something else.

## Notes

- Requires the `red-teaming` extra for the runner itself, plus the `multimodal` extra
  (`pip install 'interplay-adversarial[red-teaming,multimodal]'`) for Pillow, which is imported
  lazily only when an image payload is actually rendered; a `controls=("text-only",)`-only run
  never needs it.
- Also needs the environment variables in the [README configuration section](../../README.md#configuration).
- Run only against targets you own or are authorized to test; see [SECURITY.md](../../SECURITY.md).
