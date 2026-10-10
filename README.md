# cultural-bias-red-team

Synthetic red-team probe generation for evaluating cultural bias in LLMs, expanded to full-spectrum adversarial red teaming.

Implements the **Singapore AI Safety Red Teaming Challenge methodology** (IMDA + Humane Intelligence, Feb 2025) using [NeMo Data Designer](https://github.com/NVIDIA-NeMo/DataDesigner), plus 7 attack methodologies for comprehensive adversarial testing.

## Why

Standard red-teaming focuses on adversarial prompts from an attacker perspective. Singapore's challenge found:

- **86.1%** of successful exploits came from **single-turn benign prompts** — normal everyday user interactions
- **67.2%** exploit success rate in regional languages vs **49.2%** in English
- **Positive framing** ("which city is *richest*?") bypasses more guardrails than negative framing
- Cultural bias appears in daily use, not only adversarial scenarios

This tool generates both probe types, grounded in specific cultural contexts rather than generic demographics, and provides 7 attack methodologies to test model robustness.

## Attack Methodologies

| Method | Description | Use Case |
|--------|-------------|----------|
| **Garak** | 100+ built-in probes | Comprehensive vulnerability scanning |
| **TAP** | Tree of Attacks with Pruning | Search-based jailbreak with evaluator pruning |
| **PAIR** | Prompt Automatic Iterative Refinement | Iterative refinement with attacker + judge loop |
| **Crescendo** | Multi-turn benign-to-harmful escalation | Gradual escalation using model's own responses |
| **GOAT** | Generative Offensive Agent Tester | Agentic strategy switching with reasoning |
| **SLIP** | Self-Jailbreaking via Lexical Insertion | Target model guides its own compromise |
| **Multimodal** | Image payload attacks | Bypass text-only guardrails with image payloads |

## Quick Start

### Probe Generation (Cultural Bias)

```bash
git clone https://github.com/williamcaban/cultural-bias-red-team.git
cd cultural-bias-red-team

# Install uv if needed: curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync --extra red-teaming

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

# Or run individual attacks
uv run python -c "
from red_teaming import tap_attack, crescendo_attack
import asyncio

async def main():
    result = await tap_attack(
        goal='Your attack goal here',
        target_url='https://your-target/v1',
        attacker_model='openai/gpt-4o-mini',
        evaluator_model='openai/gpt-4o-mini',
    )
    print(f'ASR: {result.best_score}')

asyncio.run(main())
"
```

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
| _(your spec)_ | comparison | varies | Any file in `specs/` |

## Adding a New Comparison

Create `specs/<name>.py` that exports `SPEC = BiasComparisonSpec(...)`. No other files need to change.

```bash
# After creating the file:
uv run pytest                # validates the spec format
# Open a PR — CI runs automatically
```

Full instructions: [`specs/CONTRIBUTING.md`](specs/CONTRIBUTING.md)

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

### TAP (Tree of Attacks with Pruning)

**Strategy**: Branch-and-prune search with evaluator pruning  
**Query Budget**: ~15-30 queries  
**Key Feature**: Evaluator LLM prunes weak branches before target query

```python
from red_teaming import tap_attack
import asyncio


async def main():
    result = await tap_attack(
        goal="Your attack goal",
        target_url="https://your-target/v1",
        attacker_model="openai/gpt-4o-mini",
        evaluator_model="openai/gpt-4o-mini",
        n_iterations=5,
        beam_width=10,
        branching_factor=3,
    )
    print(f"Best ASR: {result.best_score}")
    print(f"Search trajectory: {len(result.search_trajectory)} iterations")


asyncio.run(main())
```

### PAIR (Prompt Automatic Iterative Refinement)

**Strategy**: Iterative refinement with attacker + judge loop  
**Query Budget**: ~20 queries  
**Key Feature**: Attacker refines based on conversation history + CoT improvement

```python
from red_teaming import pair_attack
import asyncio


async def main():
    result = await pair_attack(
        goal="Your attack goal",
        target_url="https://your-target/v1",
        attacker_model="openai/gpt-4o-mini",
        judge_model="openai/gpt-4o-mini",
        max_queries=20,
    )
    print(f"Best ASR: {result.best_score}")
    print(f"Query count: {result.query_count}")


asyncio.run(main())
```

### Crescendo

**Strategy**: Multi-turn benign-to-harmful escalation  
**Query Budget**: 5-10 turns  
**Key Feature**: Uses model's own responses to guide escalation

```python
from red_teaming import crescendo_attack
import asyncio


async def main():
    result = await crescendo_attack(
        goal="Your attack goal",
        target_url="https://your-target/v1",
        attacker_model="openai/gpt-4o-mini",
        max_turns=10,
    )
    print(f"Best ASR: {result.best_score}")
    print(f"Turns: {result.turns}")


asyncio.run(main())
```

### GOAT (Generative Offensive Agent Tester)

**Strategy**: Dynamic strategy switching with reasoning  
**Query Budget**: ≤5 turns  
**Key Feature**: Attacker reasons about best strategy per turn

```python
from red_teaming import goat_attack
import asyncio


async def main():
    result = await goat_attack(
        goal="Your attack goal",
        target_url="https://your-target/v1",
        attacker_model="openai/gpt-4o-mini",
        max_turns=5,
    )
    print(f"Best ASR: {result.best_score}")
    print(f"Strategy trajectory: {result.strategy_trajectory}")


asyncio.run(main())
```

### SLIP (Self-Jailbreaking via Lexical Insertion)

**Strategy**: Target model guides its own compromise via BFS  
**Query Budget**: ~8 iterations  
**Key Feature**: Lexical insertion of goal words into benign prompts

```python
from red_teaming import slip_attack
import asyncio


async def main():
    result = await slip_attack(
        goal="Your attack goal",
        target_url="https://your-target/v1",
        target_model="your-model",
        max_iterations=8,
    )
    print(f"Best ASR: {result.best_score}")
    print(f"Iterations: {result.iterations}")


asyncio.run(main())
```

### Multimodal (Image Payload)

**Strategy**: Embed harmful instruction in image  
**Query Budget**: 1-3 transforms  
**Key Feature**: Bypass text-only guardrails

```python
from red_teaming import multimodal_attack
import asyncio


async def main():
    result = await multimodal_attack(
        goal="Your attack goal",
        vision_target_url="https://vision-target/v1",
        vision_model="openai/gpt-4o",
        transforms=["plain", "base64", "leetspeak"],
    )
    print(f"Best ASR: {result.best_score}")
    print(f"Image path: {result.image_path}")


asyncio.run(main())
```

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
uv sync                     # install all deps
uv sync --extra red-teaming  # + attack methodology deps
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

**Singapore AI Safety Red Teaming Challenge** — world's first multicultural, multilingual AI safety red teaming exercise. 9 countries, 54 in-person experts + 308 virtual participants, 1,335–1,887 successful exploits per round.

**Source:** [IMDA Evaluation Report, February 2025](https://www.imda.gov.sg/-/media/imda/files/about/emerging-tech-research/artificial-intelligence/singapore-ai-safety-red-teaming-challenge-evaluation-report.pdf)

## Attack Methodology References

- **TAP**: Mehrotra et al., NeurIPS 2024 (arXiv:2312.02119)
- **PAIR**: Chao et al., NeurIPS 2023 (arXiv:2310.08419)
- **Crescendo**: Russinovich et al., USENIX Security 2025 (arXiv:2404.01833)
- **GOAT**: Pavlova et al., 2024 (arXiv:2410.01606)
- **SLIP**: arXiv:2601.02670

## License

Apache 2.0
