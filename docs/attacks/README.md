# Attack Methodologies

Interplay Adversarial ships seven attack runners in the `red_teaming` package. Each is an async (or subprocess)
function that takes a goal and a target endpoint and returns a result with a best score.
How they relate to each other, and to probe generation, is described in
[METHODOLOGY.md](../METHODOLOGY.md).

| Method | Strategy | Query budget | Details |
|---|---|---|---|
| **Garak** | Broad library of built-in probes | Depends on probes | [garak.md](garak.md) |
| **TAP** | Branch-and-prune search with evaluator pruning | ~15-30 queries | [tap.md](tap.md) |
| **PAIR** | Iterative refinement with attacker + judge loop | ~20 queries | [pair.md](pair.md) |
| **Crescendo** | Multi-turn benign-to-harmful escalation | 5-10 turns | [crescendo.md](crescendo.md) |
| **GOAT** | Dynamic strategy switching with reasoning | ≤5 turns | [goat.md](goat.md) |
| **SLIP** | Target guides its own compromise via BFS | ~8 iterations | [slip.md](slip.md) |
| **Multimodal** | Harmful instruction embedded in an image | 1-3 transforms | [multimodal.md](multimodal.md) |

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
```

Each page above shows the Python call for that runner. All of them need the `red-teaming` extra (`pip install 'interplay-adversarial[red-teaming]'`); Garak also needs the `garak` extra.

## Safety

These runners send adversarial content to the endpoints you configure. Use only targets you own or
are authorized to test, in an isolated environment with throwaway credentials. See
[SECURITY.md](../../SECURITY.md) and the [content policy](../CONTENT_POLICY.md).
