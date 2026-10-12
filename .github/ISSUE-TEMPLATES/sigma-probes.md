---
name: SIGMA Spec-Aligned Probes
about: Test self-improving agents against spec-derived alignment signals
title: 'feat: Add SIGMA spec-aligned self-improvement probes'
labels: ['enhancement', 'security', 'self-improvement']
assignees: williamcaban
---

## Summary

Add probes to evaluate Self-Improving Alignment Generalization from Model Specs (SIGMA) — preventing capability/alignment divergence in recursive self-improvement loops.

## Motivation

**Source**: arXiv:2610.07935 — "SIGMA: Self-Improving Alignment Generalization from a Model Spec" (Oct 7, 2026)

**Problem**: LLM agents can recursively improve themselves on **easy-to-verify objectives** (software engineering, mathematics) but **alignment objectives are harder to verify**. Self-improvement loops raise capability while alignment silently lags, creating a widening verification gap.

**Proposal**: Derive alignment training signal directly from a **written model specification**, anchoring the improvement loop to an auditable artifact rather than proxy metrics that self-improvement can game.

## Proposed Implementation

Add `SIGMAProbe` class in `interplay/red_teaming/`:

```python
class SIGMAProbe:
    """Test self-improving agents against spec-derived alignment signals."""
    
    def run(self, num_iterations: int = 10) -> SIGMAResult:
        """
        Run self-improvement loop and measure:
        - Capability trajectory (task performance)
        - Alignment trajectory (spec adherence)
        - Divergence gap (capability - alignment)
        """
```

## Acceptance Criteria

- [ ] `SIGMAProbe` class in `interplay/red_teaming/`
- [ ] `SIGMAResult` Pydantic model
- [ ] Integration with interplay pipeline
- [ ] Unit tests with mock harness/loop
- [ ] Example spec: `specs/sigma_spec.py`

## References

- arXiv:2610.07935 — SIGMA (Oct 7, 2026)

---
Signed-off-by: William Caban <william.caban@gmail.com>
