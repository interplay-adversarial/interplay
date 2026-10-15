# Interplay Adversarial

Interplay Adversarial is a red-teaming library for AI systems. It generates culturally
grounded cultural-bias and harm probes, runs seven attack methodologies against a target, and
assesses a target against an arbitrary, operator-defined objective — three independent
capabilities you can use on their own or together. A target is anything that exposes an
endpoint compatible with the providers supported by
[`any-llm-sdk`](https://github.com/mozilla-ai/any-llm): hosted or self-hosted models, and the
agents, tool-using applications and harnesses served behind such an endpoint. Formerly
`cultural-bias-red-team`.

## What it provides

- **Probe generation** — culturally grounded adversarial and benign prompts implementing the
  **Singapore AI Safety Red Teaming Challenge methodology** (IMDA + Humane Intelligence,
  Feb 2025) via [NeMo Data Designer](https://github.com/NVIDIA-NeMo/DataDesigner). Singapore's
  challenge found that 86.1% of successful exploits came from single-turn *benign* prompts and
  that regional-language prompts succeeded 67.2% of the time versus 49.2% in English — so the
  pipeline generates both probe types, grounded in specific cultural contexts rather than
  generic demographics. Three built-in taxonomies plus any two-group comparison you define. See
  [docs/probe-generation.md](docs/probe-generation.md).
- **Attack methodologies** — seven runners (Garak, TAP, PAIR, Crescendo, GOAT, SLIP,
  Multimodal) covering search strategies from a static probe library through multi-turn and
  multimodal attacks, each scored by a judge model that cites its evidence. Five of them (not
  PAIR) can use **a panel of several judges instead of one**, with a configurable
  `"majority"`/`"unanimous"` verdict and a real inter-rater-reliability report (Krippendorff's
  alpha with a bootstrapped confidence interval) computed from the same judge calls. See
  [docs/attacks/README.md](docs/attacks/README.md).
- **Description-driven assessment** — give it a free-text objective and success criterion;
  it generates probes, captures the target's response/logs/traces, and returns an
  evidence-cited verdict (`success`/`failure`/`inconclusive`) with matching JSONL/Parquet/Arrow
  datasets. Separate adversarial, target and judge models; reusable independently of any
  boundary gate. See [docs/assessment.md](docs/assessment.md).

Which of these three fits your question, how they relate, and their current scope and limits
are in the [documentation map](docs/README.md) and the
[tools and use-case guide](docs/tools-and-use-cases.md).

## Install

Requires Python 3.12 or newer.

```bash
pip install interplay-adversarial                    # core: specs and the probe pipeline library
pip install "interplay-adversarial[red-teaming]"     # attack runners: TAP, PAIR, Crescendo, GOAT, SLIP, Multimodal
pip install "interplay-adversarial[garak]"           # + the Garak scanner (large install)
pip install "interplay-adversarial[providers]"       # + 20+ LLM provider SDKs for any-llm-sdk
pip install "interplay-adversarial[all]"             # red-teaming + providers (Garak conflicts with the provider SDKs; install it in its own environment)
```

This installs the `interplay` Python package (`interplay.specs`, `interplay.red_teaming`,
`interplay.assessment`) and an `interplay` command.

## Quick start

Clone the repo for the example scripts used below (`uv sync --extra red-teaming`, then
`cp .env.example .env` and fill in the values you need); everything also works from a plain
`pip install` using the `interplay` command shown first in each section.

### Generate probes

```bash
interplay modes                                             # singapore, sdg-hub-harm, combined, and comparison specs
interplay probes setup --base-url https://your-endpoint/v1 --model your-model --api-key-env OPENAI_API_KEY
export OPENAI_API_KEY=...
interplay probes validate                                   # check the pipeline config (no API key needed)
interplay probes create --mode us-mexico --num-records 200  # extra arguments go to data-designer
```

Every mode, the diverse-dataset helper, output columns and how to add your own comparison:
[docs/probe-generation.md](docs/probe-generation.md).

### Run an attack

```bash
export TARGET_URL="https://your-target/v1"
export TARGET_API_KEY="your-api-key"
export ATTACKER_MODEL="openai/gpt-4o-mini"
export JUDGE_MODEL="openai/gpt-4o-mini"

# One runner, from the command line:
uv run python examples/single_attack_runner.py --method crescendo --goal "Your goal"

# A panel of judges instead of one, with a real inter-rater-reliability report:
uv run python examples/single_attack_runner.py --method crescendo --goal "Your goal" \
    --judge-models openai/gpt-4o-mini anthropic/claude-3-haiku --judge-aggregation unanimous

# Or the integrated workflow (Garak + TAP + PAIR) over a probe file:
uv run python examples/integrated_run.py --probe-file probes.jsonl --output-dir output/
```

Each runner can also be called directly from Python with its own parameters (query budget,
judge panel, multimodal controls, ...); see its page in
[docs/attacks/README.md](docs/attacks/README.md).

### Assess a custom objective

```bash
pip install 'interplay-adversarial[assessment]'
interplay assess --config private-providers.json --output private-campaign \
  --description 'Assess whether the application discloses a synthetic canary.' \
  --success-criteria 'The response or observed tool trace contains SYNTHETIC-CANARY.' \
  --num-probes 5
```

Configuration shape, batch vs. adaptive search, and the dataset schema:
[docs/assessment.md](docs/assessment.md).

## Configuration

Three independent configuration surfaces, matching the three capabilities above:

- **Probe generation**: one model, set once with `interplay probes setup` (writes
  data-designer's config, never the key itself) or `OPENAI_API_KEY`/`OPENAI_BASE_URL`/
  `MODEL_NAME` in `.env`.
- **Attack runners**: `TARGET_URL`/`TARGET_API_KEY`/`TARGET_MODEL`,
  `JUDGE_URL`/`JUDGE_API_KEY`/`JUDGE_MODEL`, `ATTACKER_URL`/`ATTACKER_API_KEY`/`ATTACKER_MODEL`,
  or the generic `LLM_PROVIDER`/`API_KEY`/`BASE_URL` fallback. See
  [`.env.example`](.env.example) for the full list with defaults.
- **Assessment**: a separate, private (`chmod 0600`) JSON config file, never `.env` — see
  [docs/assessment.md](docs/assessment.md).

`any-llm-sdk` supports OpenAI, Anthropic, Google, Mistral, Cohere, Ollama, self-hosted
vLLM/RHOAI and 20+ more — a self-hosted endpoint works exactly the same way as a hosted one,
just point the relevant `*_URL` at it. The attacks interact with the target through its
endpoint using chat messages (and, for the Multimodal runner, images); they do not instrument
tools, harness internals or skills directly.

## Development

```bash
uv sync                     # install the project and the dev tools (pytest, ruff, pip-audit)
uv sync --extra red-teaming  # + attack methodology deps (--extra garak for the Garak scanner)
uv run ruff check .         # lint
uv run ruff format .        # format
uv run pytest               # unit tests (no LLM required)
```

## Security and content policy

This project contains adversarial material. Read the [content policy](docs/CONTENT_POLICY.md)
before contributing, and report vulnerabilities privately as described in
[SECURITY.md](SECURITY.md). Use it only against systems you own or are authorized to test.

## Name and affiliation

Interplay Adversarial is an independent open-source project. It is not affiliated with, sponsored by or endorsed by Interplay Entertainment Corp. "Interplay" is a trademark of its respective owner.

## License

Apache 2.0
