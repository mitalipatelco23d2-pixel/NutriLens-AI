from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from scripts.data_engineering.annotations import to_coco, to_yolo_line
from scripts.data_engineering.normalization import (
    convert_unit,
    derive_salt_from_sodium,
    derive_sodium_from_salt,
    matching_key,
    normalize_ingredient_text,
    normalize_language_code,
    normalize_reported_value,
    standardize_language_code,
    validate_gtin,
    validate_unicode_text,
)
from scripts.data_engineering.products import normalize_product
from scripts.data_engineering.quality import (
    classify_duplicates,
    nutrition_outlier_flags,
    transparent_quality_score,
)
from scripts.data_engineering.schemas import (
    BoundingBox,
    DetectionAnnotation,
    Lineage,
    MissingReason,
    NutrientValue,
    PopulationRecord,
)
from scripts.data_engineering.splits import (
    generate_splits,
    validate_no_group_leakage,
)


def lineage() -> Lineage:
    return Lineage(
        source_dataset="SYNTHETIC_SOFTWARE_TEST_FIXTURE",
        source_record_id="fixture-1",
        source_version="1",
        source_url="https://example.invalid/test-only",
        input_checksum="0" * 64,
        processing_timestamp=datetime.now(UTC),
        license_status="TEST_ONLY",
    )


@pytest.mark.parametrize(
    ("value", "source", "target", "expected"),
    [
        (1000, "mg", "g", 1),
        (1, "G", "mg", 1000),
        (1, "kg", "g", 1000),
        (1000, "mcg", "mg", 1),
        (1, "kcal", "kJ", 4.184),
        (1000, "mL", "L", 1),
    ],
)
def test_deterministic_unit_conversion(
    value: float, source: str, target: str, expected: float
) -> None:
    assert convert_unit(value, source, target) == pytest.approx(expected)


def test_incompatible_unit_conversion_is_rejected() -> None:
    with pytest.raises(ValueError, match="incompatible"):
        convert_unit(1, "serving", "g")


def test_reported_sodium_and_derived_salt_remain_distinct() -> None:
    sodium = normalize_reported_value(400, "mg", "mg", source_nutrient_id="1093")
    salt = derive_salt_from_sodium(sodium)
    assert sodium.value_origin == "REPORTED"
    assert salt.value_origin == "DERIVED"
    assert salt.normalized_value == pytest.approx(1.0)
    assert derive_sodium_from_salt(salt).normalized_value == pytest.approx(400)


def test_missing_value_is_not_zero() -> None:
    missing = NutrientValue(missing_reason=MissingReason.NOT_REPORTED)
    assert missing.normalized_value is None
    with pytest.raises(ValidationError):
        NutrientValue(normalized_value=None)


def test_negative_nutrient_value_is_invalid() -> None:
    with pytest.raises(ValueError, match="negative"):
        normalize_reported_value(-1, "g", "g")


def test_conservative_text_and_ingredient_normalization() -> None:
    assert matching_key("  Brand™   Name ") == "brandtm name"
    assert normalize_ingredient_text("Sugar ; E- 330 ; INS-621 [spice] 2 %") == (
        "Sugar, E330, INS 621 (spice) 2%"
    )


def test_multilingual_unicode_and_language_codes_are_preserved() -> None:
    text = "पोषण தமிழ் পুষ্টি"
    assert validate_unicode_text(text)
    assert normalize_language_code("HI-in") == "hi-in"
    assert standardize_language_code("fr_CA") == "fr-ca"
    with pytest.raises(ValueError, match="unsupported"):
        normalize_language_code("xx")


def test_barcode_validation_preserves_leading_zeroes() -> None:
    assert validate_gtin("01234565")
    assert not validate_gtin(str(int("01234565")))


def test_product_normalization_preserves_original_fields() -> None:
    record = normalize_product(
        {
            "source_product_id": "A1",
            "product_name": "  TEST™   RECORD  ",
            "brand": "A&B",
            "barcode": "01234565",
            "ingredients": "A ; E-330",
            "languages": "en;hi-IN",
            "quantity": "250",
            "quantity_unit": "g",
            "serving_size": "25",
            "serving_unit": "g",
            "nutrition_available": "false",
            "image_available": "yes",
        },
        lineage(),
    )
    assert record.product_name_original == "TEST™   RECORD"
    assert record.product_name == "TESTTM RECORD"
    assert record.barcode == "01234565"
    assert record.ingredients_normalized_text == "A, E330"
    assert record.languages == ["en", "hi-in"]
    assert record.quantity == 250 and record.serving_size == 25
    assert record.nutrition_available is False and record.image_available is True


def test_duplicates_are_flagged_not_merged() -> None:
    rows = [
        {"id": "1", "name": "same"},
        {"id": "2", "name": "same"},
        {"id": "2", "name": "variant"},
    ]
    findings = classify_duplicates(rows, id_field="id", exact_key_fields=("name",))
    assert [finding.classification for finding in findings] == [
        "NOT_DUPLICATE",
        "LIKELY_DUPLICATE",
        "EXACT_DUPLICATE",
    ]


def test_quality_formula_is_transparent_and_bounded() -> None:
    assert (
        transparent_quality_score(
            schema_compliance=1,
            provenance=1,
            licensing=1,
            completeness=0.5,
            uniqueness=1,
            unit_validity=1,
        )
        == 90
    )
    with pytest.raises(ValueError):
        transparent_quality_score(
            schema_compliance=2,
            provenance=1,
            licensing=1,
            completeness=1,
            uniqueness=1,
            unit_validity=1,
        )


def test_outliers_are_flagged_not_deleted() -> None:
    flags = nutrition_outlier_flags(
        {"sodium_mg": {"normalized_value": 6000}, "energy_kcal": {"normalized_value": 950}}
    )
    assert len(flags) == 2
    assert all(flag.startswith("SUSPECT_OUTLIER") for flag in flags)


def test_splits_are_deterministic_and_group_safe() -> None:
    source = [("a", "family"), ("b", "family"), ("c", "other")]
    first = generate_splits(source)
    second = generate_splits(reversed(source))
    assert first == second
    assert validate_no_group_leakage(first) == []


def test_annotation_yolo_and_coco_conversion() -> None:
    annotation = DetectionAnnotation(
        annotation_id="a1",
        image_id="i1",
        label="nutrition_table",
        bounding_box=BoundingBox(x=10, y=20, width=30, height=40),
        annotation_source="HUMAN",
        review_status="REVIEWED",
    )
    assert to_yolo_line(annotation, class_index=1, image_width=100, image_height=100) == (
        "1 0.250000 0.400000 0.300000 0.400000"
    )
    coco = to_coco([annotation], [{"id": "i1", "width": 100, "height": 100}], ["nutrition_table"])
    assert coco["annotations"][0]["area"] == 1200


def test_population_missingness_is_explicit() -> None:
    with pytest.raises(ValidationError):
        PopulationRecord(
            record_id="x",
            country="IN",
            year=2020,
            indicator="fixture",
            value=None,
            unit="count",
            quality_flag="TEST",
            lineage=lineage(),
        )
