"""Run any one of the six attack-method runners against a target from the
command line, with one shared argument set.

Crescendo, GOAT, SLIP and Multimodal have no other runnable example in this
repository -- examples/integrated_run.py only calls Garak, TAP and PAIR. This
script covers all six; see the matching page under docs/attacks/ for what
"Current behavior" to expect from each (query budget, judging, no-retry
semantics) before reading its result.

Usage:
    export TARGET_URL="https://your-target/v1"
    export TARGET_API_KEY="your-api-key"
    export ATTACKER_MODEL="openai/gpt-4o-mini"
    export JUDGE_MODEL="openai/gpt-4o-mini"

    uv run python examples/single_attack_runner.py --method crescendo --goal "Your goal"
    uv run python examples/single_attack_runner.py --method goat --goal "Your goal" --max-turns 3

SLIP needs its own target model name (it never falls back to ATTACKER_MODEL):

    uv run python examples/single_attack_runner.py --method slip --goal "Your goal" \\
        --target-model your-model-name

Multimodal needs the `multimodal` extra for Pillow
(`pip install 'interplay-adversarial[red-teaming,multimodal]'`) and talks to
`--target-url`/`--target-model` as a vision-capable endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import asdict, is_dataclass

from dotenv import load_dotenv

from interplay.red_teaming import (
    crescendo_attack,
    goat_attack,
    multimodal_attack,
    pair_attack,
    slip_attack,
    tap_attack,
)

load_dotenv()

METHODS = ("tap", "pair", "crescendo", "goat", "slip", "multimodal")


async def run_method(
    method: str,
    *,
    goal: str,
    target_url: str,
    target_model: str | None,
    attacker_model: str | None,
    judge_model: str | None,
    api_key: str | None,
    max_turns: int,
):
    if method == "tap":
        return await tap_attack(
            goal=goal,
            target_url=target_url,
            target_model=target_model,
            attacker_model=attacker_model,
            evaluator_model=attacker_model,
            judge_model=judge_model,
            api_key=api_key,
        )
    if method == "pair":
        return await pair_attack(
            goal=goal,
            target_url=target_url,
            target_model=target_model,
            attacker_model=attacker_model,
            judge_model=judge_model,
            api_key=api_key,
        )
    if method == "crescendo":
        return await crescendo_attack(
            goal=goal,
            target_url=target_url,
            target_model=target_model,
            attacker_model=attacker_model,
            judge_model=judge_model,
            max_turns=max_turns,
            api_key=api_key,
        )
    if method == "goat":
        return await goat_attack(
            goal=goal,
            target_url=target_url,
            target_model=target_model,
            attacker_model=attacker_model,
            judge_model=judge_model,
            max_turns=max_turns,
            api_key=api_key,
        )
    if method == "slip":
        if not target_model:
            raise SystemExit("--method slip requires --target-model (it has no env fallback)")
        return await slip_attack(
            goal=goal,
            target_url=target_url,
            target_model=target_model,
            refiner_model=attacker_model,
            judge_model=judge_model,
            api_key=api_key,
        )
    if method == "multimodal":
        return await multimodal_attack(
            goal=goal,
            vision_target_url=target_url,
            vision_model=target_model,
            judge_model=judge_model,
            api_key=api_key,
        )
    raise ValueError(f"unknown method: {method}")  # pragma: no cover - argparse choices guards this


def summarize(result) -> dict:
    """A few fields present on most result types; see each result dataclass for the rest."""
    fields = asdict(result) if is_dataclass(result) else vars(result)
    keys = (
        "confirmed_success",
        "best_score",
        "best_prompt",
        "best_control",
        "best_transform",
        "stop_reason",
        "kappa_score",
        "query_count",
    )
    summary = {k: fields[k] for k in keys if k in fields}
    summary["trials"] = len(fields.get("trials", []))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--method", required=True, choices=METHODS)
    parser.add_argument("--goal", required=True)
    parser.add_argument("--target-url", default=os.getenv("TARGET_URL"))
    parser.add_argument("--target-model", default=os.getenv("TARGET_MODEL"))
    parser.add_argument("--attacker-model", default=os.getenv("ATTACKER_MODEL"))
    parser.add_argument("--judge-model", default=os.getenv("JUDGE_MODEL"))
    parser.add_argument("--api-key", default=os.getenv("TARGET_API_KEY"))
    parser.add_argument("--max-turns", type=int, default=5, help="crescendo/goat only")
    args = parser.parse_args()

    if not args.target_url:
        parser.error("--target-url or TARGET_URL is required")

    result = asyncio.run(
        run_method(
            args.method,
            goal=args.goal,
            target_url=args.target_url,
            target_model=args.target_model,
            attacker_model=args.attacker_model,
            judge_model=args.judge_model,
            api_key=args.api_key,
            max_turns=args.max_turns,
        )
    )
    print(json.dumps(summarize(result), indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
