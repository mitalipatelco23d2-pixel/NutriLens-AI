"""Canonical recipe adapter; no generation or recommendation logic."""

from __future__ import annotations

from typing import Any

from scripts.data_engineering.normalization import normalize_display_text
from scripts.data_engineering.schemas import Lineage, RecipeIngredient, RecipeRecord


def normalize_recipe(row: dict[str, Any], lineage: Lineage) -> RecipeRecord:
    recipe_id = str(row.get("recipe_id", "")).strip()
    title = str(row.get("title", "")).strip()
    source_url = str(row.get("source_url", "")).strip()
    if not recipe_id or not title or not source_url:
        raise ValueError("recipe_id, title, and source_url are required")
    ingredients = [
        RecipeIngredient(
            sequence=index,
            text_original=str(item["text"]),
            name_normalized=normalize_display_text(str(item["name"])),
            quantity=item.get("quantity"),
            unit=item.get("unit"),
        )
        for index, item in enumerate(row.get("ingredients", []), start=1)
    ]
    return RecipeRecord(
        recipe_id=recipe_id,
        title_original=title,
        title=normalize_display_text(title),
        cuisine=row.get("cuisine"),
        ingredients=ingredients,
        steps=[normalize_display_text(str(step)) for step in row.get("steps", [])],
        servings=row.get("servings"),
        preparation_minutes=row.get("preparation_minutes"),
        cooking_minutes=row.get("cooking_minutes"),
        difficulty=row.get("difficulty"),
        dietary_tags=list(row.get("dietary_tags", [])),
        source_url=source_url,
        review_status=str(row.get("review_status", "DRAFT")),
        lineage=lineage,
    )
