import re


# ============================================================
# NUTRITION EXTRACTION SERVICE - M2
# NutriLens AI
# ============================================================

"""
M2 Nutrition Extraction

Responsibilities:
- Extract nutrition values from OCR text
- Handle common OCR spelling errors
- Support common nutrition-label formats
- Detect nutrition basis
- Extract serving size
- Keep missing values missing
- NEVER assume missing nutrition values are 0
"""


# ============================================================
# NUTRIENT PATTERNS
# ============================================================

NUTRIENT_PATTERNS = {

    # --------------------------------------------------------
    # ENERGY
    # --------------------------------------------------------
    "energy_kcal": [
        r"\benergy\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*k\s*c\s*a\s*l\b",
        r"\benergy\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*kcal\b",
        r"\benergy\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*cal\b"
    ],

    # --------------------------------------------------------
    # PROTEIN
    # --------------------------------------------------------
    "protein_g": [
        r"\bprotein\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b"
    ],

    # --------------------------------------------------------
    # CARBOHYDRATE
    # --------------------------------------------------------
    "carbohydrate_g": [
        r"\bcarbohydrates?\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
        r"\bcarbs?\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b"
    ],

    # --------------------------------------------------------
    # SUGAR
    # --------------------------------------------------------
    "sugar_g": [
        r"\btotal\s+sugars?\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
        r"\btotal\s+sugar\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
        r"\bsugars?\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b"
    ],

    # --------------------------------------------------------
    # TOTAL FAT
    # --------------------------------------------------------
    "fat_g": [
        r"\btotal\s+fat\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
        r"\bfat\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b"
    ],

    # --------------------------------------------------------
    # SATURATED FAT
    # --------------------------------------------------------
    "saturated_fat_g": [
        r"\bsaturated\s+fat\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
        r"\bsaturates\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b"
    ],

    # --------------------------------------------------------
    # TRANS FAT
    # --------------------------------------------------------
    "trans_fat_g": [
        r"\btrans\s+fat\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b"
    ],

    # --------------------------------------------------------
    # FIBER / FIBRE
    # --------------------------------------------------------
    "fiber_g": [
        r"\bdietary\s+fiber\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
        r"\bdietary\s+fibre\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
        r"\bfiber\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b",
        r"\bfibre\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*g\b"
    ],

    # --------------------------------------------------------
    # SODIUM
    # --------------------------------------------------------
    "sodium_mg": [
        r"\bsodium\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*mg\b"
    ],

    # --------------------------------------------------------
    # CHOLESTEROL
    # --------------------------------------------------------
    "cholesterol_mg": [
        r"\bcholesterol\b\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*mg\b"
    ]
}


# ============================================================
# OCR CLEANING
# ============================================================

def clean_nutrition_text(text):
    """
    Clean OCR text before nutrition extraction.

    Important:
    - Corrects common OCR mistakes.
    - Does NOT create missing nutrition values.
    - Does NOT convert missing values to zero.
    """

    if not isinstance(text, str):
        return ""

    text = text.lower()

    # --------------------------------------------------------
    # Common OCR mistakes
    # --------------------------------------------------------

    replacements = {

        # kcal
        "kca1": "kcal",
        "kcai": "kcal",
        "kca": "kcal",

        # nutrient names
        "prote1n": "protein",
        "proteln": "protein",

        "carbohydrat": "carbohydrate",
        "carbohydratcs": "carbohydrates",
        "carbohydrat es": "carbohydrates",

        "sodlum": "sodium",
        "sodiurn": "sodium",
        "sodlum": "sodium",

        "sug ars": "sugars",

        # fibre / fiber
        "flbre": "fibre",
        "flber": "fiber",

        # fat
        "saturat ed": "saturated",

        # common OCR spelling
        "servlng": "serving",
        "servlngs": "servings"
    }

    for wrong, correct in replacements.items():
        text = text.replace(wrong, correct)

    # --------------------------------------------------------
    # Normalize whitespace
    # --------------------------------------------------------

    text = re.sub(r"[ \t]+", " ", text)

    # Keep newlines because they can help separate
    # nutrition-label rows.
    text = re.sub(r"\n\s*", "\n", text)

    return text.strip()


# ============================================================
# NUTRIENT EXTRACTION
# ============================================================

def extract_nutrient(text, patterns):
    """
    Return the first valid numeric value found.

    Missing value:
        None

    Never converts missing values to zero.
    """

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            try:
                value = float(match.group(1))

                # Reject impossible negative values.
                if value < 0:
                    continue

                return value

            except (ValueError, TypeError):
                continue

    return None


# ============================================================
# SERVING BASIS
# ============================================================

def detect_serving_basis(text):
    """
    Detect nutrition basis.

    Possible values:
        per_100g
        per_100ml
        per_serving
        unknown
    """

    text = text.lower()

    # --------------------------------------------------------
    # Per 100 g
    # --------------------------------------------------------

    if re.search(
        r"per\s*100\s*(?:g|gm|gms|gram|grams)",
        text
    ):
        return "per_100g"

    # --------------------------------------------------------
    # Per 100 ml
    # --------------------------------------------------------

    if re.search(
        r"per\s*100\s*(?:ml|milliliter|millilitres|milliliters)",
        text
    ):
        return "per_100ml"

    # --------------------------------------------------------
    # Per serving
    # --------------------------------------------------------

    if re.search(
        r"per\s*(?:serving|serve)",
        text
    ):
        return "per_serving"

    # --------------------------------------------------------
    # Serving size
    # --------------------------------------------------------

    if re.search(
        r"serving\s*size",
        text
    ):
        return "per_serving"

    return "unknown"


# ============================================================
# SERVING SIZE
# ============================================================

def extract_serving_size(text):
    """
    Extract serving size.

    Examples:
        Serving Size 50 g
        Serving Size: 50g
        Serving 50 g
    """

    patterns = [

        r"serving\s*size\s*[:\-]?\s*"
        r"(\d+(?:\.\d+)?)\s*(?:g|gm|gms|gram|grams)\b",

        r"serving\s*[:\-]?\s*"
        r"(\d+(?:\.\d+)?)\s*(?:g|gm|gms|gram|grams)\b"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            try:
                value = float(match.group(1))

                if value > 0:
                    return value

            except (ValueError, TypeError):
                continue

    return None


# ============================================================
# MAIN NUTRITION EXTRACTION
# ============================================================

def extract_nutrition(text):
    """
    Main M2 Nutrition Extraction function.

    Parameters
    ----------
    text : str
        OCR output.

    Returns
    -------
    dict
        Extracted nutrition information.

    Important:
    Missing nutrition values are NOT inserted as zero.
    """

    if not isinstance(text, str):
        raise ValueError(
            "Nutrition text must be a string."
        )

    # --------------------------------------------------------
    # Clean OCR text
    # --------------------------------------------------------

    text = clean_nutrition_text(text)

    nutrition = {}

    # --------------------------------------------------------
    # Extract nutrients
    # --------------------------------------------------------

    for nutrient, patterns in NUTRIENT_PATTERNS.items():

        value = extract_nutrient(
            text,
            patterns
        )

        # Only add the field if it was actually detected.
        if value is not None:
            nutrition[nutrient] = value

    # --------------------------------------------------------
    # Detect nutrition basis
    # --------------------------------------------------------

    nutrition["basis"] = detect_serving_basis(text)

    # --------------------------------------------------------
    # Extract serving size
    # --------------------------------------------------------

    serving_size = extract_serving_size(text)

    if serving_size is not None:
        nutrition["serving_size_g"] = serving_size

    return nutrition


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    sample_text = """
    NUTRITION INFORMATION

    Energy 480 kcal
    Protein 6 g
    Carbohydrate 70 g
    Total Sugars 25 g
    Total Fat 20 g
    Saturated Fat 10 g
    Trans Fat 0 g
    Dietary Fibre 3 g
    Sodium 400 mg

    Serving Size 50 g
    """

    print("================================")
    print("M2 NUTRITION EXTRACTION")
    print("================================")

    result = extract_nutrition(sample_text)

    print()

    for key, value in result.items():
        print(f"{key}: {value}")

    print()
    print("================================")