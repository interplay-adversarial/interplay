# AGENTS.md — Interplay

Guidance for AI agents working on this repository.

## What this repo does

Generates synthetic red-team probes for evaluating cultural bias in LLMs, using the
Singapore AI Safety Red Teaming Challenge methodology (IMDA + Humane Intelligence, Feb 2025).

Two modes:
- **Singapore mode** (default): 9-country APAC taxonomy, 5 bias categories
- **Comparison mode**: any two-group comparison defined in `interplay/specs/`

Both modes produce adversarial + benign probes in a single DataDesigner run via `SkipConfig`.

## Repository structure

```
pipeline.py          # DataDesigner pipeline — load_config_builder() is the CLI entry point
interplay/           # the installable package (distribution name: interplay-adversarial)
  specs/
    __init__.py      # load_spec(slug) + list_specs()
    models.py        # BiasGroup + BiasComparisonSpec Pydantic models
    singapore.py     # Singapore 9-country taxonomy (DataFrame + CATEGORY_DEFINITIONS)
    us_mexico.py     # SPEC = BiasComparisonSpec(...)
    us_puerto_rico.py  # SPEC = ...
    us_white_brown.py  # SPEC = ...
    CONTRIBUTING.md  # how to add a new spec
  red_teaming/       # attack runners (TAP, PAIR, Crescendo, GOAT, SLIP, Multimodal, Garak)
tests/
  test_specs.py      # runs without data-designer; validates spec format
examples/
  custom_spec.py     # end-to-end example of defining and running a custom spec
```

## Development setup

```bash
uv sync                     # install all deps including dev
uv run ruff check .         # lint
uv run ruff format .        # format
uv run pytest               # run tests (no LLM calls required)
```

## Running the pipeline

```bash
cp .env.example .env        # add OPENAI_API_KEY and optionally OPENAI_BASE_URL, MODEL_NAME

# Validate and preview (no LLM calls for validate):
uv run data-designer validate pipeline.py
uv run data-designer preview  pipeline.py

# Taxonomy modes:
uv run data-designer create pipeline.py --num-records 500                            # singapore (default, 5 categories)
BIAS_SPEC=sdg-hub-harm  uv run data-designer create pipeline.py --num-records 400   # harm 8 only
BIAS_SPEC=combined      uv run data-designer create pipeline.py --num-records 800   # all 13 categories

# Comparison spec modes:
BIAS_SPEC=us-mexico      uv run data-designer create pipeline.py --num-records 200
BIAS_SPEC=us-puerto-rico uv run data-designer create pipeline.py --num-records 200
BIAS_SPEC=us-white-brown uv run data-designer create pipeline.py --num-records 200
BIAS_SPEC=my_spec        uv run data-designer create pipeline.py --num-records 100  # custom spec

# Diverse multi-mode dataset:
uv run python examples/diverse_dataset.py --preview-only   # sanity check
uv run python examples/diverse_dataset.py                  # generates ~720 probes
```

## Adding a new spec

1. Create `interplay/specs/<name>.py` — must export `SPEC: BiasComparisonSpec`
2. Run `uv run pytest` — tests validate the spec automatically
3. Open a PR — CI runs `data-designer validate` and `pytest`

See `interplay/specs/CONTRIBUTING.md` for the full spec template and requirements.

## Code conventions

- Python 3.13+, Pydantic v2
- `ruff` for linting and formatting — run before committing
- All custom column generators must be decorated with `@dd.custom_column_generator`
  and declared at **module level** (not inside functions)
- Pydantic schemas must be **flat** — no nested BaseModel fields in output schemas
  (DataDesigner structured output degrades with nested schemas)
- `generator_params` in `CustomColumnConfig` is the correct way to pass runtime data
  to generators — never use closures or global state

## What NOT to do

- Do not add `generator_params` closures — always pass data via `generator_params=` in `CustomColumnConfig`
- Do not define `@dd.custom_column_generator` functions inside `build_*` functions
- Do not modify `pipeline.py` to add new spec data — all spec data belongs in `interplay/specs/`
- Do not use nested Pydantic models in `AdversarialProbe` or `BenignProbe`
- Do not store actual slurs in `stereotypes_to_probe` — describe the bias pattern, not the slur itself

## Key design decisions

**SkipConfig two-mode pattern**: One `dd.create()` call, one checkpoint. `probe_mode` sampler
column (adversarial/benign) activates the corresponding LLM column via `SkipConfig`.

**generator_params for spec data**: All comparison spec data flows to custom generators via
`generator_params=spec` in `CustomColumnConfig`, never via module-level globals.

**Flat Pydantic schemas**: DataDesigner structured output reliability degrades with nested models.
`AdversarialProbe` and `BenignProbe` are flat — all fields are `str` or `Optional[str]`.

**Singapore mode stays separate**: The Singapore 9-country taxonomy is not a `BiasComparisonSpec`
(it has 5 categories, not 2 groups). `build_cultural_bias_pipeline()` handles it directly;
`build_comparison_pipeline(spec)` handles arbitrary two-group comparisons.
