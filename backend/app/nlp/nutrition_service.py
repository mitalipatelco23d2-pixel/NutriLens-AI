from __future__ import annotations

import re


# ============================================================
# OCR CLEANING
# ============================================================

def clean_nutrition_text(text: str) -> str:
    """
    Clean OCR text before extracting nutrition values.

    Important:
    - Corrects common OCR mistakes.
    - Does not assume missing nutrients are zero.
    - Preserves newlines because nutrition labels often use rows.
    """

    if not isinstance(text, str):
        raise ValueError("Nutrition text must be a string.")

    text = text.lower()

    # --------------------------------------------------------
    # Common OCR word corrections
    # --------------------------------------------------------

    replacements = {
        "kca1": "kcal",
        "kcai": "kcal",
        "prote1n": "protein",
        "proteln": "protein",
        "carbohydrat": "carbohydrate",
        "carbohydratcs": "carbohydrates",
        "carbohydrat es": "carbohydrates",
        "sodlum": "sodium",
        "sodiurn": "sodium",
        "sug ars": "sugars",
        "flbre": "fibre",
        "flber": "fiber",
        "saturat ed": "saturated",
        "servlng": "serving",
        "servlngs": "servings",
    }

    for wrong, correct in replacements.items():
        text = re.sub(
            rf"\b{re.escape(wrong)}\b",
            correct,
            text,
        )

    # --------------------------------------------------------
    # Correct common OCR mistakes inside numeric values
    # --------------------------------------------------------
    #
    # Examples:
    #   4O0 -> 400
    #   1I0 -> 110
    #
    # Only replace O/I when they occur between digits.
    # --------------------------------------------------------

    text = re.sub(r"(?<=\d)[oO](?=\d)", "0", text)
    text = re.sub(r"(?<=\d)[iI](?=\d)", "1", text)

    # --------------------------------------------------------
    # Normalize whitespace
    # --------------------------------------------------------

    text = re.sub(r"[ \t]+", " ", text)

    # Keep newlines because they can help separate
    # nutrition-label rows.
    text = re.sub(r"\n\s*", "\n", text)

    return text.strip()


# ============================================================
# NUTRIENT PATTERNS
# ============================================================

NUTRIENT_PATTERNS = {
    "energy_kcal": [
        r"\benergy\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*kcal\b",
    ],
    "protein_g": [
        r"\bprotein\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
    ],
    "carbohydrate_g": [
        r"\bcarbohydrates?\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
    ],
    "sugar_g": [
        r"\b(?:total\s+)?sugars?\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
    ],
    "fat_g": [
        r"\b(?:total\s+)?fat\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
    ],
    "saturated_fat_g": [
        r"\bsaturated\s+fat\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
    ],
    "trans_fat_g": [
        r"\btrans\s+fat\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
    ],
    "fiber_g": [
        r"\b(?:dietary\s+)?fib(?:re|er)\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
    ],
    "sodium_mg": [
        r"\bsodium\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*mg\b",
    ],
    "salt_g": [
        r"\bsalt\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
    ],
    "cholesterol_mg": [
        r"\bcholesterol\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*mg\b",
    ],
    "calcium_mg": [
        r"\bcalcium\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*mg\b",
    ],
}


# ============================================================
# EXTRACT ONE NUTRIENT
# ============================================================

def extract_nutrient(
    text: str,
    patterns: list[str],
) -> float | None:
    """
    Extract the first valid non-negative nutrient value.
    """

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if not match:
            continue

        try:
            value = float(match.group(1))
        except (TypeError, ValueError):
            continue

        if value < 0:
            return None

        return value

    return None


# ============================================================
# NUTRITION BASIS
# ============================================================

def detect_serving_basis(text: str) -> str:
    """
    Detect whether nutrition values are given per 100 g,
    per 100 ml, or per serving.
    """

    normalized = clean_nutrition_text(text)

    if re.search(r"\bper\s*100\s*g\b", normalized):
        return "per_100g"

    if re.search(r"\bper\s*100\s*ml\b", normalized):
        return "per_100ml"

    if re.search(r"\bper\s+serving\b", normalized):
        return "per_serving"

    if re.search(r"\bserving\s+size\b", normalized):
        return "per_serving"

    return "unknown"


# ============================================================
# SERVING SIZE
# ============================================================

def extract_serving_size(text: str) -> float | None:
    """
    Extract serving size in grams when explicitly available.
    """

    normalized = clean_nutrition_text(text)

    patterns = [
        r"\bserving\s+size\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
        r"\bserving\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*grams?\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)

        if match:
            try:
                value = float(match.group(1))

                if value >= 0:
                    return value

            except (TypeError, ValueError):
                pass

    return None


# ============================================================
# COMPLETE NUTRITION EXTRACTION
# ============================================================

def extract_nutrition(text: str) -> dict:
    """
    Extract nutrition information from OCR text.

    Missing nutrients are NOT added as zero.
    Zero is preserved only when the label explicitly says zero.
    """

    if not isinstance(text, str):
        raise ValueError("Nutrition text must be a string.")

    cleaned_text = clean_nutrition_text(text)

    result = {}

    # --------------------------------------------------------
    # Extract nutrients
    # --------------------------------------------------------

    for nutrient_name, patterns in NUTRIENT_PATTERNS.items():
        value = extract_nutrient(cleaned_text, patterns)

        if value is not None:
            result[nutrient_name] = value

    # --------------------------------------------------------
    # Detect nutrition basis
    # --------------------------------------------------------

    result["basis"] = detect_serving_basis(cleaned_text)

    # --------------------------------------------------------
    # Extract serving size
    # --------------------------------------------------------

    serving_size = extract_serving_size(cleaned_text)

    if serving_size is not None:
        result["serving_size_g"] = serving_size

    return result


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    sample_text = """
    Nutrition Information

    Energy 480 kcal
    Protein 6 g
    Carbohydrates 70 g
    Total Sugars 25 g
    Total Fat 20 g
    Saturated Fat 10 g
    Trans Fat 0 g
    Dietary Fibre 3 g
    Sodium 400 mg

    Serving Size 50 g
    """

    result = extract_nutrition(sample_text)

    print("================================")
    print("M2 NUTRITION EXTRACTION")
    print("================================")
    print()

    for key, value in result.items():
        print(f"{key}: {value}")
