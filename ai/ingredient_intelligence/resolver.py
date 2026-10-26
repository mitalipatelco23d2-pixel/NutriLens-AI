"""Ingredient taxonomy resolution for the R4 Ingredient Intelligence Engine."""

from __future__ import annotations

from ai.ingredient_intelligence.schemas import (
    IngredientTaxonomyMatch,
    ParsedIngredient,
    ResolvedIngredient,
)
from ai.ingredient_intelligence.taxonomy import (
    IngredientTaxonomyEntry,
    build_ingredient_lookup,
    match_ingredient_exact,
)


class IngredientResolver:
    """Resolve parsed ingredients against the governed OFF taxonomy."""

    def __init__(self, entries: list[IngredientTaxonomyEntry]) -> None:
        self.lookup = build_ingredient_lookup(entries)

    def resolve(self, ingredient: ParsedIngredient) -> ResolvedIngredient:
        """Resolve one parsed ingredient using conservative exact matching."""

        match = match_ingredient_exact(
            ingredient.normalized_text,
            self.lookup,
        )

        if match is None:
            return ResolvedIngredient(
                ingredient=ingredient,
                taxonomy=IngredientTaxonomyMatch(
                    matched=False,
                    match_method="NONE",
                ),
            )

        return ResolvedIngredient(
            ingredient=ingredient,
            taxonomy=IngredientTaxonomyMatch(
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
    ) -> list[ResolvedIngredient]:
        """Resolve multiple ingredients while preserving ingredient order."""

        return [self.resolve(ingredient) for ingredient in ingredients]
