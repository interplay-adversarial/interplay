---
name: Package Hallucination Probe
about: Detect package-hallucination attacks via trusted rule files
title: 'feat: Package-hallucination attack probes (rule-file injection)'
labels: ['enhancement', 'security', 'red-teaming']
assignees: williamcaban
---

## Summary

Add probes to detect package-hallucination attacks mounted through trusted developer rule files (AGENTS.md, .cursorrules, etc.).

## Motivation

**Source**: Daily AI Briefing Oct 8, 2026

**Attack vector**: Attacker plants instructions in shared rule files that steer the coding agent toward **hallucinating a package name** the attacker has pre-registered, converting developer-style guidance files into a **software supply-chain vector**.

**Novelty**: Rule files are treated as **trusted developer intent** rather than untrusted content — same trust-boundary confusion as indirect prompt injection, but with **direct code-execution consequences**.

## Proposed Implementation

Add `PackageHallucinationProbe` class in `interplay/red_teaming/`:

```python
class PackageHallucinationProbe:
    """Test agents for package-hallucination vulnerabilities via rule files."""
    
    def run(self, agent: CodingAgent, task: str) -> HallucinationResult:
        """Test whether agent hallucinates attacker's package from rule file."""
```

## Acceptance Criteria

- [ ] `PackageHallucinationProbe` class
- [ ] Attack pattern library (4+ patterns)
- [ ] Integration with interplay pipeline
- [ ] Unit tests with mock coding agent
- [ ] Example: `examples/package_hallucination_attack.py`

## References

- Daily AI Briefing Oct 8, 2026 — "Package hallucination attacks via AGENTS.md/.cursorrules"

---
Signed-off-by: William Caban <william.caban@gmail.com>
