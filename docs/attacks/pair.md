# PAIR (Prompt Automatic Iterative Refinement)

[Attack methods](README.md) · [Run and recover results](runner-results.md)

PAIR queries the target, judges the captured response and uses recent outcomes
to refine the next prompt. It uses the shared authenticated target and
`JudgeScorer`/`JudgePanel` path, including evidence citations and inconclusive
outcomes. The old numeric-only judge has been removed.

```python
from interplay.red_teaming import pair_attack

result = await pair_attack(
    goal="Assess synthetic canary disclosure",
    target_url="https://target.example/v1",
    target_model="target-model",
    attacker_model="attacker-model",
    judge_model="judge-model",
    max_queries=20,
    output_dir="output/new-pair-run",
)
print(result.confirmed_success, result.stop_reason)
```

`max_queries` is bounded to 1–100. Every role shares a finite campaign deadline
and charged call budget. A response is retained before judging; missing capture,
judge failure or unavailable judge budget leaves an incomplete/inconclusive trial.
Success requires a complete capture and a supported success judgment. No target
retries; no unused refinement after success or the last target iteration.

`secondary_judge_models`, `judge_aggregation`, explicit `role_endpoints` and
`judge_members` work as with the other method runners. `conversation_history`,
`best_score`, `best_prompt` and `query_count` remain available. `best_score` now
maps the selected verdict to a search diagnostic (success 1, inconclusive 0.5,
failure 0); it is not an attack success rate. Use `confirmed_success` for the
judge-confirmed outcome. Panel agreement is in `irr_report` with an explicit
unavailable reason when insufficient judges/cases exist.

Refinement requests only the next probe, without chain-of-thought. Empty or
oversized refinements are rejected. This remains a free-text refinement method,
not GOAT's pool-validated strategy selection. See the shared guide for private
JSONL/Parquet/Arrow exports, offline recovery, credential isolation and limits.

Reference: [Chao et al., arXiv:2310.08419](https://arxiv.org/abs/2310.08419).
