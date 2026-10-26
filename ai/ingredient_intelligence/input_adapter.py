"""R3 to R4 input adapter."""

from __future__ import annotations

from ai.food_understanding.schemas import IngredientExtraction
from ai.ingredient_intelligence.parser import parse_ingredient_list
from ai.ingredient_intelligence.schemas import IngredientParseResult


def parse_r3_ingredients(
    extraction: IngredientExtraction,
) -> IngredientParseResult:
    """Convert the governed R3 ingredient extraction into the R4 parse contract."""

    return parse_ingredient_list(extraction.raw_text)
