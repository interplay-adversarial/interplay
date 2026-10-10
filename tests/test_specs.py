"""
Spec validation tests — run on every PR that touches specs/.

Tests run without data-designer installed — only pydantic + numpy + pandas required.
"""

import sys
from pathlib import Path

# Allow running as a script (python tests/test_specs.py) without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

from specs import list_specs, load_spec
from specs.models import BiasComparisonSpec, BiasGroup
from specs.sdg_hub_harm import SDG_HUB_HARM_DATASET
from specs.singapore import CATEGORY_DEFINITIONS, CULTURAL_BIAS_DATASET


def test_models_importable() -> None:
    assert BiasGroup is not None
    assert BiasComparisonSpec is not None


def test_singapore_dataset_shape() -> None:
    assert len(CULTURAL_BIAS_DATASET) == 5, "Singapore taxonomy must have 5 bias categories"
    required_cols = [
        "policy_concept",
        "concept_definition",
        "demographics_pool",
        "geography_pool",
        "cultural_context_pool",
        "prompt_strategy_pool",
        "target_language_pool",
    ]
    for col in required_cols:
        assert col in CULTURAL_BIAS_DATASET.columns, f"Missing column: {col}"


def test_sdg_hub_harm_dataset_shape() -> None:
    assert len(SDG_HUB_HARM_DATASET) == 8, "SDG Hub harm dataset must have 8 categories"
    required_cols = [
        "policy_concept",
        "concept_definition",
        "demographics_pool",
        "expertise_pool",
        "geography_pool",
        "language_styles_pool",
        "exploit_stages_pool",
        "task_medium_pool",
        "temporal_pool",
        "trust_signals_pool",
    ]
    for col in required_cols:
        assert col in SDG_HUB_HARM_DATASET.columns, f"Missing column: {col}"


def test_no_duplicate_policy_concepts() -> None:
    import pandas as pd

    combined = pd.concat([CULTURAL_BIAS_DATASET, SDG_HUB_HARM_DATASET], ignore_index=True)
    assert combined["policy_concept"].nunique() == 13, (
        "Combined dataset should have 13 unique policy concepts (5 Singapore + 8 harm)"
    )


def test_sdg_hub_expertise_pool_populated() -> None:
    for _, row in SDG_HUB_HARM_DATASET.iterrows():
        assert len(row["expertise_pool"]) >= 1, (
            f"{row['policy_concept']}: expertise_pool must not be empty"
        )


def test_singapore_definitions_coverage() -> None:
    for _, row in CULTURAL_BIAS_DATASET.iterrows():
        cat = row["policy_concept"]
        assert cat in CATEGORY_DEFINITIONS, f"Missing definition for: {cat}"
        assert len(CATEGORY_DEFINITIONS[cat]) > 10


def test_list_specs_finds_bundled() -> None:
    slugs = list_specs()
    assert "us-mexico" in slugs
    assert "us-puerto-rico" in slugs
    assert "us-white-brown" in slugs
    # singapore is excluded from comparison specs
    assert "singapore" not in slugs


def test_all_specs_load_and_validate() -> None:
    for slug in list_specs():
        spec = load_spec(slug)
        assert isinstance(spec, BiasComparisonSpec), f"{slug}: SPEC must be BiasComparisonSpec"
        assert spec.name, f"{slug}: name must be non-empty"
        assert len(spec.group_1.cultural_references) >= 3, (
            f"{slug}: group_1 needs ≥3 cultural_references"
        )
        assert len(spec.group_2.cultural_references) >= 3, (
            f"{slug}: group_2 needs ≥3 cultural_references"
        )
        assert len(spec.group_1.regional_variants) >= 2, (
            f"{slug}: group_1 needs ≥2 regional_variants"
        )
        assert len(spec.group_2.regional_variants) >= 2, (
            f"{slug}: group_2 needs ≥2 regional_variants"
        )
        assert len(spec.group_1.stereotypes_to_probe) >= 2, (
            f"{slug}: group_1 needs ≥2 stereotypes_to_probe"
        )
        assert len(spec.group_2.stereotypes_to_probe) >= 2, (
            f"{slug}: group_2 needs ≥2 stereotypes_to_probe"
        )
        assert len(spec.bias_categories) >= 1, f"{slug}: at least one bias_category required"
        assert len(spec.shared_topics) >= 3, f"{slug}: at least 3 shared_topics required"
        assert len(spec.prompt_strategies) >= 2, f"{slug}: at least 2 prompt_strategies required"


def test_regional_weights_positive() -> None:
    for slug in list_specs():
        spec = load_spec(slug)
        for region, weight in spec.group_1.regional_variants.items():
            assert weight > 0, f"{slug}/group_1: weight for '{region}' must be positive"
        for region, weight in spec.group_2.regional_variants.items():
            assert weight > 0, f"{slug}/group_2: weight for '{region}' must be positive"


def test_slug_variants_load_same_spec() -> None:
    s1 = load_spec("us-mexico")
    s2 = load_spec("us_mexico")
    assert s1.name == s2.name


if __name__ == "__main__":
    tests = [
        test_models_importable,
        test_singapore_dataset_shape,
        test_sdg_hub_harm_dataset_shape,
        test_no_duplicate_policy_concepts,
        test_sdg_hub_expertise_pool_populated,
        test_singapore_definitions_coverage,
        test_list_specs_finds_bundled,
        test_all_specs_load_and_validate,
        test_regional_weights_positive,
        test_slug_variants_load_same_spec,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  PASS  {test.__name__}")
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(failed)
