"""
NutriLens AI
M1 NLP + M2 Nutrition Integration

M1:
- Ingredient extraction
- Ingredient normalization
- Allergen detection
- Additive / INS detection
- Knowledge Base analysis

M2:
- Nutrition extraction

Output:
A single combined result that can later be passed
to the ML risk prediction module.
"""

import os
import sys
import json

# ---------------------------------------------------------
# PATH SETUP
# ---------------------------------------------------------

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Add services directory to Python path
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)


# ---------------------------------------------------------
# IMPORT M1 + M2
# ---------------------------------------------------------

from text_cleaner import process_label_text
from nutrition_service import extract_nutrition


# ---------------------------------------------------------
# M1 + M2 MAIN FUNCTION
# ---------------------------------------------------------

def analyze_label_text(ocr_text):
    """
    Complete NutriLens AI label analysis.

    Parameters
    ----------
    ocr_text : str
        Raw text obtained from OCR.

    Returns
    -------
    dict
        Combined M1 NLP + M2 Nutrition result.
    """

    if not ocr_text or not isinstance(ocr_text, str):
        return {
            "ingredients": [],
            "normalized_ingredients": [],
            "allergens": [],
            "additives": [],
            "nutrition": {}
        }

    # =====================================================
    # M1 - NLP / INGREDIENT ANALYSIS
    # =====================================================

    cleaned_data = process_label_text(ocr_text)

    ingredients = cleaned_data.get("ingredients", [])
    normalized_ingredients = cleaned_data.get(
        "normalized_ingredients",
        []
    )
    allergens = cleaned_data.get("allergens", [])
    additives = cleaned_data.get("additives", [])

    # =====================================================
    # M2 - NUTRITION EXTRACTION
    # =====================================================

    nutrition = extract_nutrition(ocr_text)

    # Safety check
    if nutrition is None:
        nutrition = {}

    # =====================================================
    # COMBINED RESULT
    # =====================================================

    result = {
        "ingredients": ingredients,
        "normalized_ingredients": normalized_ingredients,
        "allergens": allergens,
        "additives": additives,
        "nutrition": nutrition
    }

    return result


# ---------------------------------------------------------
# DISPLAY RESULT
# ---------------------------------------------------------

def print_result(result):
    """
    Display the combined M1 + M2 result
    in a readable format.
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
        "normalized_ingredients", []
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

    # Sample OCR output
    # This is the OCR text you obtained from Parle-G.

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

    # -----------------------------------------------------
    # RUN M1 + M2
    # -----------------------------------------------------

    result = analyze_label_text(sample_ocr_text)

    # -----------------------------------------------------
    # DISPLAY
    # -----------------------------------------------------

    print_result(result)