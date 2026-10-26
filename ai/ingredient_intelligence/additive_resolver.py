"""Additive resolution for the R4 Ingredient Intelligence Engine."""

from __future__ import annotations

from ai.ingredient_intelligence.schemas import (
    AdditiveMatch,
    IngredientAdditiveResolution,
    ParsedIngredient,
)
from ai.ingredient_intelligence.taxonomy import (
    AdditiveTaxonomyEntry,
    build_additive_lookup,
    match_additive_exact,
)


class AdditiveResolver:
    """Resolve parsed ingredient tokens against the OFF additive taxonomy."""

    def __init__(self, entries: list[AdditiveTaxonomyEntry]) -> None:
        self.lookup = build_additive_lookup(entries)

    def resolve(self, ingredient: ParsedIngredient) -> IngredientAdditiveResolution:
        """Resolve one ingredient token using conservative exact matching."""

        match = match_additive_exact(
            ingredient.normalized_text,
            self.lookup,
        )

        if match is None:
            return IngredientAdditiveResolution(
                ingredient=ingredient,
                additive=AdditiveMatch(
                    matched=False,
                    match_method="NONE",
                ),
            )

        return IngredientAdditiveResolution(
            ingredient=ingredient,
            additive=AdditiveMatch(
                matched=True,
                taxonomy_id=match.taxonomy_id,
                canonical_name=match.canonical_name,
                external_code=match.external_code,
                functional_category=match.functional_category,
                match_method="EXACT",
                source_dataset=match.source_dataset,
                source_version=match.source_version,
            ),
        )

    def resolve_many(
        self,
        ingredients: list[ParsedIngredient],
    ) -> list[IngredientAdditiveResolution]:
        """Resolve multiple ingredient tokens while preserving order."""

        return [self.resolve(ingredient) for ingredient in ingredients]
