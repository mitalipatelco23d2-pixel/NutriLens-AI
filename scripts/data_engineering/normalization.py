"""Deterministic unit, text, multilingual, barcode, and sodium/salt normalization."""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from scripts.data_engineering.schemas import NutrientValue, ValueOrigin

ENERGY_KJ_PER_KCAL = Decimal("4.184")
SALT_TO_SODIUM_FACTOR = Decimal("2.5")
UNIT_ALIASES = {
    "g": "g",
    "mg": "mg",
    "kg": "kg",
    "mcg": "mcg",
    "kcal": "kcal",
    "kj": "kJ",
    "ml": "mL",
    "\u00b5g": "mcg",
    "\u03bcg": "mcg",
    "ug": "mcg",
    "microgram": "mcg",
    "micrograms": "mcg",
    "milligram": "mg",
    "milligrams": "mg",
    "gram": "g",
    "grams": "g",
    "kilogram": "kg",
    "kilograms": "kg",
    "kilocalorie": "kcal",
    "kilocalories": "kcal",
    "kilojoule": "kJ",
    "kilojoules": "kJ",
    "l": "L",
    "liter": "L",
    "litre": "L",
    "milliliter": "mL",
    "millilitre": "mL",
}
MASS_TO_G = {
    "mcg": Decimal("0.000001"),
    "mg": Decimal("0.001"),
    "g": Decimal(1),
    "kg": Decimal(1000),
}
VOLUME_TO_ML = {"mL": Decimal(1), "L": Decimal(1000)}

SCHEDULED_LANGUAGE_CODES = {
    "as",
    "bn",
    "brx",
    "doi",
    "gu",
    "hi",
    "kn",
    "ks",
    "kok",
    "mai",
    "ml",
    "mni",
    "mr",
    "ne",
    "or",
    "pa",
    "sa",
    "sat",
    "sd",
    "ta",
    "te",
    "ur",
}
SUPPORTED_LANGUAGE_CODES = SCHEDULED_LANGUAGE_CODES | {"en", "und"}
LANGUAGE_CODE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$")


def canonical_unit(unit: str) -> str:
    value = unicodedata.normalize("NFKC", unit).strip()
    return UNIT_ALIASES.get(value.lower(), value)


def convert_unit(value: float, source_unit: str, target_unit: str) -> float:
    source = canonical_unit(source_unit)
    target = canonical_unit(target_unit)
    number = Decimal(str(value))
    if source == target:
        return float(number)
    if source in MASS_TO_G and target in MASS_TO_G:
        return float(number * MASS_TO_G[source] / MASS_TO_G[target])
    if source in VOLUME_TO_ML and target in VOLUME_TO_ML:
        return float(number * VOLUME_TO_ML[source] / VOLUME_TO_ML[target])
    if source == "kcal" and target == "kJ":
        return float(number * ENERGY_KJ_PER_KCAL)
    if source == "kJ" and target == "kcal":
        return float(number / ENERGY_KJ_PER_KCAL)
    raise ValueError(f"incompatible or unsupported unit conversion: {source} -> {target}")


def normalize_reported_value(
    value: float, source_unit: str, target_unit: str, *, source_nutrient_id: str | None = None
) -> NutrientValue:
    if value < 0:
        raise ValueError("negative nutrient values are invalid")
    normalized = convert_unit(value, source_unit, target_unit)
    source = canonical_unit(source_unit)
    target = canonical_unit(target_unit)
    origin = ValueOrigin.REPORTED if source == target else ValueOrigin.CONVERTED
    method = (
        "reported_without_conversion" if source == target else f"deterministic_{source}_to_{target}"
    )
    return NutrientValue(
        source_nutrient_id=source_nutrient_id,
        original_value=value,
        original_unit=source,
        normalized_value=normalized,
        normalized_unit=target,
        normalization_method=method,
        value_origin=origin,
    )


def derive_salt_from_sodium(sodium_mg: NutrientValue) -> NutrientValue:
    if sodium_mg.normalized_value is None or sodium_mg.normalized_unit != "mg":
        raise ValueError("reported sodium in mg is required for salt derivation")
    salt_g = Decimal(str(sodium_mg.normalized_value)) * SALT_TO_SODIUM_FACTOR / Decimal(1000)
    return NutrientValue(
        source_nutrient_id=sodium_mg.source_nutrient_id,
        original_value=None,
        original_unit=None,
        normalized_value=float(salt_g),
        normalized_unit="g",
        normalization_method="salt_g = sodium_mg * 2.5 / 1000",
        value_origin=ValueOrigin.DERIVED,
        quality_flag="DERIVED_FROM_REPORTED_SODIUM",
    )


def derive_sodium_from_salt(salt_g: NutrientValue) -> NutrientValue:
    if salt_g.normalized_value is None or salt_g.normalized_unit != "g":
        raise ValueError("reported salt in g is required for sodium derivation")
    sodium_mg = Decimal(str(salt_g.normalized_value)) * Decimal(1000) / SALT_TO_SODIUM_FACTOR
    return NutrientValue(
        source_nutrient_id=salt_g.source_nutrient_id,
        original_value=None,
        original_unit=None,
        normalized_value=float(sodium_mg),
        normalized_unit="mg",
        normalization_method="sodium_mg = salt_g * 1000 / 2.5",
        value_origin=ValueOrigin.DERIVED,
        quality_flag="DERIVED_FROM_REPORTED_SALT",
    )


def normalize_unicode(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def normalize_display_text(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_unicode(text)).strip()


def matching_key(text: str) -> str:
    return normalize_display_text(text).casefold()


def normalize_ingredient_text(text: str) -> str:
    value = normalize_display_text(text)
    translation: dict[int, str] = {
        ord("["): "(",
        ord("]"): ")",
        ord("{"): "(",
        ord("}"): ")",
        ord(";"): ",",
    }
    value = value.translate(translation)
    value = re.sub(r"\s*,\s*", ", ", value)
    value = re.sub(
        r"\b[eE][\s-]*(\d{3,4}[a-zA-Z]?)\b", lambda match: f"E{match.group(1).upper()}", value
    )
    value = re.sub(
        r"\b[iI][nN][sS][\s-]*(\d{3,4}[a-zA-Z]?)\b",
        lambda match: f"INS {match.group(1).upper()}",
        value,
    )
    value = re.sub(r"(\d+(?:\.\d+)?)\s+%", r"\1%", value)
    return value


def standardize_language_code(code: str) -> str:
    value = normalize_display_text(code).replace("_", "-").lower()
    if not LANGUAGE_CODE.fullmatch(value):
        raise ValueError(f"invalid language code: {code}")
    return value


def normalize_language_code(code: str) -> str:
    value = standardize_language_code(code)
    primary = value.split("-", maxsplit=1)[0]
    if primary not in SUPPORTED_LANGUAGE_CODES:
        raise ValueError(f"unsupported R2 language code: {code}")
    return value


def validate_unicode_text(text: str) -> bool:
    try:
        round_trip = text.encode("utf-8").decode("utf-8")
    except UnicodeError:
        return False
    return round_trip == text and "\ufffd" not in text


def validate_gtin(barcode: str) -> bool:
    if not barcode.isdigit() or len(barcode) not in {8, 12, 13, 14}:
        return False
    digits = [int(char) for char in barcode]
    body = digits[:-1]
    total = sum(digit * (3 if (len(body) - index) % 2 else 1) for index, digit in enumerate(body))
    return (10 - total % 10) % 10 == digits[-1]
