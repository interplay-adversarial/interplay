# Probe generation (cultural bias and harm)

[← Documentation map](README.md) · [Methodology](METHODOLOGY.md)

This page is the deep dive for `interplay probes ...` / `pipeline.py`: every
built-in mode, how to combine them, the output columns, and how to add your
own comparison. For the two-command quick start, see the
[README](../README.md#quick-start).

## Pipeline modes

Set `BIAS_SPEC` to select the generation mode (default `singapore`). Three
built-in taxonomy modes and any number of comparison spec modes.

### Taxonomy modes

```bash
# Singapore 5-category cultural bias (default)
# Categories: Gender, Geographic/National Identity, Race/Religion/Ethnicity,
#             Socio-Economic, Unique Cultural Challenges
uv run data-designer create pipeline.py --num-records 500

# SDG Hub 8 harm-category policy concepts
# Categories: Illegal Activity, Hate Speech, Security & Malware, Violence,
#             Fraud, Sexually Explicit, Misinformation, Self Harm
BIAS_SPEC=sdg-hub-harm uv run data-designer create pipeline.py --num-records 400

# All 13 categories combined (Singapore 5 + harm 8)
# Most diverse single run — covers both subtle cultural bias and explicit harm
BIAS_SPEC=combined uv run data-designer create pipeline.py --num-records 800
```

### Comparison spec modes (two-group)

```bash
# US vs Mexico — national identity + race/ethnicity bias
BIAS_SPEC=us-mexico uv run data-designer create pipeline.py --num-records 200

# US (mainland) vs Puerto Rico — citizenship + national identity
BIAS_SPEC=us-puerto-rico uv run data-designer create pipeline.py --num-records 200

# US White vs US Brown/Latino — intra-US racial bias
BIAS_SPEC=us-white-brown uv run data-designer create pipeline.py --num-records 200
```

### Available modes and specs

| `BIAS_SPEC` value | Type | Categories | Description |
|---|---|---|---|
| `singapore` (default) | taxonomy | 5 | Singapore APAC cultural bias taxonomy |
| `sdg-hub-harm` | taxonomy | 8 | SDG Hub original harm policy concepts |
| `combined` | taxonomy | 13 | Singapore 5 + harm 8 — maximum coverage |
| `us-mexico` | comparison | 4 | US Americans vs Mexicans |
| `us-puerto-rico` | comparison | 3 | Mainland US vs Puerto Ricans |
| `us-white-brown` | comparison | 4 | US White (non-Hispanic) vs US Brown/Latino |
| _(your spec)_ | comparison | varies | Any file in `interplay/specs/` |

## Generating diverse datasets

Run multiple modes and merge results for maximum probe coverage:

```bash
uv run python examples/diverse_dataset.py --preview-only   # sanity check first
uv run python examples/diverse_dataset.py                  # generates ~720 probes
```

This runs Singapore + SDG Hub harm + US-Mexico + US White/Brown and merges into
`diverse_red_team_dataset.jsonl` (Garak-compatible format).

Customize runs by editing the `runs` list in `examples/diverse_dataset.py`:

```python
runs = [
    ("singapore", build_cultural_bias_pipeline(), 200),
    ("sdg-hub-harm", build_harm_pipeline(), 320),
    ("combined", build_combined_pipeline(), 500),  # or use this for broadest coverage
    ("us-mexico", build_comparison_pipeline(load_spec("us-mexico")), 100),
    ("us-white-brown", build_comparison_pipeline(load_spec("us-white-brown")), 100),
]
```

## Adding a new comparison

Create `interplay/specs/<name>.py` that exports `SPEC = BiasComparisonSpec(...)`.
No other files need to change.

```bash
# After creating the file:
uv run pytest                # validates the spec format
# Open a PR — CI runs automatically
```

Full instructions, including the minimum field requirements enforced by
tests: [`interplay/specs/CONTRIBUTING.md`](../interplay/specs/CONTRIBUTING.md).

## Output

Each probe row includes:

| Column | Description |
|---|---|
| `policy_concept` | Bias category (e.g., "Gender Bias") |
| `probe_mode` | `adversarial` or `benign` |
| `region` | Geographic context grounding the probe |
| `prompt_strategy` | Singapore strategy used (fill-in-blank, positive-framing, etc.) |
| `adversarial_probe` | Structured output with `prompt` + explanations (when mode=adversarial) |
| `benign_probe` | Structured output with `prompt` + `why_benign` + `bias_mechanism` (when mode=benign) |
| `probe_quality_score` | 0–3 score from LLM judge (Singapore RT-SG-05 sliding scale) |
| `*__trace` | Audit trail — exact system prompt + rendered user prompt sent to model |

In comparison mode, also includes `group_1_name`, `group_2_name`, `group_1_ref`,
`group_2_ref`, `comparison_topic`.

`probe_quality_score` measures the generated probe's quality under the
pipeline's rubric; it is not a verdict about a target's response. For that,
see the [description-driven assessment API](assessment.md) or the
[attack runners](attacks/README.md).
