# Attack Methodologies

[← Documentation map](../README.md) · [Methodology](../METHODOLOGY.md) · [Tools and use cases](../tools-and-use-cases.md)

Interplay Adversarial ships seven attack runners in the `red_teaming` package. Each is an async (or subprocess)
function that takes a goal and a target endpoint and returns a result with a best score.
How they relate to each other, and to probe generation, is described in
[METHODOLOGY.md](../METHODOLOGY.md).

| Method | Strategy | Query budget | Details |
|---|---|---|---|
| **Garak** | Broad library of built-in probes | Depends on probes | [garak.md](garak.md) |
| **TAP** | Branch-and-prune search, evaluator pruning, judged target execution | beam_width (≤10) x n_iterations (≤10) admitted-branch queries | [tap.md](tap.md) |
| **PAIR** | Iterative refinement with attacker + judge loop | ~20 queries | [pair.md](pair.md) |
| **Crescendo** | Multi-turn benign-to-harmful escalation | 5-10 turns | [crescendo.md](crescendo.md) |
| **GOAT** | Dynamic strategy switching with reasoning | ≤5 turns | [goat.md](goat.md) |
| **SLIP** | Bounded lexical insertion then target-assisted refinement, judged target execution | up to (max_words + refine_rounds) x max_candidates_per_round admitted-candidate queries | [slip.md](slip.md) |
| **Multimodal** | Transformed instruction embedded in an image, with explicit text/image controls, judged target execution | transforms (≤8) x controls (≤8) queries | [multimodal.md](multimodal.md) |

## Running them

Set the target, attacker and judge endpoints (see the
[README configuration section](../../README.md#configuration)), then either run the integrated
workflow or call a runner directly:

```bash
export TARGET_URL="https://your-target/v1"
export TARGET_API_KEY="your-api-key"
export ATTACKER_MODEL="openai/gpt-4o-mini"
export JUDGE_MODEL="openai/gpt-4o-mini"

# Integrated workflow (Garak + TAP + PAIR) over a probe file
uv run python examples/integrated_run.py --probe-file probes.jsonl --output-dir output/

# Or run one runner directly from the command line, optionally with a panel of judges:
uv run python examples/single_attack_runner.py --method crescendo --goal "Your goal" \
    --judge-models openai/gpt-4o-mini anthropic/claude-3-haiku --judge-aggregation unanimous
```

Each page above shows the Python call for that runner. All of them need the `red-teaming` extra (`pip install 'interplay-adversarial[red-teaming]'`); Garak also needs the `garak` extra.

All six method runners accept more than one judge model
(`secondary_judge_models`) to form a panel instead of a single judge, with a
configurable `judge_aggregation` (`"majority"`/`"unanimous"`) and a real
inter-rater-reliability report (`result.irr_report`). See
[tap.md § Current behavior](tap.md#current-behavior) for the full semantics.

## Safety

These runners send adversarial content to the endpoints you configure. Use only targets you own or
are authorized to test, in an isolated environment with throwaway credentials. See
[SECURITY.md](../../SECURITY.md) and the [content policy](../CONTENT_POLICY.md).

For explicit per-role credentials, durable datasets and offline CLI recovery, see
[Run, retain and recover method evaluations](runner-results.md).
