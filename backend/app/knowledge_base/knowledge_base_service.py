# backend/services/knowledge_base_service.py

import csv
import os
import re


# ============================================================
# PATH CONFIGURATION
# ============================================================

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

# Project root:
# backend/app/knowledge_base -> backend/app -> backend -> project root
PROJECT_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(CURRENT_DIR)
    )
)

KB_PATH = os.path.join(
    PROJECT_DIR,
    "data",
    "external",
    "m5",
    "nutrilens_knowledge_base_final.csv"
)

# ============================================================
# GLOBAL KNOWLEDGE BASE
# ============================================================

KNOWLEDGE_BASE = []


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(text):
    """
    Normalize ingredient text for matching.
    """

    if text is None:
        return ""

    text = str(text).strip().lower()

    # Remove brackets
    text = re.sub(r"[\(\)\[\]\{\}]", " ", text)

    # Replace common separators
    text = text.replace("_", " ")
    text = text.replace("-", " ")

    # Normalize multiple spaces
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_key(text):
    """
    Stronger normalization used for ingredient matching.

    Example:
        E472e -> e472e
        472e  -> e472e
        palm-oil -> palmoil
    """

    text = normalize_text(text)

    # Remove spaces and punctuation
    key = re.sub(r"[^a-z0-9]", "", text)

    # Normalize E-number format
    if re.match(r"^\d+[a-z]?$", key):
        key = "e" + key

    return key


# ============================================================
# CSV LOADING
# ============================================================

def load_knowledge_base():
    """
    Load Ingredient Knowledge Base CSV.
    """

    global KNOWLEDGE_BASE

    if not os.path.exists(KB_PATH):
        raise FileNotFoundError(
            f"Knowledge Base file not found:\n{KB_PATH}"
        )

    KNOWLEDGE_BASE = []

    with open(
        KB_PATH,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        for row in reader:

            cleaned_row = {}

            for key, value in row.items():

                if key is None:
                    continue

                cleaned_row[key.strip()] = (
                    value.strip()
                    if isinstance(value, str)
                    else value
                )

            KNOWLEDGE_BASE.append(cleaned_row)

    print(
        f"Ingredient Knowledge Base loaded: "
        f"{len(KNOWLEDGE_BASE)} ingredients"
    )

    return KNOWLEDGE_BASE


# ============================================================
# ALIAS EXTRACTION
# ============================================================

def get_aliases(row):
    """
    Extract aliases from the KB row.

    Supports aliases separated by:
    - comma
    - semicolon
    - pipe
    """

    aliases = []

    ingredient = row.get("ingredient", "")

    if ingredient:
        aliases.append(ingredient)

    alias_text = row.get("aliases", "")

    if alias_text:

        parts = re.split(
            r"[,;|]",
            alias_text
        )

        for part in parts:

            part = part.strip()

            if part:
                aliases.append(part)

    return aliases


# ============================================================
# BUILD MATCH INDEX
# ============================================================

def build_match_index():
    """
    Create a fast lookup dictionary for ingredients
    and aliases.
    """

    index = {}

    for row in KNOWLEDGE_BASE:

        aliases = get_aliases(row)

        for alias in aliases:

            key = normalize_key(alias)

            if not key:
                continue

            # First occurrence gets priority
            if key not in index:
                index[key] = row

    return index


MATCH_INDEX = {}


# ============================================================
# INGREDIENT MATCHING
# ============================================================

def find_ingredient(ingredient):
    """
    Find an ingredient in the Knowledge Base.

    Matching order:
    1. Exact normalized match
    2. E-number normalized match
    3. Conservative phrase match
    """

    if not ingredient:
        return None, None

    ingredient_clean = normalize_text(ingredient)
    ingredient_key = normalize_key(ingredient)

    # --------------------------------------------------------
    # Exact match
    # --------------------------------------------------------

    if ingredient_key in MATCH_INDEX:

        return (
            MATCH_INDEX[ingredient_key],
            "exact"
        )

    # --------------------------------------------------------
    # E-number alternative
    # --------------------------------------------------------

    if ingredient_key.startswith("e"):

        without_e = ingredient_key[1:]

        if without_e in MATCH_INDEX:

            return (
                MATCH_INDEX[without_e],
                "e_number"
            )

    else:

        with_e = "e" + ingredient_key

        if with_e in MATCH_INDEX:

            return (
                MATCH_INDEX[with_e],
                "e_number"
            )

    # --------------------------------------------------------
    # Conservative phrase matching
    # --------------------------------------------------------

    for row in KNOWLEDGE_BASE:

        aliases = get_aliases(row)

        for alias in aliases:

            alias_clean = normalize_text(alias)

            if len(alias_clean) < 4:
                continue

            if (
                alias_clean in ingredient_clean
                or ingredient_clean in alias_clean
            ):

                return (
                    row,
                    "phrase"
                )

    return None, None


# ============================================================
# LONG-TERM RISK CHECK
# ============================================================

def has_long_term_risk(row):
    """
    Determine whether KB contains meaningful
    long-term risk information.
    """

    risk = str(
        row.get("long_term_risk", "")
    ).strip().lower()

    if not risk:
        return False

    ignored_values = {
        "",
        "not established",
        "none",
        "nan",
        "n/a",
        "na",
        "unknown"
    }

    return risk not in ignored_values


# ============================================================
# ALLERGEN CHECK
# ============================================================

def is_allergen(row):
    """
    Determine whether an ingredient is associated
    with an allergen concern.
    """

    concern_type = str(
        row.get("concern_type", "")
    ).lower()

    category = str(
        row.get("category", "")
    ).lower()

    avoid_for = str(
        row.get("avoid_for", "")
    ).lower()

    combined = (
        concern_type + " "
        + category + " "
        + avoid_for
    )

    return (
        "allergen" in combined
        or "allergy" in combined
    )


# ============================================================
# CREATE DETAIL RESULT
# ============================================================

def create_detail(
    input_ingredient,
    row,
    matched_by
):
    """
    Convert KB row into API-friendly structure.
    """

    return {
        "input_ingredient": input_ingredient,

        "matched": True,

        "matched_by": matched_by,

        "ingredient": row.get(
            "ingredient",
            ""
        ),

        "aliases": row.get(
            "aliases",
            ""
        ),

        "category": row.get(
            "category",
            ""
        ),

        "concern_level": row.get(
            "concern_level",
            ""
        ),

        "concern_type": row.get(
            "concern_type",
            ""
        ),

        "reason": row.get(
            "reason",
            ""
        ),

        "possible_effect": row.get(
            "possible_effect",
            ""
        ),

        "usage": row.get(
            "usage",
            ""
        ),

        "avoid_for": row.get(
            "avoid_for",
            ""
        ),

        "source": row.get(
            "source",
            ""
        ),

        "product_count": row.get(
            "product_count",
            ""
        ),

        "long_term_risk": row.get(
            "long_term_risk",
            ""
        )
    }


# ============================================================
# CREATE UNMATCHED DETAIL
# ============================================================

def create_unmatched_detail(ingredient):
    """
    Create result for an ingredient that is not
    present in the Knowledge Base.
    """

    return {
        "input_ingredient": ingredient,

        "matched": False,

        "matched_by": None,

        "ingredient": ingredient,

        "aliases": "",

        "category": "Unknown",

        "concern_level": "Unknown",

        "concern_type": "Unknown",

        "reason": (
            "Ingredient was not found in the "
            "NutriLens Ingredient Knowledge Base."
        ),

        "possible_effect": "",

        "usage": "",

        "avoid_for": "",

        "source": "",

        "product_count": "",

        "long_term_risk": "Not established"
    }


# ============================================================
# SUMMARY CREATION
# ============================================================

def create_summary(details):
    """
    Generate summary statistics from ingredient analysis.
    """

    total = len(details)

    matched = sum(
        1 for item in details
        if item.get("matched") is True
    )

    unmatched = total - matched

    moderate = sum(
        1
        for item in details
        if str(
            item.get("concern_level", "")
        ).lower()
        == "moderate"
    )

    context_dependent = sum(
        1
        for item in details
        if str(
            item.get("concern_level", "")
        ).lower()
        in {
            "context-dependent",
            "context dependent"
        }
    )

    low = sum(
        1
        for item in details
        if str(
            item.get("concern_level", "")
        ).lower()
        == "low"
    )

    nutrient = sum(
        1
        for item in details
        if str(
            item.get("concern_level", "")
        ).lower()
        == "nutrient"
    )

    no_concern = sum(
        1
        for item in details
        if str(
            item.get("concern_level", "")
        ).lower()
        == "no concern"
    )

    long_term = sum(
        1
        for item in details
        if item.get("matched")
        and has_long_term_risk(item)
    )

    allergen = sum(
        1
        for item in details
        if item.get("matched")
        and is_allergen(item)
    )

    return {

        "total_ingredients": total,

        "matched": matched,

        "unmatched": unmatched,

        "moderate": moderate,

        "context_dependent": context_dependent,

        "low": low,

        "nutrient": nutrient,

        "no_concern": no_concern,

        "long_term_risk": long_term,

        "allergen": allergen
    }


# ============================================================
# MAIN ANALYSIS FUNCTION
# ============================================================

def analyze_ingredients(ingredients_text):
    """
    Analyze ingredient text using the NutriLens
    Ingredient Knowledge Base.

    Input:
        "wheat flour, sugar, palm oil, salt"

    Output:
        {
            "details": [...],
            "summary": {...}
        }
    """

    global MATCH_INDEX

    # --------------------------------------------------------
    # Load Knowledge Base
    # --------------------------------------------------------

    if not KNOWLEDGE_BASE:
        load_knowledge_base()

    # --------------------------------------------------------
    # Build matching index
    # --------------------------------------------------------

    if not MATCH_INDEX:
        MATCH_INDEX = build_match_index()

    # --------------------------------------------------------
    # Handle list input
    # --------------------------------------------------------

    if isinstance(ingredients_text, list):

        ingredients = ingredients_text

    else:

        if ingredients_text is None:
            ingredients_text = ""

        ingredients_text = str(
            ingredients_text
        )

        # Split on comma or semicolon
        ingredients = re.split(
            r"[,;]",
            ingredients_text
        )

    # --------------------------------------------------------
    # Clean ingredients
    # --------------------------------------------------------

    cleaned_ingredients = []

    for ingredient in ingredients:

        ingredient = str(
            ingredient
        ).strip()

        if not ingredient:
            continue

        # Remove unnecessary surrounding punctuation
        ingredient = ingredient.strip(
            " .:-"
        )

        if ingredient:
            cleaned_ingredients.append(
                ingredient
            )

    # --------------------------------------------------------
    # Analyze each ingredient
    # --------------------------------------------------------

    details = []

    for ingredient in cleaned_ingredients:

        row, matched_by = find_ingredient(
            ingredient
        )

        if row is not None:

            detail = create_detail(
                ingredient,
                row,
                matched_by
            )

        else:

            detail = create_unmatched_detail(
                ingredient
            )

        details.append(detail)

    # --------------------------------------------------------
    # Create summary
    # --------------------------------------------------------

    summary = create_summary(
        details
    )

    return {
        "details": details,
        "summary": summary
    }


# ============================================================
# COMPATIBILITY ALIAS
# ============================================================

def analyze_label_text(ocr_result):
    """
    Compatibility wrapper.

    This function allows other parts of NutriLens
    to call the KB service using analyze_label_text().
    """

    if isinstance(ocr_result, dict):

        ingredients = ocr_result.get(
            "normalized_ingredients",
            ocr_result.get(
                "ingredients",
                ""
            )
        )

    else:

        ingredients = ocr_result

    return analyze_ingredients(
        ingredients
    )


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    print("\n" + "=" * 60)
    print("NUTRILENS KNOWLEDGE BASE TEST")
    print("=" * 60)

    try:

        load_knowledge_base()

        MATCH_INDEX = build_match_index()

        test_ingredients = (
            "wheat flour, sugar, "
            "vegetable oil, palm oil, "
            "salt, milk powder, "
            "artificial flavour"
        )

        result = analyze_ingredients(
            test_ingredients
        )

        print("\nINPUT:")
        print(test_ingredients)

        print("\nINGREDIENT ANALYSIS:")

        for item in result["details"]:

            print(
                f"\nIngredient: "
                f"{item['input_ingredient']}"
            )

            print(
                f"Matched: "
                f"{item['matched']}"
            )

            print(
                f"KB Ingredient: "
                f"{item['ingredient']}"
            )

            print(
                f"Concern Level: "
                f"{item['concern_level']}"
            )

            print(
                f"Concern Type: "
                f"{item['concern_type']}"
            )

            print(
                f"Long-Term Risk: "
                f"{item['long_term_risk']}"
            )

        print("\nSUMMARY:")

        for key, value in result[
            "summary"
        ].items():

            print(
                f"{key}: {value}"
            )

        print("\n" + "=" * 60)
        print("KNOWLEDGE BASE TEST COMPLETED")
        print("=" * 60)

    except Exception as e:

        print("\nERROR:")
        print(e)

        raise
