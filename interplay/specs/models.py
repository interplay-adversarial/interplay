"""
Pydantic models for defining bias comparison specs.

Each spec describes two groups to compare across bias categories.
Add new specs by creating a new file in this directory that exports SPEC.
"""

from pydantic import BaseModel, field_validator


class BiasGroup(BaseModel):
    """One side of a two-group bias comparison."""

    name: str
    # Local names, holidays, institutions, places that signal this group
    cultural_references: list[str]
    # {sub-region: weight} — weights are normalized automatically
    regional_variants: dict[str, float]
    # Bias examples the model might surface when prompted about this group
    stereotypes_to_probe: list[str]
    # Primary language(s) for prompt generation targeting this group
    language: str = "English"

    @field_validator("regional_variants")
    @classmethod
    def weights_positive(cls, v: dict[str, float]) -> dict[str, float]:
        if any(w <= 0 for w in v.values()):
            raise ValueError("All regional_variants weights must be positive")
        return v

    @field_validator("cultural_references", "stereotypes_to_probe")
    @classmethod
    def non_empty_lists(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Must provide at least one entry")
        return v


class BiasComparisonSpec(BaseModel):
    """
    User-defined two-group bias comparison.

    Pass to build_comparison_pipeline(spec) to generate probes comparing
    group_1 against group_2 across the specified bias categories.

    Usage:
        from interplay.specs.models import BiasGroup, BiasComparisonSpec

        MY_SPEC = BiasComparisonSpec(
            name="France vs Algeria",
            group_1=BiasGroup(
                name="French",
                cultural_references=["Bastille Day", "baguette", "Paris"],
                regional_variants={"Paris": 0.4, "Lyon": 0.3, "rural south": 0.3},
                stereotypes_to_probe=["French stereotyped as arrogant toward Algerians"],
            ),
            group_2=BiasGroup(
                name="Algerian",
                cultural_references=["Eid al-Fitr", "Algiers", "harissa", "couscous"],
                regional_variants={"Algiers": 0.4, "Oran": 0.3, "Kabyle region": 0.3},
                stereotypes_to_probe=["Algerians stereotyped as criminals in France"],
                language="Arabic (Algerian dialect) / French",
            ),
            bias_categories=["Race, Religion, and Ethnicity Bias", "Socio-Economic Bias"],
            shared_topics=["criminality", "work ethic", "intelligence", "trustworthiness"],
            prompt_strategies=["fill_in_blank", "positive_framing", "scenario_workplace"],
            languages=["English", "French (contexte français)"],
        )
    """

    name: str
    description: str = ""
    group_1: BiasGroup
    group_2: BiasGroup
    # Which Singapore bias categories to generate probes for
    bias_categories: list[str]
    # Fill-in-the-blank topics: "criminality", "work ethic", "intelligence"
    shared_topics: list[str]
    # Singapore prompting strategies to sample
    prompt_strategies: list[str]
    # Languages for probe generation (English is always included)
    languages: list[str] = ["English"]

    @field_validator("bias_categories", "shared_topics", "prompt_strategies")
    @classmethod
    def non_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Must provide at least one entry")
        return v
