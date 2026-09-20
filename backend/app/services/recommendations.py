"""Basis-aware, non-diagnostic recommendations derived from existing M1/M2 data."""

from __future__ import annotations

import math
from typing import Any


def _measurement(source: dict[str, Any], field: str) -> float | None:
    value = source.get(field)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _item(category: str, priority: str, message: str, reason: str) -> dict[str, str]:
    return {
        "category": category,
        "priority": priority,
        "message": message,
        "reason": reason,
    }


def generate_recommendations(
    nlp_result: dict[str, Any],
    health_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return general label-reading guidance without changing either M2 output."""

    basis = str(
        (health_result or {}).get("basis") or nlp_result.get("basis") or "unknown"
    )
    nutrition = nlp_result.get("nutrition")
    nutrition = nutrition if isinstance(nutrition, dict) else {}
    nutrition_score = (health_result or {}).get("nutrition_score")
    nutrition_score = nutrition_score if isinstance(nutrition_score, dict) else {}
    items: list[dict[str, str]] = []
    omissions: list[str] = []

    thresholds_applied = basis == "per_100g" and nutrition_score.get("available") is True
    if basis != "per_100g":
        omissions.append(
            f"Nutrition-threshold recommendations require per_100g data; basis {basis} was preserved and no conversion was attempted."
        )
    elif nutrition_score.get("available") is not True:
        missing = list(nutrition_score.get("missing_nutrients") or [])
        detail = "Required M2 nutrition measurements are incomplete."
        if missing:
            detail += " Missing: " + ", ".join(missing) + "."
        omissions.append(detail)

    if thresholds_applied:
        sugar = _measurement(nutrition, "sugars_100g")
        saturated_fat = _measurement(nutrition, "saturated_fat_100g")
        trans_fat = _measurement(nutrition, "trans_fat_100g")
        sodium_g = _measurement(nutrition, "sodium_100g")

        if sugar is not None and sugar >= 22.5:
            items.append(
                _item(
                    "sugar",
                    "HIGH",
                    "Consider comparing this product with options containing less sugar per 100 g.",
                    f"The label reports {sugar:g} g sugars per 100 g.",
                )
            )
        elif sugar is not None and sugar >= 5:
            items.append(
                _item(
                    "sugar",
                    "MEDIUM",
                    "Compare the sugars-per-100-g value when choosing between similar products.",
                    f"The label reports {sugar:g} g sugars per 100 g.",
                )
            )

        if saturated_fat is not None and saturated_fat >= 5:
            items.append(
                _item(
                    "saturated_fat",
                    "HIGH",
                    "Consider comparing this product with options containing less saturated fat per 100 g.",
                    f"The label reports {saturated_fat:g} g saturated fat per 100 g.",
                )
            )
        elif saturated_fat is not None and saturated_fat >= 1.5:
            items.append(
                _item(
                    "saturated_fat",
                    "MEDIUM",
                    "Compare saturated-fat values across similar products.",
                    f"The label reports {saturated_fat:g} g saturated fat per 100 g.",
                )
            )

        if trans_fat is not None and trans_fat > 0:
            items.append(
                _item(
                    "trans_fat",
                    "HIGH",
                    "Review and compare the declared trans-fat value on alternative products.",
                    f"The label reports {trans_fat:g} g trans fat per 100 g.",
                )
            )

        if sodium_g is not None:
            sodium_mg = sodium_g * 1000.0
            if sodium_mg >= 600:
                items.append(
                    _item(
                        "sodium",
                        "HIGH",
                        "Consider comparing this product with options containing less sodium per 100 g.",
                        f"The label reports {sodium_mg:g} mg sodium per 100 g.",
                    )
                )
            elif sodium_mg >= 300:
                items.append(
                    _item(
                        "sodium",
                        "MEDIUM",
                        "Compare sodium-per-100-g values across similar products.",
                        f"The label reports {sodium_mg:g} mg sodium per 100 g.",
                    )
                )

    allergens = nlp_result.get("allergens")
    if isinstance(allergens, list) and allergens:
        names = [str(item).strip() for item in allergens if str(item).strip()]
        if names:
            items.append(
                _item(
                    "allergens",
                    "HIGH",
                    "Review the product's allergen declaration against the consumer's known requirements.",
                    "The M1 label parser detected: " + ", ".join(names) + ".",
                )
            )

    additives = nlp_result.get("additives")
    if isinstance(additives, list) and additives:
        items.append(
            _item(
                "label_review",
                "LOW",
                "Use the complete ingredient and additive declaration when comparing products.",
                f"The M1 label parser detected {len(additives)} additive reference(s).",
            )
        )

    priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    items.sort(key=lambda item: (priority_order[item["priority"]], item["category"]))
    return {
        "status": "available" if not omissions else "partial",
        "basis": basis,
        "nutrition_thresholds_applied": thresholds_applied,
        "items": items,
        "omissions": omissions,
        "disclaimer": (
            "These are general, rule-based food-label suggestions, not medical advice, "
            "a diagnosis, or a statement that any ingredient is medically safe or unsafe."
        ),
    }
