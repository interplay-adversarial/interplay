"""
Generate a diverse red-teaming dataset by running all three taxonomy modes
and two comparison specs, then merging the results.

This produces the broadest possible probe coverage:

  Mode                  Categories              Probes   Focus
  ─────────────────     ─────────────────────   ──────   ──────────────────────────────────────
  singapore             Gender, Geographic,      200     Subtle cultural bias in everyday AI use
                        Race/Religion,                   (benign prompting, APAC context)
                        Socio-Economic,
                        Unique Cultural
  sdg-hub-harm          Illegal Activity,        320     Explicit harm categories (adversarial)
                        Hate Speech,
                        Security & Malware,
                        Violence, Fraud,
                        Sexually Explicit,
                        Misinformation,
                        Self Harm
  us-mexico             Geographic, Race,        100     US-Mexico national identity comparison
                        Socio-Economic,
                        Gender
  us-white-brown        Race, Socio-Economic,    100     Intra-US racial bias comparison
                        Geographic, Gender
  ─────────────────     ─────────────────────   ──────   ──────────────────────────────────────
  Total                 13 unique categories     720     Adversarial + benign × 4 modes

Usage:
    uv run python examples/diverse_dataset.py
    uv run python examples/diverse_dataset.py --preview-only

Output: diverse_red_team_dataset.jsonl  (Garak-compatible format)
"""

from __future__ import annotations

import argparse
import os

import pandas as pd
from data_designer.interface import DataDesigner, ResumeMode
from data_designer.types.providers import ModelConfig, ModelProvider
from dotenv import load_dotenv

from pipeline import (
    build_comparison_pipeline,
    build_cultural_bias_pipeline,
    build_harm_pipeline,
)
from specs import load_spec

load_dotenv()


def make_dd() -> DataDesigner:
    provider = ModelProvider(
        name="default",
        endpoint=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key="OPENAI_API_KEY",
        provider_type="openai",
    )
    model_config = ModelConfig(
        alias="cultural-bias-model",
        model=os.getenv("MODEL_NAME", "gpt-4o-mini"),
        provider="default",
    )
    return DataDesigner(providers=[provider], model_configs=[model_config])


def to_garak_rows(df: pd.DataFrame, mode: str) -> list[dict]:
    """Extract prompt + metadata from a DataDesigner result DataFrame."""
    rows = []
    for _, row in df.iterrows():
        probe_mode = row.get("probe_mode", "unknown")
        probe_data = row.get(f"{probe_mode}_probe", {})
        prompt = probe_data.get("prompt", "") if isinstance(probe_data, dict) else str(probe_data)
        if not prompt or len(prompt) < 10:
            continue
        rows.append(
            {
                "prompt": prompt,
                "dataset_mode": mode,
                "policy_concept": row.get("policy_concept", ""),
                "probe_mode": probe_mode,
                "strategy": row.get("prompt_strategy", ""),
                "region": row.get("region", ""),
                "language": row.get("target_language", "English"),
                "expertise_level": row.get("expertise_level", ""),
                "quality_score": row.get("probe_quality_score", ""),
                # Comparison mode extras (empty string for taxonomy modes)
                "group_1": row.get("group_1_name", ""),
                "group_2": row.get("group_2_name", ""),
                "comparison_topic": row.get("comparison_topic", ""),
                # Metadata from LLM output
                "why_harmful_or_biased": (
                    probe_data.get("why_prompt_harmful", "") if isinstance(probe_data, dict) else ""
                )
                or (
                    probe_data.get("why_culturally_biased", "")
                    if isinstance(probe_data, dict)
                    else ""
                ),
                "bias_mechanism": (
                    probe_data.get("bias_mechanism", "") if isinstance(probe_data, dict) else ""
                ),
            }
        )
    return rows


def main(preview_only: bool = False) -> None:
    dd = make_dd()
    all_rows: list[dict] = []

    # ----------------------------------------------------------------
    # Define runs: (mode_label, builder, num_records)
    # Adjust num_records to fit your token budget.
    # ----------------------------------------------------------------
    runs = [
        ("singapore", build_cultural_bias_pipeline(), 200),
        ("sdg-hub-harm", build_harm_pipeline(), 320),
        ("us-mexico", build_comparison_pipeline(load_spec("us-mexico")), 100),
        ("us-white-brown", build_comparison_pipeline(load_spec("us-white-brown")), 100),
    ]

    if preview_only:
        print("=== PREVIEW MODE — 3 records per pipeline ===\n")
        for mode, builder, _ in runs:
            print(f"── {mode} ──")
            preview = dd.preview(builder)
            cols = ["policy_concept", "probe_mode", "region", "expertise_level"]
            if "group_1_name" in preview.columns:
                cols += ["group_1_name", "group_2_name", "comparison_topic"]
            print(preview[cols].to_string())
            print()
        return

    # ----------------------------------------------------------------
    # Full generation
    # ----------------------------------------------------------------
    for mode, builder, num_records in runs:
        print(f"\n── Generating {num_records} probes: {mode} ──")
        result = dd.create(
            builder,
            num_records=num_records,
            resume=ResumeMode.IF_POSSIBLE,
        )
        print(f"   Generated: {len(result)}")
        if "probe_mode" in result.columns:
            print(f"   Adversarial: {(result['probe_mode'] == 'adversarial').sum()}")
            print(f"   Benign:      {(result['probe_mode'] == 'benign').sum()}")
        if "probe_quality_score" in result.columns:
            scores = result["probe_quality_score"].value_counts().sort_index()
            print(f"   Quality: {scores.to_dict()}")
        all_rows.extend(to_garak_rows(result, mode))

    # ----------------------------------------------------------------
    # Merge and export
    # ----------------------------------------------------------------
    combined = pd.DataFrame(all_rows)
    output = "diverse_red_team_dataset.jsonl"
    combined.to_json(output, orient="records", lines=True)

    print(f"\n{'=' * 60}")
    print(f"Total probes: {len(combined)}")
    print("\nBy dataset mode:")
    print(combined.groupby("dataset_mode").size().to_string())
    print("\nBy policy_concept:")
    print(combined.groupby("policy_concept").size().sort_values(ascending=False).to_string())
    print("\nBy probe_mode:")
    print(combined.groupby("probe_mode").size().to_string())
    print(f"\nSaved → {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate diverse red-teaming dataset")
    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="Run preview (3 records each) without full generation",
    )
    args = parser.parse_args()
    main(preview_only=args.preview_only)
