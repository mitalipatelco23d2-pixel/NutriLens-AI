"""Canonical product and ingredient-text normalization adapter."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from scripts.data_engineering.normalization import (
    matching_key,
    normalize_display_text,
    normalize_ingredient_text,
    standardize_language_code,
    validate_gtin,
)
from scripts.data_engineering.quality import transparent_quality_score
from scripts.data_engineering.schemas import Lineage, ProductRecord


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    number = float(value)
    if number < 0:
        raise ValueError("negative product/serving quantities are invalid")
    return number


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in {None, ""}:
        return False
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def _languages(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        candidates = re.split(r"[;,|]", value)
    elif isinstance(value, list | tuple | set):
        candidates = [str(item) for item in value]
    else:
        raise ValueError("languages must be a string or sequence")
    return [standardize_language_code(item) for item in candidates if item.strip()]


def normalize_product(row: dict[str, Any], lineage: Lineage) -> ProductRecord:
    source_id = str(row.get("source_product_id", "")).strip()
    name_original = str(row.get("product_name", "")).strip()
    if not source_id:
        raise ValueError("MISSING_REQUIRED_ID")
    if not name_original:
        raise ValueError("MISSING_PRODUCT_NAME")
    brand_original = str(row.get("brand", "")).strip() or None
    barcode = str(row.get("barcode", "")).strip() or None
    ingredients_original = str(row.get("ingredients", "")).strip() or None
    completeness_fields = [barcode, brand_original, row.get("category"), ingredients_original]
    completeness = sum(value not in {None, ""} for value in completeness_fields) / len(
        completeness_fields
    )
    score = transparent_quality_score(
        schema_compliance=1,
        provenance=1,
        licensing=1,
        completeness=completeness,
        uniqueness=1,
        unit_validity=1,
    )
    return ProductRecord(
        product_id=f"{lineage.source_dataset.lower()}:{source_id}",
        source_product_id=source_id,
        barcode=barcode,
        barcode_valid=validate_gtin(barcode) if barcode else None,
        product_name_original=name_original,
        product_name=normalize_display_text(name_original),
        product_name_match_key=matching_key(name_original),
        brand_original=brand_original,
        brand=normalize_display_text(brand_original) if brand_original else None,
        brand_match_key=matching_key(brand_original) if brand_original else None,
        category=str(row.get("category", "")).strip() or None,
        subcategory=str(row.get("subcategory", "")).strip() or None,
        country=str(row.get("country", "")).strip() or None,
        languages=_languages(row.get("languages")),
        quantity=_optional_float(row.get("quantity")),
        quantity_unit=str(row.get("quantity_unit", "")).strip() or None,
        serving_size=_optional_float(row.get("serving_size")),
        serving_unit=str(row.get("serving_unit", "")).strip() or None,
        ingredients_original=ingredients_original,
        ingredients_normalized_text=normalize_ingredient_text(ingredients_original)
        if ingredients_original
        else None,
        nutrition_available=_boolean(row.get("nutrition_available", False)),
        ingredient_data_available=ingredients_original is not None,
        image_available=_boolean(row.get("image_available", False)),
        nova_group=row.get("nova_group"),
        source_timestamp=row.get("source_timestamp"),
        data_quality_score=score,
        record_status="VALID",
        lineage=lineage.model_copy(update={"processing_timestamp": datetime.now(UTC)}),
    )
