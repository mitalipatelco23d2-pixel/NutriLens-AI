"""Conservative label facts shared by client and server scan paths.

No nutritional rating is inferred without a governed rule and compatible basis.
Missing/ambiguous values, units and columns remain unknown.
"""

from __future__ import annotations

import math
import re

from ai.food_understanding.nutrition_consistency import inconsistent_serving_rows
from ai.food_understanding.schemas import (
    IngredientExtraction,
    NutritionExtraction,
    NutritionRow,
    ScanInsightHighlight,
    ScanInsights,
    TextCandidate,
)

_CANONICAL_ALIASES: dict[str, set[str]] = {
    "energy": {
        "energy",
        "calories",
        "calorie",
        "caloric value",
        "energi",
        "energy value",
        "energla",
    },
    "protein": {"protein", "proteins", "proteln"},
    "carbohydrate": {
        "carbohydrate",
        "carbohydrates",
        "total carbohydrate",
        "total carbohydrates",
        "carb",
        "carbs",
    },
    "total sugar": {"total sugar", "total sugars", "totalsugar", "sugar", "sugars"},
    "added sugar": {
        "added sugar",
        "added sugars",
        "aded sugar",
        "uded sugar",
        "mded sugar",
    },
    "total fat": {"total fat", "totalfat", "fat", "total lipids"},
    "saturated fat": {
        "saturated fat",
        "saturatedfat",
        "saturatd fat",
        "saturated fatty acids",
        "saturates",
    },
    "trans fat": {"trans fat", "transfat", "trans fatty acids"},
    "cholesterol": {"cholesterol", "cholestrol", "colesterol"},
    "sodium": {"sodium", "sodiumn", "sdium", "sodlum"},
    "calcium": {"calcium", "calctum", "clctum", "calclum"},
    "fibre": {"fibre", "fiber", "dietary fibre", "dietary fiber"},
}


_BASES = {"PER_100_G": "per 100 g", "PER_100_ML": "per 100 ml", "PER_SERVING": "per serving"}
_UNITS = {"energy": {"kcal", "kj"}, "sodium": {"mg", "g"}, "calcium": {"mg", "g"}}


def _amount(value: str) -> float | None:
    # Do not round inequalities, percentages, OCR garbage or nonfinite values to zero.
    if not re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", value.strip()):
        return None
    number = float(value.replace(",", "."))
    return number if math.isfinite(number) else None


def _fact(nutrition: NutritionExtraction, row: NutritionRow, canonical: str) -> str | None:
    columns = [c.casefold().strip() for c in nutrition.table_columns]
    if len(columns) != len(row.values):
        amounts = [c for c in columns if "%" not in c]
        columns = amounts if len(amounts) == len(row.values) else []
    expected_basis = _BASES.get(nutrition.basis)
    if not expected_basis:
        return None
    if not nutrition.table_columns and len(row.values) == 1:
        index = 0
    else:
        matches = [i for i, c in enumerate(columns) if c == expected_basis]
        if len(matches) != 1:
            return None
        index = matches[0]
    if index >= len(row.values) or index >= len(row.units):
        return None
    value = _amount(row.values[index])
    unit = row.units[index].strip().casefold()
    if value is None or unit not in _UNITS.get(canonical, {"g", "mg"}):
        return None
    return f"{canonical.capitalize()}: {value:g} {unit} {expected_basis}."


def compose_scan_insights(
    nutrition: NutritionExtraction | None,
    ingredients: IngredientExtraction | None,
    brand_candidates: list[TextCandidate] | None = None,
    product_name_candidates: list[TextCandidate] | None = None,
) -> ScanInsights:
    """Present declared facts without assigning unsupported health or safety meaning."""
    highlights: list[str] = []
    watches: list[str] = []
    structured: list[ScanInsightHighlight] = []
    context: str | None = None
    allergen: str | None = None
    if nutrition is not None:
        basis = _BASES.get(nutrition.basis)
        val, unit = nutrition.serving_size_value, nutrition.serving_size_unit
        if basis is None:
            context = "Serving basis could not be determined from label. Check original package."
        else:
            context = f"Values stated {basis}."
            if val and unit and _amount(val) is not None and (_amount(val) or 0) > 0:
                context += f" One serving is {val} {unit}."
                same_unit = {"PER_100_G": "g", "PER_100_ML": "ml"}.get(nutrition.basis)
                if same_unit == unit.casefold():
                    context += (
                        f" This is {float(val.replace(',', '.')) / 100:g} times the stated basis."
                    )
            else:
                context += " Serving size is not declared on label."
        structured.append(
            ScanInsightHighlight(
                title="Serving basis", description=context, category="serving", icon="scale"
            )
        )

    if ingredients is not None and ingredients.allergen_text.strip():
        # Preserve the entire declaration, including mixed contains/may-contain/free-from
        # clauses. A free-from clause never makes a mixed warning green/positive.
        statement = ingredients.allergen_text.strip()
        allergen = f"Package allergen statement: {statement}"
        highlights.append(allergen)
        structured.append(
            ScanInsightHighlight(
                title="Allergen statement",
                description=allergen,
                category="allergen",
                icon="alert-triangle",
            )
        )
    if nutrition is not None:
        if nutrition.confidence is not None and nutrition.confidence < 0.5:
            watches.append("Some nutrition text was difficult to read. Check the original package.")
        conflicts = inconsistent_serving_rows(nutrition)
        if conflicts:
            watches.append(
                "Some amounts conflict across serving columns. Check the package before using them."
            )
        for canonical, aliases in _CANONICAL_ALIASES.items():
            matches = [
                row
                for index, row in enumerate(nutrition.table_rows)
                if index not in conflicts
                and (row.canonical_label or row.label).casefold().strip() in aliases
            ]
            if len(matches) != 1:
                continue
            fact = _fact(nutrition, matches[0], canonical)
            if fact:
                structured.append(
                    ScanInsightHighlight(
                        title=f"{canonical.capitalize()} content",
                        description=fact,
                        category="neutral",
                    )
                )
                highlights.append(fact)
        if nutrition.table_rows and not highlights:
            highlights.append(
                "Nutrition text was detected; verify amounts and serving basis on the package."
            )
    if not highlights:
        highlights.append(
            "Ingredient list extracted from label."
            if ingredients is not None and ingredients.raw_text
            else "Food label captured for reference."
        )
    return ScanInsights(
        highlights=highlights[:3],
        positive_signals=[],
        things_to_watch=watches,
        allergen_summary=allergen,
        serving_context=context,
        structured_highlights=structured,
        ask_nutri_suggestions=[
            "Explain this scan.",
            "How much protein is one serving?",
            "What allergen statements are on this label?",
        ],
    )
