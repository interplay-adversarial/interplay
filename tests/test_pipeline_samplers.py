"""The category samplers must never fail on a category with an empty or missing pool."""

import pytest

from interplay import pipeline
from interplay.specs.sdg_hub_harm import SDG_HUB_HARM_DEFINITIONS
from interplay.specs.singapore import CATEGORY_DEFINITIONS

ALL_CATEGORIES = [*CATEGORY_DEFINITIONS, *SDG_HUB_HARM_DEFINITIONS, "a category nobody defined"]
SAMPLERS = [
    (pipeline._sg_cultural_context, "cultural_context"),
    (pipeline._sg_prompt_strategy, "prompt_strategy"),
    (pipeline._sg_target_language, "target_language"),
]


@pytest.mark.parametrize("category", ALL_CATEGORIES)
@pytest.mark.parametrize(("sampler", "column"), SAMPLERS)
def test_sampler_returns_a_value_for_every_category(sampler, column, category):
    row = sampler({"policy_concept": category})
    assert isinstance(row[column], str) and row[column]


def test_harm_categories_have_empty_context_pools_and_still_sample():
    # Documents the data shape that used to crash the pipeline: np.random.choice([]) raises.
    empty = [
        c for c in SDG_HUB_HARM_DEFINITIONS if not pipeline.CULTURAL_CONTEXTS_BY_CATEGORY.get(c)
    ]
    assert empty, "if every harm category now has contexts, this guard test can be removed"
    assert (
        pipeline._sg_cultural_context({"policy_concept": empty[0]})["cultural_context"]
        == "No context available"
    )
