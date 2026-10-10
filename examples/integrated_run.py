"""Integrated red teaming run: cultural bias + attack methodologies.

Example workflow:
    1. Generate probes with cultural-bias-red-team pipeline
    2. Run Garak against target
    3. Run TAP/PAIR attacks
    4. Merge results with statistical validation

Usage:
    # Set environment variables or create .env file
    export TARGET_URL="https://your-target/v1"
    export TARGET_API_KEY="your-api-key"
    export JUDGE_MODEL="judge-model-name"

    # Run integrated workflow
    uv run python examples/integrated_run.py
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from red_teaming import (
    get_judge_config,
    get_target_config,
    load_env_file,
    pair_attack,
    run_garak,
    tap_attack,
)


async def run_integrated_workflow(
    probe_file: str,
    target_url: str | None = None,
    api_key: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Run integrated cultural bias + attack methodology workflow.

    Args:
        probe_file: Path to cultural bias probe file (JSONL)
        target_url: Target endpoint URL (optional, uses env TARGET_URL)
        api_key: API key (optional, uses env variables)
        output_dir: Directory for output files

    Returns:
        Dict with merged results
    """
    # Load environment
    load_env_file()

    # Get config from env
    target_config = get_target_config()
    judge_config = get_judge_config()

    # Override with explicit args
    target_url = target_url or target_config["url"]
    api_key = api_key or target_config.get("api_key")

    # Ensure output directory
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)

    results = {
        "config": {
            "target_url": target_url,
            "target_model": target_config.get("model"),
            "judge_model": judge_config.get("model"),
        },
        "garak_results": None,
        "tap_results": [],
        "pair_results": [],
        "summary": {},
    }

    # Step 1: Run Garak
    print("Step 1: Running Garak...")
    garak_result = run_garak(
        target_url=target_url,
        probe_file=probe_file,
        output_dir=output_dir,
    )
    results["garak_results"] = garak_result
    print(f"Garak: {'SUCCESS' if garak_result['success'] else 'FAILED'}")

    # Step 2: Run TAP on subset of probes
    print("Step 2: Running TAP attacks...")
    # Load probes
    probes = []
    with open(probe_file) as f:
        for line in f:
            probes.append(json.loads(line))

    # Run TAP on first 5 probes (adjust as needed)
    for i, probe in enumerate(probes[:5]):
        print(f"  TAP probe {i + 1}/{min(5, len(probes))}...")
        goal = probe.get("adversarial_probe", {}).get("prompt", probe.get("prompt", ""))

        tap_result = await tap_attack(
            goal=goal,
            target_url=target_url,
            attacker_model=os.getenv(
                "ATTACKER_MODEL", judge_config.get("model", "openai/gpt-4o-mini")
            ),
            evaluator_model=os.getenv(
                "EVALUATOR_MODEL", judge_config.get("model", "openai/gpt-4o-mini")
            ),
            judge_model=os.getenv("JUDGE_MODEL", judge_config.get("model")),
            api_key=api_key,
            base_url=os.getenv("BASE_URL"),
        )
        results["tap_results"].append(
            {
                "probe": probe,
                "result": {
                    "best_score": tap_result.best_score,
                    "best_prompt": tap_result.best_prompt,
                    "kappa_score": tap_result.kappa_score,
                },
            }
        )

    # Step 3: Run PAIR on subset
    print("Step 3: Running PAIR attacks...")
    for i, probe in enumerate(probes[:3]):  # Fewer for demo
        print(f"  PAIR probe {i + 1}/{min(3, len(probes))}...")
        goal = probe.get("adversarial_probe", {}).get("prompt", probe.get("prompt", ""))

        pair_result = await pair_attack(
            goal=goal,
            target_url=target_url,
            attacker_model=os.getenv(
                "ATTACKER_MODEL", judge_config.get("model", "openai/gpt-4o-mini")
            ),
            judge_model=os.getenv("JUDGE_MODEL", judge_config.get("model", "openai/gpt-4o-mini")),
            api_key=api_key,
            base_url=os.getenv("BASE_URL"),
        )
        results["pair_results"].append(
            {
                "probe": probe,
                "result": {
                    "best_score": pair_result.best_score,
                    "best_prompt": pair_result.best_prompt,
                    "query_count": pair_result.query_count,
                },
            }
        )

    # Step 4: Calculate summary
    tap_scores = [r["result"]["best_score"] for r in results["tap_results"]]
    pair_scores = [r["result"]["best_score"] for r in results["pair_results"]]

    results["summary"] = {
        "total_probes": len(probes),
        "tap_attacks_run": len(tap_scores),
        "tap_avg_score": sum(tap_scores) / len(tap_scores) if tap_scores else 0,
        "tap_max_score": max(tap_scores) if tap_scores else 0,
        "pair_attacks_run": len(pair_scores),
        "pair_avg_score": sum(pair_scores) / len(pair_scores) if pair_scores else 0,
        "pair_max_score": max(pair_scores) if pair_scores else 0,
    }

    # Save results
    if output_dir:
        output_file = Path(output_dir) / "integrated_results.json"
        with open(output_file, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Results saved to {output_file}")

    return results


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Integrated red teaming workflow")
    parser.add_argument("--probe-file", default="probes.jsonl", help="Probe file path")
    parser.add_argument("--target-url", help="Target endpoint URL")
    parser.add_argument("--api-key", help="API key")
    parser.add_argument("--output-dir", default="output", help="Output directory")

    args = parser.parse_args()

    # Run workflow
    results = asyncio.run(
        run_integrated_workflow(
            probe_file=args.probe_file,
            target_url=args.target_url,
            api_key=args.api_key,
            output_dir=args.output_dir,
        )
    )

    # Print summary
    print("\n" + "=" * 60)
    print("INTEGRATED WORKFLOW SUMMARY")
    print("=" * 60)
    print(f"Target: {results['config']['target_url']}")
    print(f"Total probes: {results['summary']['total_probes']}")
    print(f"TAP attacks: {results['summary']['tap_attacks_run']}")
    print(f"  Avg score: {results['summary']['tap_avg_score']:.3f}")
    print(f"  Max score: {results['summary']['tap_max_score']:.3f}")
    print(f"PAIR attacks: {results['summary']['pair_attacks_run']}")
    print(f"  Avg score: {results['summary']['pair_avg_score']:.3f}")
    print(f"  Max score: {results['summary']['pair_max_score']:.3f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
