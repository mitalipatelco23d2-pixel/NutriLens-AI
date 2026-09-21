"""
NutriLens AI
M1 NLP + M2 Nutrition Integration

M1:
- Ingredient extraction
- Ingredient normalization
- Allergen detection
- Additive / INS detection

M2:
- Nutrition extraction

This module combines the structured NLP parser with the
existing nutrition extraction service.

The result can be passed to the ML health-risk model.
"""

import json

from .parser import analyze_food_label_text
from .nutrition_service import extract_nutrition


def analyze_label_text(ocr_text):
    """
    Analyze OCR text from a packaged-food label.

    Parameters
    ----------
    ocr_text : str
        Raw OCR text.

    Returns
    -------
    dict
        Combined NLP + nutrition analysis.
    """

    if not ocr_text or not isinstance(ocr_text, str):
        return {
            "ingredients": [],
            "normalized_ingredients": [],
            "allergens": [],
            "additives": [],
            "nutrition": {}
        }

    # -----------------------------------------------------
    # M1 - Structured NLP analysis
    # -----------------------------------------------------

    parsed_result = analyze_food_label_text(ocr_text)

    ingredients = parsed_result.get(
        "ingredients",
        []
    )

    normalized_ingredients = parsed_result.get(
        "normalized_ingredients",
        []
    )

    allergens = parsed_result.get(
        "allergens",
        []
    )

    additives = parsed_result.get(
        "additives",
        []
    )

    # -----------------------------------------------------
    # M2 - Existing nutrition extraction
    # -----------------------------------------------------

    nutrition = extract_nutrition(ocr_text)

    if nutrition is None:
        nutrition = {}

    # -----------------------------------------------------
    # Combined result
    # -----------------------------------------------------

    return {
        "ingredients": ingredients,
        "normalized_ingredients": normalized_ingredients,
        "allergens": allergens,
        "additives": additives,
        "nutrition": nutrition
    }


def print_result(result):
    """
    Display the combined M1 + M2 result.
    """

    print()
    print("================================")
    print("NUTRILENS AI - M1 + M2 RESULT")
    print("================================")

    print()
    print("INGREDIENTS:")

    for ingredient in result.get("ingredients", []):
        print(f"- {ingredient}")

    print()
    print("NORMALIZED INGREDIENTS:")

    for ingredient in result.get(
        "normalized_ingredients",
        []
    ):
        print(f"- {ingredient}")

    print()
    print("ALLERGENS:")

    allergens = result.get("allergens", [])

    if allergens:
        for allergen in allergens:
            print(f"- {allergen}")
    else:
        print("- None detected")

    print()
    print("ADDITIVES / INS:")

    additives = result.get("additives", [])

    if additives:
        for additive in additives:
            print(f"- {additive}")
    else:
        print("- None detected")

    print()
    print("NUTRITION:")

    nutrition = result.get("nutrition", {})

    if nutrition:
        for key, value in nutrition.items():
            print(f"{key}: {value}")
    else:
        print("- No nutrition information detected")

    print()
    print("================================")
    print("JSON RESULT")
    print("================================")

    print(
        json.dumps(
            result,
            indent=4,
            ensure_ascii=False
        )
    )


# ---------------------------------------------------------
# TEST
# ---------------------------------------------------------

if __name__ == "__main__":

    sample_ocr_text = """
    Parle G Gluco BISCUITS

    INGREDIENTS:
    REFINED WHEAT FLOUR (MAIDA) (BY WHEAT),
    SUGAR,
    REFINED PALM OIL,
    INVERT SUGAR [SUGAR, CITRIC ACID],
    IODISED SALT,
    RAISING AGENTS (INS 503, INS 500),
    SOLIDS,
    FLOUR TREATMENT AGENT AND EMULSIFIER
    OF VEGETABLE ORIGIN (INS 472E),
    CONTAINS ADDED FLAVOUR,
    ARTIFICIAL FLAVOURING SUBSTANCES - VANILLA,
    GLUCOSE,
    LEVULOSE.

    CONTAINS:
    WHEAT, MILK

    NUTRITION INFORMATION
    Energy 480 kcal
    Protein 6 g
    Carbohydrate 65 g
    Total Sugars 25 g
    Total Fat 20 g
    Saturated Fat 10 g
    Trans Fat 0 g
    Dietary Fibre 3 g
    Sodium 400 mg
    Serving Size 50 g
    """

    result = analyze_label_text(sample_ocr_text)

    print_result(result)
