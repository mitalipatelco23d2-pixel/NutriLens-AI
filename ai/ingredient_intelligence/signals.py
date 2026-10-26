"""Transparent ingredient-category signals for R4."""

from __future__ import annotations

from ai.ingredient_intelligence.schemas import (
    IngredientSignal,
    IngredientSignalResult,
    ParsedIngredient,
)
from ai.ingredient_intelligence.taxonomy import (
    AdditiveTaxonomyEntry,
    IngredientTaxonomyEntry,
    build_additive_lookup,
    build_ingredient_id_map,
    build_ingredient_lookup,
    ingredient_has_ancestor,
    match_ingredient_exact,
    normalize_lookup_text,
)


def detect_hidden_sugars_from_taxonomy(
    ingredients: list[ParsedIngredient],
    taxonomy_entries: list[IngredientTaxonomyEntry],
) -> IngredientSignalResult:
    """Detect sugar-source ingredients using OFF taxonomy ancestry."""

    signals: list[IngredientSignal] = []

    lookup = build_ingredient_lookup(taxonomy_entries)
    id_map = build_ingredient_id_map(taxonomy_entries)

    for ingredient in ingredients:
        match = match_ingredient_exact(
            ingredient.normalized_text,
            lookup,
        )

        if match is None:
            continue

        is_sugar = match.taxonomy_id == "off:ingredient:sugar" or ingredient_has_ancestor(
            match,
            "off:ingredient:sugar",
            id_map,
        )

        if not is_sugar:
            continue

        signals.append(
            IngredientSignal(
                ingredient_text=ingredient.original_text,
                category="HIDDEN_SUGAR_SOURCE",
                matched_term=match.canonical_name,
                evidence_source="OFF_TAXONOMY",
            )
        )

    return IngredientSignalResult(signals=signals)


def detect_ingredient_ancestry_signal(
    ingredients: list[ParsedIngredient],
    taxonomy_entries: list[IngredientTaxonomyEntry],
    *,
    ancestor_ids: set[str],
    category: str,
) -> IngredientSignalResult:
    """Detect a category only from an exact match and governed ancestry."""

    lookup = build_ingredient_lookup(taxonomy_entries)
    id_map = build_ingredient_id_map(taxonomy_entries)
    signals: list[IngredientSignal] = []
    for ingredient in ingredients:
        match = match_ingredient_exact(ingredient.normalized_text, lookup)
        if match is None:
            continue
        if match.taxonomy_id not in ancestor_ids and not any(
            ingredient_has_ancestor(match, ancestor_id, id_map) for ancestor_id in ancestor_ids
        ):
            continue
        signals.append(
            IngredientSignal(
                ingredient_text=ingredient.original_text,
                category=category,
                matched_term=match.canonical_name,
                evidence_source="OFF_TAXONOMY",
            )
        )
    return IngredientSignalResult(signals=signals)


def detect_additive_function_signal(
    ingredients: list[ParsedIngredient],
    additive_entries: list[AdditiveTaxonomyEntry],
    *,
    functions: set[str],
    category: str,
) -> IngredientSignalResult:
    """Detect additive functions from governed functional-category records."""

    lookup = build_additive_lookup(additive_entries)
    normalized_functions = {normalize_lookup_text(value) for value in functions}
    signals: list[IngredientSignal] = []
    for ingredient in ingredients:
        match = lookup.get(normalize_lookup_text(ingredient.normalized_text))
        categories = (
            {
                normalize_lookup_text(value)
                for value in (match.functional_category or "").split(";")
                if value.strip()
            }
            if match
            else set()
        )
        if match is None or categories.isdisjoint(normalized_functions):
            continue
        signals.append(
            IngredientSignal(
                ingredient_text=ingredient.original_text,
                category=category,
                matched_term=match.canonical_name,
                evidence_source="OFF_ADDITIVE_TAXONOMY",
            )
        )
    return IngredientSignalResult(signals=signals)
