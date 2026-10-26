"""Allergen resolution for the R4 Ingredient Intelligence Engine."""

from __future__ import annotations

from ai.ingredient_intelligence.schemas import (
    AllergenMatch,
    IngredientAllergenResolution,
    ParsedIngredient,
)
from ai.ingredient_intelligence.taxonomy import (
    AllergenTaxonomyEntry,
    build_allergen_lookup,
    match_allergen_exact,
)


class AllergenResolver:
    """Resolve parsed ingredient tokens against the OFF allergen taxonomy."""

    def __init__(self, entries: list[AllergenTaxonomyEntry]) -> None:
        self.lookup = build_allergen_lookup(entries)

    def resolve(self, ingredient: ParsedIngredient) -> IngredientAllergenResolution:
        """Resolve one ingredient token using conservative exact matching."""

        match = match_allergen_exact(
            ingredient.normalized_text,
            self.lookup,
        )

        if match is None:
            return IngredientAllergenResolution(
                ingredient=ingredient,
                allergen=AllergenMatch(
                    matched=False,
                    match_method="NONE",
                ),
            )

        return IngredientAllergenResolution(
            ingredient=ingredient,
            allergen=AllergenMatch(
                matched=True,
                taxonomy_id=match.taxonomy_id,
                canonical_name=match.canonical_name,
                match_method="EXACT",
                source_dataset=match.source_dataset,
                source_version=match.source_version,
            ),
        )

    def resolve_many(
        self,
        ingredients: list[ParsedIngredient],
    ) -> list[IngredientAllergenResolution]:
        """Resolve multiple ingredient tokens while preserving order."""

        return [self.resolve(ingredient) for ingredient in ingredients]
