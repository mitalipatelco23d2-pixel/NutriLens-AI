"""
NutriLens AI
Ingredient Extraction and Normalization
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .normalizer import normalize_label_value, unique_casefold


@dataclass
class IngredientSectionResult:
    ingredients: list[str]
    warnings: list[str]
    section_detected: bool
    heading: str | None
    truncated: bool


INGREDIENT_START_PATTERN = re.compile(
    r"\b(?P<heading>ingredients?|composition)\s*[:\-]",
    re.IGNORECASE,
)

NUTRITION_START_PATTERN = re.compile(
    r"""
    \b(?:
        nutrition(?:al)?\s+(?:information|facts?|values?) |
        nutrition\s*[:\-]? |
        energy(?:\s*[:\-]|\s+(?=\d)) |
        calories?(?:\s*[:\-]|\s+(?=\d)) |
        protein(?:\s*[:\-]|\s+(?=\d)) |
        carbohydrate(?:s)?(?:\s*[:\-]|\s+(?=\d)) |
        total\s+sugars?(?:\s*[:\-]|\s+(?=\d)) |
        added\s+sugars?(?:\s*[:\-]|\s+(?=\d)) |
        total\s+fat(?:\s*[:\-]|\s+(?=\d)) |
        saturated\s+fat(?:\s*[:\-]|\s+(?=\d)) |
        trans\s+fat(?:\s*[:\-]|\s+(?=\d)) |
        dietary\s+fib(?:re|er)(?:\s*[:\-]|\s+(?=\d)) |
        sodium(?:\s*[:\-]|\s+(?=\d)) |
        serving\s+size(?:\s*[:\-]|\s+(?=\d))
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

CONTAINS_PATTERN = re.compile(
    r"\bcontains?\s*:",
    re.IGNORECASE,
)


def extract_ingredient_section(
    text: str,
) -> IngredientSectionResult:

    warnings: list[str] = []

    if not text or not isinstance(text, str):
        return IngredientSectionResult(
            ingredients=[],
            warnings=["No usable ingredient text was supplied."],
            section_detected=False,
            heading=None,
            truncated=False,
        )

    text = re.sub(r"\s+", " ", text).strip()

    start_match = INGREDIENT_START_PATTERN.search(text)

    if start_match:
        heading = start_match.group("heading")
        ingredient_text = text[start_match.end():]
        section_detected = True
    else:
        heading = None
        ingredient_text = text
        section_detected = False

        warnings.append(
            "Ingredient section heading was not detected; "
            "the available text was used as a fallback."
        )

    truncated = False

    nutrition_match = NUTRITION_START_PATTERN.search(
        ingredient_text
    )

    contains_match = CONTAINS_PATTERN.search(
        ingredient_text
    )

    boundaries = [
        match.start()
        for match in (
            nutrition_match,
            contains_match,
        )
        if match is not None
    ]

    if boundaries:
        ingredient_text = ingredient_text[:min(boundaries)]
        truncated = True

    ingredient_text = ingredient_text.strip(" .;:-")

    ingredients = split_ingredient_text(
        ingredient_text
    )

    if not ingredients:
        warnings.append(
            "No ingredients were detected in the ingredient section."
        )

    return IngredientSectionResult(
        ingredients=ingredients,
        warnings=warnings,
        section_detected=section_detected,
        heading=heading,
        truncated=truncated,
    )


def split_ingredient_text(
    ingredient_text: str,
) -> list[str]:

    if not ingredient_text:
        return []

    ingredient_starts = (
        r"sugar"
        r"|refined\s+palm\s+oil"
        r"|palm\s+oil"
        r"|invert\s+sugar"
        r"|[il]odi[sz]ed\s+salt"
        r"|salt"
        r"|raising\s+agents?"
        r"|milk(?:\s+solids?)?"
        r"|flour\s+treatment\s+agent"
        r"|emulsifier"
        r"|added\s+flavou?r"
        r"|artificial\s+flavou?r"
        r"|glucose"
        r"|levulose"
    )

    text = re.sub(
        r";\s*",
        ", ",
        ingredient_text,
    )

    text = re.sub(
        rf",\s*(?=(?:{ingredient_starts})\b)",
        "|||",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"(\d+\s*%)\s*,\s*(?=[A-Za-z])",
        r"\1|||",
        text,
    )

    raw_parts = text.split("|||")

    cleaned_parts: list[str] = []

    for part in raw_parts:

        part = normalize_label_value(part)

        if not part:
            continue

        part = part.strip(" .;:-")

        if part:
            cleaned_parts.append(part)

    return cleaned_parts


def extract_ingredients_from_text(
    text: str,
) -> list[str]:

    result = extract_ingredient_section(text)

    return result.ingredients


def extract_ingredients(
    text: str,
) -> list[str]:

    result = extract_ingredient_section(text)

    return result.ingredients


def normalize_ingredient_name(
    name: str,
) -> str:

    value = normalize_label_value(name)
    value = value.lower()
    value = value.strip(" .;:-")

    # Remove common descriptive words.
    value = re.sub(
        r"\brefined\b",
        "",
        value,
    )

    value = re.sub(
        r"\bprocessed\b",
        "",
        value,
    )

    # Wheat flour / maida.
    if re.search(
        r"\b(?:wheat\s+flour|maida)\b",
        value,
        re.IGNORECASE,
    ):
        return "wheat flour"

    # Oils.
    if re.search(
        r"\bpalm\s+oil\b",
        value,
        re.IGNORECASE,
    ):
        return "palm oil"

    if re.search(
        r"\bsunflower\s+oil\b",
        value,
        re.IGNORECASE,
    ):
        return "sunflower oil"

    if re.search(
        r"\bvegetable\s+oil\b",
        value,
        re.IGNORECASE,
    ):
        return "vegetable oil"

    # Invert sugar and its sub-ingredient.
    if "invert sugar" in value:
        if "citric acid" in value:
            return "invert sugar citric acid"
        return "invert sugar"

    # Salt.
    # Handles both correct OCR and common OCR confusion:
    # IODISED / IODIZED / LODISED / LODIZED.
    if re.search(
        r"\b[il]odi[sz]ed\s+salt\b",
        value,
        re.IGNORECASE,
    ):
        return "salt"

    if value == "salt":
        return "salt"

    # Sugar.
    if value == "sugar":
        return "sugar"

    # Milk.
    if re.search(
        r"\bmilk\s+(?:powder|solids?)\b",
        value,
        re.IGNORECASE,
    ):
        return "milk"

    if value == "milk":
        return "milk"

    # Other common ingredients.
    if value in {"wheat"}:
        return "wheat"

    if value in {"almond", "almonds"}:
        return "almonds"

    if value in {"raisin", "raisins"}:
        return "raisins"

    if re.search(
        r"\bsunflower\s+seeds?\b",
        value,
        re.IGNORECASE,
    ):
        return "sunflower seeds"

    if value in {"oat", "oats"}:
        return "oats"

    if value == "citric acid":
        return "citric acid"

    if re.search(
        r"\braising\s+agents?\b",
        value,
        re.IGNORECASE,
    ):
        return "raising agents"

    if re.search(
        r"\bglucose\b",
        value,
        re.IGNORECASE,
    ):
        return "glucose"

    if re.search(
        r"\blevulose\b",
        value,
        re.IGNORECASE,
    ):
        return "levulose"

    if re.search(
        r"\bemulsifier\b",
        value,
        re.IGNORECASE,
    ):
        return "emulsifier"

    if re.search(
        r"\bflour\s+treatment\s+agent\b",
        value,
        re.IGNORECASE,
    ):
        return "flour treatment agent"

    if re.search(
        r"\badded\s+flavou?r\b",
        value,
        re.IGNORECASE,
    ):
        return "added flavour"

    # Safety cleanup.
    value = re.sub(
        r"\bcontains?\s*:?.*$",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()

    # INS codes.
    if re.fullmatch(
        r"ins\s*\d+[a-z]?",
        value,
        re.IGNORECASE,
    ):
        return re.sub(
            r"\s+",
            "",
            value,
        ).upper()

    # OCR artefact cleanup.
    value = re.sub(
        r"\b(?:d|dl|di)\s+(?=glucose|levulose)\b",
        "",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    ).strip(" .;:-")

    return value


def normalize_ingredient_list(
    ingredients: list[str],
) -> list[str]:

    normalized = (
        normalize_ingredient_name(item)
        for item in ingredients
    )

    return unique_casefold(normalized)


def extract_ingredients_for_ml(
    text: str,
) -> list[str]:

    return normalize_ingredient_list(
        extract_ingredients(text)
    )
