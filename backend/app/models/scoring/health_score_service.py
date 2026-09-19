"""Deterministic M2 nutrition-health score adapted from ``origin/main``.

The original service also folded ingredient-model probabilities and a knowledge
base into one score. NutriLens exposes ingredient risk separately, so this
module keeps only the independently explainable nutrition and additive terms.
Missing measurements are rejected rather than interpreted as zero.
"""

from __future__ import annotations

import math
from typing import Any

from ...core.errors import InvalidModelInputError

REQUIRED_NUTRITION_FIELDS = (
    "sugar_g",
    "saturated_fat_g",
    "trans_fat_g",
    "sodium_mg",
)


def _measurement(data: dict[str, Any], field: str) -> float:
    value = data.get(field)
    if value is None:
        raise InvalidModelInputError(
            f"Missing required nutrition measurement: {field}."
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidModelInputError(
            f"Nutrition measurement {field} must be numeric."
        ) from exc
    if not math.isfinite(number) or number < 0:
        raise InvalidModelInputError(
            f"Nutrition measurement {field} must be a finite non-negative value."
        )
    return number


def calculate_nutrition_health_score(
    nutrition: dict[str, Any],
    *,
    additives: list[str] | None = None,
    allergens: list[str] | None = None,
) -> dict[str, Any]:
    """Return the M2 score for verified per-100g measurements."""

    sugar = _measurement(nutrition, "sugar_g")
    saturated_fat = _measurement(nutrition, "saturated_fat_g")
    trans_fat = _measurement(nutrition, "trans_fat_g")
    sodium_mg = _measurement(nutrition, "sodium_mg")

    nutrition_breakdown: dict[str, float] = {}
    reasons: list[str] = []
    warnings: list[str] = []

    sugar_penalty = 12.0 if sugar >= 22.5 else 5.0 if sugar >= 5.0 else 0.0
    if sugar_penalty:
        reasons.append(
            "High sugar content"
            if sugar_penalty == 12.0
            else "Moderate sugar content"
        )
    nutrition_breakdown["sugar_penalty"] = sugar_penalty

    saturated_fat_penalty = (
        10.0 if saturated_fat >= 5.0 else 4.0 if saturated_fat >= 1.5 else 0.0
    )
    if saturated_fat_penalty:
        reasons.append(
            "High saturated fat content"
            if saturated_fat_penalty == 10.0
            else "Moderate saturated fat content"
        )
    nutrition_breakdown["saturated_fat_penalty"] = saturated_fat_penalty

    trans_fat_penalty = 10.0 if trans_fat > 0 else 0.0
    if trans_fat_penalty:
        reasons.append("Contains trans fat")
    nutrition_breakdown["trans_fat_penalty"] = trans_fat_penalty

    sodium_penalty = (
        10.0 if sodium_mg >= 600.0 else 4.0 if sodium_mg >= 300.0 else 0.0
    )
    if sodium_penalty:
        reasons.append(
            "High sodium content"
            if sodium_penalty == 10.0
            else "Moderate sodium content"
        )
    nutrition_breakdown["sodium_penalty"] = sodium_penalty

    nutrition_penalty = min(
        35.0,
        sugar_penalty + saturated_fat_penalty + trans_fat_penalty + sodium_penalty,
    )
    additive_count = len(additives or [])
    additive_penalty = float(min(5, additive_count))
    if additive_penalty:
        reasons.append(f"Contains {additive_count} detected additive(s)")

    if allergens:
        warnings.append("Contains or may contain: " + ", ".join(allergens))

    total_penalty = nutrition_penalty + additive_penalty
    score = max(0.0, min(100.0, 100.0 - total_penalty))
    score_level = "GOOD" if score >= 70.0 else "MODERATE" if score >= 40.0 else "POOR"

    return {
        "health_score": round(score, 2),
        "score_level": score_level,
        "breakdown": {
            "nutrition_penalty": nutrition_penalty,
            "additive_penalty": additive_penalty,
            "allergen_penalty": 0.0,
        },
        "nutrition_breakdown": nutrition_breakdown,
        "reasons": reasons,
        "warnings": warnings,
        "total_penalty": round(total_penalty, 2),
        "model_version": "m2_nutrition_rules_v1",
    }
