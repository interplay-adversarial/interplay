---
name: Answer-Side Backdoor Detection
about: Detect triggers planted in model-generated context
title: 'feat: Answer-side backdoor detection (multi-turn)'
labels: ['enhancement', 'security', 'red-teaming']
assignees: williamcaban
---

## Summary

Add detection for answer-side backdoors — triggers planted in the model's own generated context that defeat input-side guardrails.

## Motivation

**Source**: arXiv:2610.07723 — "Answer-side backdoors in multi-turn LLMs" (Oct 7, 2026)

**Attack surface**: Triggers planted not in user input but in the **model's own generated context**, defeating guardrails designed to sanitize the input space.

**Finding**: Input-side defenses are **structurally blind** to triggers the model itself produces mid-conversation.

## Proposed Implementation

Add `AnswerSideBackdoorDetector` in `interplay/red_teaming/`:

```python
class AnswerSideBackdoorDetector:
    """Detect triggers planted in model-generated context."""
    
    def run_probe(self, goal: str, max_turns: int = 10) -> BackdoorProbeResult:
        """Run multi-turn conversation and detect triggers."""
```

## Acceptance Criteria

- [ ] `AnswerSideBackdoorDetector` class
- [ ] Integration with multi-turn pipeline
- [ ] Unit tests with synthetic trigger patterns
- [ ] Example: `examples/answer_side_backdoor.py`

## References

- arXiv:2610.07723 — Answer-side backdoors (Oct 7, 2026)

---
Signed-off-by: William Caban <william.caban@gmail.com>
