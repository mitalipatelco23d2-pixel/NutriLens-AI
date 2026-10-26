"""Ingredient list parser for the R4 Ingredient Intelligence Engine."""

from __future__ import annotations

import re

from ai.ingredient_intelligence.normalization import normalize_ingredient_text
from ai.ingredient_intelligence.schemas import IngredientParseResult, ParsedIngredient

PERCENTAGE_PATTERN = re.compile(r"^(?P<name>.*?)(?:\s*\((?P<percentage>\d+(?:\.\d+)?)\s*%\))?\s*$")
MAX_INGREDIENT_DEPTH = 16
MAX_PARSED_INGREDIENTS = 512


def parse_ingredient_list(raw_text: str) -> IngredientParseResult:
    """Parse ordered ingredients and nested compound ingredients."""

    cleaned = normalize_ingredient_text(raw_text)

    if not cleaned:
        return IngredientParseResult(
            raw_text=raw_text,
            cleaned_text="",
            ingredients=[],
            warnings=["No ingredient text was available for parsing."],
        )

    parts = _split_top_level(cleaned)

    ingredients: list[ParsedIngredient] = []

    budget_exhausted = [False]
    for part in parts:
        _append_ingredient(part, ingredients, depth=0, budget_exhausted=budget_exhausted)

    warnings: list[str] = []

    if not ingredients:
        warnings.append("Ingredient text was present but no ingredients could be parsed.")
    if budget_exhausted[0]:
        warnings.append("Ingredient structure exceeded safe parsing limits; review is required.")

    return IngredientParseResult(
        raw_text=raw_text,
        cleaned_text=cleaned,
        ingredients=ingredients,
        warnings=warnings,
    )


def _append_ingredient(
    value: str,
    ingredients: list[ParsedIngredient],
    *,
    depth: int,
    budget_exhausted: list[bool],
) -> None:
    """Append a parent ingredient followed by any nested sub-ingredients."""

    if depth > MAX_INGREDIENT_DEPTH or len(ingredients) >= MAX_PARSED_INGREDIENTS:
        budget_exhausted[0] = True
        return

    stripped = value.strip()
    compound = re.fullmatch(r"(?P<name>[^()[\]]+?)\s*[\(\[](?P<children>.*)[\)\]]", stripped)
    if compound and any(separator in compound.group("children") for separator in ",;"):
        parent_name = compound.group("name").strip()
        if parent_name:
            ingredients.append(
                ParsedIngredient(
                    original_text=parent_name,
                    normalized_text=_normalize_name(parent_name),
                    position=len(ingredients) + 1,
                    depth=depth,
                )
            )
        for child in _split_top_level(compound.group("children")):
            if len(ingredients) >= MAX_PARSED_INGREDIENTS:
                budget_exhausted[0] = True
                break
            _append_ingredient(
                child,
                ingredients,
                depth=depth + 1,
                budget_exhausted=budget_exhausted,
            )
        return

    match = PERCENTAGE_PATTERN.fullmatch(stripped)
    if match is None:
        return
    original = match.group("name").strip()
    if not original:
        return
    percentage_raw = match.group("percentage")
    ingredients.append(
        ParsedIngredient(
            original_text=original,
            normalized_text=_normalize_name(original),
            position=len(ingredients) + 1,
            percentage=float(percentage_raw) if percentage_raw is not None else None,
            depth=depth,
        )
    )


def _split_top_level(text: str) -> list[str]:
    """Split only on commas/semicolons outside parentheses or brackets."""

    parts: list[str] = []
    buffer: list[str] = []
    depth = 0

    for character in text:
        if character in "([":
            depth += 1
            buffer.append(character)
            continue

        if character in ")]":
            depth = max(0, depth - 1)
            buffer.append(character)
            continue

        if character in ",;" and depth == 0:
            value = "".join(buffer).strip()
            if value:
                parts.append(value)
            buffer = []
            continue

        buffer.append(character)

    final_value = "".join(buffer).strip()
    if final_value:
        parts.append(final_value)

    return parts


def _normalize_name(value: str) -> str:
    """Create a conservative canonical candidate without taxonomy matching."""

    value = value.casefold()
    value = re.sub(r"\s+", " ", value)
    return value.strip()
