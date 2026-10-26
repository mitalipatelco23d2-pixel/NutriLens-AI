"""Evidence contract: facts, qualifiers, units and uncertainty; no invented ratings."""

import pytest

from ai.food_understanding.insight_composer import compose_scan_insights
from ai.food_understanding.schemas import IngredientExtraction, NutritionExtraction, NutritionRow


def text(insights):
    return " ".join(
        [
            *insights.highlights,
            *insights.positive_signals,
            *insights.things_to_watch,
            *[h.description for h in insights.structured_highlights],
        ]
    )


@pytest.mark.parametrize(
    "statement",
    [
        "Contains Milk",
        "May Contain Milk",
        "Free From Milk",
        "Contains No Milk",
        "Free from gluten; Contains Milk",
        "Free from milk; May contain peanuts",
        "Contains almonds; contains no milk",
        "Made on equipment that handles milk",
    ],
)
def test_allergen_statement_is_preserved_without_safety_rating(statement):
    result = compose_scan_insights(None, IngredientExtraction(allergen_text=statement))
    assert result.allergen_summary == f"Package allergen statement: {statement}"
    assert result.positive_signals == []
    assert all(h.category != "positive" for h in result.structured_highlights)


@pytest.mark.parametrize("value", ["unknown", "", "<0.1", "NaN", "inf", "-1", "12%", "1e309"])
def test_unknown_and_ambiguous_values_never_become_zero(value):
    result = compose_scan_insights(
        NutritionExtraction(
            basis="PER_100_G",
            table_rows=[NutritionRow(label="added sugar", values=[value], units=["g"])],
        ),
        None,
    )
    assert "Added sugar:" not in text(result)
    assert not any(h.category == "neutral" for h in result.structured_highlights)


@pytest.mark.parametrize(
    "nutrient,value,unit",
    [
        ("added sugar", "0", "g"),
        ("added sugar", "24", "g"),
        ("sodium", "0.45", "g"),
        ("sodium", "650", "mg"),
        ("protein", "3.6", "g"),
        ("energy", "200", "kj"),
        ("trans fat", "0", "g"),
        ("fibre", "4.5", "g"),
    ],
)
def test_nutrients_are_factual_and_keep_declared_units(nutrient, value, unit):
    result = compose_scan_insights(
        NutritionExtraction(
            basis="PER_100_ML",
            table_rows=[NutritionRow(label=nutrient, values=[value], units=[unit])],
        ),
        None,
    )
    assert f"{nutrient.capitalize()}: {value} {unit} per 100 ml." in text(result)
    assert not result.positive_signals
    assert not result.things_to_watch
    assert all(h.category in {"neutral", "serving"} for h in result.structured_highlights)


@pytest.mark.parametrize("units", [[], [""], ["%"], ["unknown"]])
def test_missing_or_unsupported_units_are_not_invented(units):
    result = compose_scan_insights(
        NutritionExtraction(
            basis="PER_100_G", table_rows=[NutritionRow(label="energy", values=["50"], units=units)]
        ),
        None,
    )
    assert "Energy:" not in text(result)


def test_column_order_and_percent_columns_are_respected():
    result = compose_scan_insights(
        NutritionExtraction(
            basis="PER_100_ML",
            table_columns=["per serving", "per 100 ml", "% RDA"],
            table_rows=[
                NutritionRow(label="protein", values=["9", "3.6", "18"], units=["g", "g", "%"])
            ],
        ),
        None,
    )
    assert "Protein: 3.6 g per 100 ml." in text(result)
    assert "Protein: 9" not in text(result)


@pytest.mark.parametrize(
    "basis,columns", [("UNKNOWN", []), ("PER_100_G", ["amount", "other"]), ("PER_100_G", [])]
)
def test_ambiguous_basis_or_columns_do_not_invent_association(basis, columns):
    result = compose_scan_insights(
        NutritionExtraction(
            basis=basis,
            table_columns=columns,
            table_rows=[NutritionRow(label="sodium", values=["40", "80"], units=["mg", "mg"])],
        ),
        None,
    )
    assert "Sodium:" not in text(result)


@pytest.mark.parametrize(
    "basis,unit,factor",
    [
        ("PER_100_ML", "ml", True),
        ("PER_100_G", "g", True),
        ("PER_100_G", "ml", False),
        ("PER_100_ML", "g", False),
    ],
)
def test_serving_multiplier_requires_compatible_unit(basis, unit, factor):
    result = compose_scan_insights(
        NutritionExtraction(basis=basis, serving_size_value="250", serving_size_unit=unit), None
    )
    assert ("2.5 times" in result.serving_context) is factor


@pytest.mark.parametrize("basis", ["PER_100_G", "PER_100_ML", "PER_SERVING", "UNKNOWN"])
def test_missing_serving_size_is_explicit(basis):
    result = compose_scan_insights(NutritionExtraction(basis=basis), None)
    assert (
        "not declared" in result.serving_context
        or "could not be determined" in result.serving_context
    )


def test_missing_evidence_and_ingredients_do_not_invent_claims():
    result = compose_scan_insights(None, None)
    assert result.allergen_summary is None
    assert result.serving_context is None
    assert result.highlights == ["Food label captured for reference."]
    result = compose_scan_insights(
        None, IngredientExtraction(raw_text="milk sugar non-hydrogenated oil")
    )
    assert not result.positive_signals
    assert not result.things_to_watch
    assert "Single-ingredient" not in text(result)
    assert result.allergen_summary is None


def test_partial_nutrition_has_no_claim_for_missing_nutrients():
    result = compose_scan_insights(
        NutritionExtraction(
            basis="PER_100_G", table_rows=[NutritionRow(label="protein", values=["3"], units=["g"])]
        ),
        None,
    )
    assert "Protein: 3 g" in text(result)
    assert "sodium" not in text(result).lower()
    assert "sugar" not in text(result).lower()


def test_confidence_warning_is_consumer_facing():
    result = compose_scan_insights(NutritionExtraction(confidence=0.3), None)
    assert result.things_to_watch
    assert "OCR" not in text(result)
    assert "verified" not in text(result)


def test_milk_summary_is_bounded_and_has_no_unsupported_health_rating():
    result = compose_scan_insights(
        NutritionExtraction(
            basis="PER_100_ML",
            serving_size_value="250",
            serving_size_unit="ml",
            table_rows=[
                NutritionRow(label=k, values=[v], units=[u])
                for k, v, u in [
                    ("energy", "50", "kcal"),
                    ("protein", "3.6", "g"),
                    ("added sugar", "0", "g"),
                    ("sodium", "45", "mg"),
                ]
            ],
        ),
        IngredientExtraction(raw_text="Pasteurized Cow Milk", allergen_text="CONTAINS MILK"),
    )
    assert len(result.highlights) <= 3
    assert "CONTAINS MILK" in result.allergen_summary
    assert "Protein: 3.6 g per 100 ml." in text(result)
    assert not result.positive_signals
    for word in ["healthy", "unhealthy", "safe", "high", "low", "good", "bad", "verified"]:
        assert word not in text(result).lower().split()
