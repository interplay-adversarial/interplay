# Interplay Adversarial

Adversarial and red-teaming library for AI systems: culturally grounded probe generation plus seven attack methodologies. Attacks run against any target that exposes an endpoint compatible with the providers supported by [`any-llm-sdk`](https://github.com/mozilla-ai/any-llm): hosted or self-hosted models, and the agents, tool-using applications and harnesses served behind such an endpoint. Formerly `cultural-bias-red-team`.

Implements the **Singapore AI Safety Red Teaming Challenge methodology** (IMDA + Humane Intelligence, Feb 2025) using [NeMo Data Designer](https://github.com/NVIDIA-NeMo/DataDesigner), plus 7 attack methodologies for comprehensive adversarial testing (see [docs/METHODOLOGY.md](https://github.com/interplay-adversarial/interplay/blob/main/docs/METHODOLOGY.md)).

Start with the [tools, library APIs and use-case guide](docs/tools-and-use-cases.md)
to choose between probe generation, batch/adaptive assessment, legacy attack
runners and Agent Boundary Gate integration. It documents current scoring and
instrumentation limits.

## Install

Requires Python 3.12 or newer.

```bash
pip install interplay-adversarial                    # core: specs and the probe pipeline library
pip install "interplay-adversarial[red-teaming]"     # attack runners: TAP, PAIR, Crescendo, GOAT, SLIP, Multimodal
pip install "interplay-adversarial[garak]"           # + the Garak scanner (large install)
pip install "interplay-adversarial[providers]"       # + 20+ LLM provider SDKs for any-llm-sdk
pip install "interplay-adversarial[all]"             # red-teaming + providers (Garak conflicts with the provider SDKs; install it in its own environment)
```

The package installs the `interplay` Python package (`interplay.specs`, `interplay.red_teaming`) and an `interplay`
command. Probe generation works straight from a pip install:

```bash
interplay modes                                            # singapore, sdg-hub-harm, combined, and comparison specs
interplay probes validate                                  # check the pipeline config (no API key needed)
interplay probes create --mode us-mexico --num-records 200   # extra arguments go to data-designer
```

`preview` and `create` call a model. Define it once (it writes data-designer's config, never the key itself), then
export the key:

```bash
interplay probes setup --base-url https://your-endpoint/v1 --model your-model --api-key-env OPENAI_API_KEY
export OPENAI_API_KEY=...
```

The examples run from a clone of the repository; see Quick Start.

## Why

For arbitrary assessment descriptions, see the new
[description-driven campaign API](docs/assessment.md): separate adversarial,
target and judge models, response/log/trace observations, evidence-cited verdicts,
and matching JSONL/Parquet/Arrow datasets. It is reusable independently of any
boundary gate; existing cultural probe modes and seven attack runners remain separate.

Standard red-teaming focuses on adversarial prompts from an attacker perspective. Singapore's challenge found:

- **86.1%** of successful exploits came from **single-turn benign prompts** — normal everyday user interactions
- **67.2%** exploit success rate in regional languages vs **49.2%** in English
- **Positive framing** ("which city is *richest*?") bypasses more guardrails than negative framing
- Cultural bias appears in daily use, not only adversarial scenarios

This tool generates both probe types, grounded in specific cultural contexts rather than generic demographics, and provides 7 attack methodologies to test how AI systems behave under adversarial pressure.

## Attack Methodologies

| Method | Description | Use Case |
|--------|-------------|----------|
| [**Garak**](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/garak.md) | 100+ built-in probes | Comprehensive vulnerability scanning |
| [**TAP**](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/tap.md) | Tree of Attacks with Pruning | Search-based jailbreak with evaluator pruning |
| [**PAIR**](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/pair.md) | Prompt Automatic Iterative Refinement | Iterative refinement with attacker + judge loop |
| [**Crescendo**](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/crescendo.md) | Multi-turn benign-to-harmful escalation | Gradual escalation using model's own responses |
| [**GOAT**](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/goat.md) | Generative Offensive Agent Tester | Agentic strategy switching with reasoning |
| [**SLIP**](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/slip.md) | Self-Jailbreaking via Lexical Insertion | Target model guides its own compromise |
| [**Multimodal**](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/multimodal.md) | Image payload attacks | Bypass text-only guardrails with image payloads |

Details, parameters and examples for each: [docs/attacks](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/README.md).

## Quick Start

### Probe Generation (Cultural Bias)

With a pip install, use `interplay probes ...` (see Install). From a clone, the same pipeline is available as `pipeline.py`:

```bash
git clone https://github.com/interplay-adversarial/interplay.git
cd interplay

# Install uv if needed: curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --extra red-teaming   # add --extra garak for the Garak scanner

cp .env.example .env        # Add API keys and endpoint configuration

# Validate and preview
uv run data-designer validate pipeline.py
uv run data-designer preview  pipeline.py

# Generate 500 probes (Singapore 9-country taxonomy, default)
uv run data-designer create pipeline.py --num-records 500
```

### Attack Methodologies

```bash
# Set environment variables (or use .env file)
export TARGET_URL="https://your-target/v1"
export TARGET_API_KEY="your-api-key"
export ATTACKER_MODEL="openai/gpt-4o-mini"
export JUDGE_MODEL="openai/gpt-4o-mini"

# Run integrated workflow (Garak + TAP + PAIR)
uv run python examples/integrated_run.py --probe-file probes.jsonl --output-dir output/
```

Each attack can also be called directly from Python; see the page for the method in
[docs/attacks](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/README.md).

## Pipeline Modes (Probe Generation)

Set `BIAS_SPEC` to select the generation mode. Three built-in taxonomy modes and N comparison spec modes.

### Taxonomy Modes

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

| Mode | Categories | Focus |
|---|---|---|
| `singapore` (default) | 5 | Subtle cultural bias in everyday AI interactions (APAC context) |
| `sdg-hub-harm` | 8 | Explicit harm: illegal activity, malware, fraud, violence, etc. |
| `combined` | 13 | Full coverage — both cultural bias and harm categories |

### Comparison Spec Modes (Two-Group)

```bash
# US vs Mexico — national identity + race/ethnicity bias
BIAS_SPEC=us-mexico uv run data-designer create pipeline.py --num-records 200

# US (mainland) vs Puerto Rico — citizenship + national identity
BIAS_SPEC=us-puerto-rico uv run data-designer create pipeline.py --num-records 200

# US White vs US Brown/Latino — intra-US racial bias
BIAS_SPEC=us-white-brown uv run data-designer create pipeline.py --num-records 200
```

## Generating Diverse Datasets

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

## Available Modes and Specs

| `BIAS_SPEC` value | Type | Categories | Description |
|---|---|---|---|
| `singapore` (default) | taxonomy | 5 | Singapore APAC cultural bias taxonomy |
| `sdg-hub-harm` | taxonomy | 8 | SDG Hub original harm policy concepts |
| `combined` | taxonomy | 13 | Singapore 5 + harm 8 — maximum coverage |
| `us-mexico` | comparison | 4 | US Americans vs Mexicans |
| `us-puerto-rico` | comparison | 3 | Mainland US vs Puerto Ricans |
| `us-white-brown` | comparison | 4 | US White (non-Hispanic) vs US Brown/Latino |
| _(your spec)_ | comparison | varies | Any file in `interplay/specs/` |

## Adding a New Comparison

Create `interplay/specs/<name>.py` that exports `SPEC = BiasComparisonSpec(...)`. No other files need to change.

```bash
# After creating the file:
uv run pytest                # validates the spec format
# Open a PR — CI runs automatically
```

Full instructions: [`interplay/specs/CONTRIBUTING.md`](https://github.com/interplay-adversarial/interplay/blob/main/interplay/specs/CONTRIBUTING.md)

## Output (Probe Generation)

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

In comparison mode, also includes `group_1_name`, `group_2_name`, `group_1_ref`, `group_2_ref`, `comparison_topic`.

## Attack Methodologies (Detailed)

Each methodology has its own page with parameters and a runnable example.

| Method | Strategy | Query budget | Details |
|--------|----------|--------------|---------|
| Garak | Broad library of built-in probes | Depends on probes | [docs/attacks/garak.md](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/garak.md) |
| TAP | Branch-and-prune search with evaluator pruning | ~15-30 queries | [docs/attacks/tap.md](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/tap.md) |
| PAIR | Iterative refinement with attacker + judge loop | ~20 queries | [docs/attacks/pair.md](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/pair.md) |
| Crescendo | Multi-turn benign-to-harmful escalation | 5-10 turns | [docs/attacks/crescendo.md](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/crescendo.md) |
| GOAT | Dynamic strategy switching with reasoning | ≤5 turns | [docs/attacks/goat.md](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/goat.md) |
| SLIP | Target guides its own compromise via BFS | ~8 iterations | [docs/attacks/slip.md](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/slip.md) |
| Multimodal | Harmful instruction embedded in an image | 1-3 transforms | [docs/attacks/multimodal.md](https://github.com/interplay-adversarial/interplay/blob/main/docs/attacks/multimodal.md) |

## Configuration

### Environment Variables

Create a `.env` file in the repo root:

```bash
# Target endpoint configuration
TARGET_URL=https://your-target/v1
TARGET_API_KEY=your-api-key
TARGET_MODEL=your-model-name

# Judge model (for scoring)
JUDGE_URL=https://your-target/v1
JUDGE_API_KEY=your-api-key
JUDGE_MODEL=openai/gpt-4o-mini

# Attacker model (for TAP/PAIR/GOAT)
ATTACKER_URL=https://your-target/v1
ATTACKER_API_KEY=your-api-key
ATTACKER_MODEL=openai/gpt-4o-mini

# Provider configuration
LLM_PROVIDER=openai
API_KEY=your-api-key
BASE_URL=https://your-provider/v1
```

### Supported Providers

A target is anything that exposes an endpoint compatible with one of the providers supported by `any-llm-sdk`
(a model, or an agent, tool-using application or harness served behind such an endpoint). The attacks interact
with it through that endpoint, using chat messages and, for the Multimodal runner, images; they do not instrument
tools, harness internals or skills directly.

All providers supported by `any-llm-sdk`:
- OpenAI (default)
- Anthropic
- Google (Gemini)
- Mistral
- Cohere
- Ollama (local)
- vLLM (local/custom)
- And 20+ more

## Development

```bash
uv sync                     # install the project and the dev tools (pytest, ruff, pip-audit)
uv sync --extra red-teaming  # + attack methodology deps (--extra garak for the Garak scanner)
uv run ruff check .         # lint
uv run ruff format .        # format
uv run pytest               # unit tests (no LLM required)
```

## Using with RHOAI / vLLM

```bash
export OPENAI_BASE_URL=https://your-vllm-endpoint/v1
export OPENAI_API_KEY=your-key
export MODEL_NAME=granite-3.3-8b-instruct

uv run data-designer create pipeline.py --num-records 500

# Or for attack methodologies:
export TARGET_URL=https://your-vllm-endpoint/v1
export TARGET_API_KEY=your-key
export ATTACKER_MODEL=granite-3.3-8b-instruct

uv run python examples/integrated_run.py --probe-file probes.jsonl
```

## Methodology

Interplay Adversarial combines culturally grounded probe generation (the **Singapore AI Safety Red Teaming Challenge** approach, IMDA and Humane Intelligence, February 2025) with seven attack methodologies that cover different search strategies, from static probe libraries to multi-turn and multimodal attacks. How they work, when to use each, how they combine, and the references are in [docs/METHODOLOGY.md](https://github.com/interplay-adversarial/interplay/blob/main/docs/METHODOLOGY.md).

## Security and content policy

This project contains adversarial material. Read the [content policy](https://github.com/interplay-adversarial/interplay/blob/main/docs/CONTENT_POLICY.md) before
contributing, and report vulnerabilities privately as described in [SECURITY.md](https://github.com/interplay-adversarial/interplay/blob/main/SECURITY.md).
Use it only against systems you own or are authorized to test.

## Name and affiliation

Interplay Adversarial is an independent open-source project. It is not affiliated with, sponsored by or endorsed by Interplay Entertainment Corp. "Interplay" is a trademark of its respective owner.

## License

Apache 2.0
