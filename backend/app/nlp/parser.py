from __future__ import annotations

from dataclasses import asdict
from typing import Any, Protocol

from ..ocr.nutrition_parser import NutritionParseResult, parse_nutrition_text
from .additives import extract_additives
from .allergens import extract_allergen_declarations, extract_explicit_allergens
from .ingredients import (
    extract_ingredient_section,
    extract_ingredients_from_text,
    normalize_ingredient_list,
    normalize_ingredient_name,
)


CANONICAL_NUTRITION_KEYS = {
    "fat_100g",
    "saturated_fat_100g",
    "trans_fat_100g",
    "carbohydrates_100g",
    "sugars_100g",
    "added_sugars_100g",
    "fiber_100g",
    "proteins_100g",
    "salt_100g",
    "sodium_100g",
    "calcium_100g",
}


class IngredientExtractor(Protocol):
    def extract(self, text: str) -> list[str]: ...


def canonical_nutrition(parsed: NutritionParseResult) -> dict[str, float]:
    nutrition: dict[str, float] = {}
    for name, nutrient in parsed.nutrients.items():
        if name == "energy_100g":
            nutrition["energy_kj_100g"] = nutrient.value
            nutrition["energy_kcal_100g"] = round(nutrient.value / 4.184, 6)
        elif name in CANONICAL_NUTRITION_KEYS:
            nutrition[name] = nutrient.value
    return nutrition


def nutrition_details(parsed: NutritionParseResult) -> dict[str, dict[str, Any]]:
    details: dict[str, dict[str, Any]] = {}
    for name, nutrient in parsed.nutrients.items():
        canonical_names = (
            ("energy_kj_100g", "energy_kcal_100g")
            if name == "energy_100g"
            else (name,)
        )
        for canonical_name in canonical_names:
            detail = asdict(nutrient)
            if canonical_name == "energy_kcal_100g":
                detail["value"] = round(nutrient.value / 4.184, 6)
                detail["unit"] = "kcal"
            detail["canonical_key"] = canonical_name
            details[canonical_name] = detail
    return details


def analyze_food_label_text(
    text: str,
    parsed_nutrition: NutritionParseResult | None = None,
    ocr_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    parsed = parsed_nutrition or parse_nutrition_text(text)
    ingredient_result = extract_ingredient_section(text)
    declarations = extract_allergen_declarations(text)
    additives = extract_additives(text)
    warnings = list(dict.fromkeys([*parsed.warnings, *ingredient_result.warnings]))
    result = {
        "ingredients": ingredient_result.ingredients,
        "additives": additives,
        "allergens": list(dict.fromkeys(item.name for item in declarations)),
        "allergen_details": [asdict(item) for item in declarations],
        "nutrition": canonical_nutrition(parsed),
        "nutrition_details": nutrition_details(parsed),
        "basis": parsed.basis,
        "warnings": warnings,
        "metadata": {
            "processor": "member_1_packaged_food_nlp",
            "ingredient_section_detected": ingredient_result.section_detected,
            "ingredient_heading": ingredient_result.heading,
            "ingredient_section_truncated": ingredient_result.truncated,
            "additive_count": len(additives),
            "explicit_allergen_count": len(declarations),
            "nutrition_field_count": len(parsed.nutrients),
        },
    }
    if ocr_result is not None:
        lines = ocr_result.get("lines") or []
        confidence = ocr_result.get("mean_confidence")
        result["metadata"].update(
            {
                "ocr_mean_confidence": confidence,
                "ocr_line_count": len(lines) if isinstance(lines, list) else 0,
                "text_source": "raw_text"
                if str(ocr_result.get("raw_text") or "").strip()
                else "lines",
            }
        )
        if ocr_result.get("engine") is not None:
            result["metadata"]["ocr_engine"] = ocr_result["engine"]
        if ocr_result.get("selected_rotation") is not None:
            result["metadata"]["ocr_rotation"] = ocr_result["selected_rotation"]
        if isinstance(confidence, (int, float)) and 0 <= confidence < 0.5:
            result["warnings"].append(
                "OCR confidence was low; structured label extraction may be incomplete."
            )
        if not text.strip():
            result["warnings"].append("OCR supplied no usable label text.")
        result["warnings"] = list(dict.fromkeys(result["warnings"]))
    return result


class PackagedFoodNlpAnalyzer:
    provider = "member_1_packaged_food_nlp"

    @staticmethod
    def _text(ocr_result: dict[str, Any]) -> str:
        raw_text = str(ocr_result.get("raw_text") or "")
        if raw_text.strip():
            return raw_text
        return "\n".join(
            str(line.get("text") or "")
            for line in ocr_result.get("lines") or []
            if isinstance(line, dict)
        )

    def analyze(
        self,
        ocr_result: dict[str, Any],
        *,
        parsed_nutrition: NutritionParseResult | None = None,
    ) -> dict[str, Any]:
        return analyze_food_label_text(
            self._text(ocr_result),
            parsed_nutrition=parsed_nutrition,
            ocr_result=ocr_result,
        )


class FallbackIngredientExtractor:
    """Compatibility adapter used by the detailed Member 4 pipeline."""

    def extract(self, text: str) -> list[str]:
        return extract_ingredients_from_text(text)


__all__ = [
    "FallbackIngredientExtractor",
    "IngredientExtractor",
    "PackagedFoodNlpAnalyzer",
    "analyze_food_label_text",
    "canonical_nutrition",
    "extract_additives",
    "extract_explicit_allergens",
    "extract_ingredients_from_text",
    "normalize_ingredient_list",
    "normalize_ingredient_name",
]
