"""Generalized nutrition evidence-preservation contract and anti-overfitting tests.

This test suite proves that the nutrition parser, consistency detector, and evidence
gate are strictly product-agnostic and not overfitted to any single product or fixture.

Generic Nutrition Evidence Contract:
1. Preserve observed numeric OCR evidence exactly as captured.
2. Never invent decimal points (e.g. 15 -> 1.5, 80 -> 8.0).
3. Never silently add or delete digits (e.g. 150 -> 15).
4. Never force arithmetic consistency by modifying source evidence.
5. Invariant: observed_numeric_evidence_before == observed_numeric_evidence_after.
6. Unknown != Zero. Missing values remain missing.
7. Governed fallback is required when observed values contradict.
"""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from ai.food_understanding.insight_composer import compose_scan_insights
from ai.food_understanding.nutrition_consistency import _interval, inconsistent_serving_rows
from ai.food_understanding.schemas import NutritionExtraction, NutritionRow
from backend.client_evidence_gate import _has_ambiguous_value_columns, _has_implausible_value


def _build_label(
    *,
    basis_amount: str,
    serving_amount: str,
    nutrient_label: str = "protein",
    unit: str = "g",
    serving_size: str = "30",
    size_unit: str = "g",
    basis: str = "PER_100_G",
) -> NutritionExtraction:
    col_basis = "per 100 g" if size_unit == "g" else "per 100 ml"
    return NutritionExtraction(
        basis=basis,  # type: ignore[arg-type]
        table_columns=[col_basis, "per serving"],
        serving_size_value=serving_size,
        serving_size_unit=size_unit,
        table_rows=[
            NutritionRow(
                label=nutrient_label,
                canonical_label=nutrient_label,
                values=[basis_amount, serving_amount],
                units=[unit, unit],
            )
        ],
    )


# ==============================================================================
# 1. CONSISTENT EVIDENCE ACROSS PRODUCT CATEGORIES & NUTRIENTS
# ==============================================================================


@pytest.mark.parametrize(
    "product_category,nutrient,per_100,serving_size,serving_unit,per_serving,unit",
    [
        # Beverages (ml)
        ("beverages", "energy", "45", "200", "ml", "90", "kcal"),
        ("beverages", "total sugar", "10.5", "200", "ml", "21.0", "g"),
        ("beverages", "vitamin c", "12", "250", "ml", "30", "mg"),
        ("beverages", "sodium", "15", "330", "ml", "50", "mg"),
        # Dairy (g / ml)
        ("dairy", "protein", "10", "150", "g", "15", "g"),
        ("dairy", "total fat", "4.0", "150", "g", "6.0", "g"),
        ("dairy", "saturated fat", "22", "30", "g", "6.6", "g"),
        ("dairy", "calcium", "120", "200", "ml", "240", "mg"),
        # Cereal (g)
        ("cereal", "carbohydrates", "68", "40", "g", "27.2", "g"),
        ("cereal", "dietary fibre", "10.0", "40", "g", "4.0", "g"),
        ("cereal", "iron", "7.0", "30", "g", "2.1", "g"),
        ("cereal", "added sugar", "8.0", "45", "g", "3.6", "g"),
        # Snacks (g)
        ("snacks", "total fat", "32", "28", "g", "9.0", "g"),
        ("snacks", "sodium", "600", "28", "g", "168", "mg"),
        ("snacks", "trans fat", "0.1", "30", "g", "0.0", "g"),
        ("snacks", "potassium", "450", "25", "g", "112", "mg"),
        # Biscuits (g)
        ("biscuits", "carbohydrates", "70", "15", "g", "10.5", "g"),
        ("biscuits", "total sugar", "24", "20", "g", "4.8", "g"),
        ("biscuits", "saturated fat", "12", "16", "g", "1.9", "g"),
        ("biscuits", "energy", "480", "15", "g", "72", "kcal"),
        # Sauces (g / ml)
        ("sauces", "total sugar", "22", "15", "g", "3.3", "g"),
        ("sauces", "total fat", "75", "14", "g", "10.5", "g"),
        ("sauces", "sodium", "950", "15", "ml", "142", "mg"),
        ("sauces", "salt", "2.4", "15", "g", "0.36", "g"),
        # Packaged Meals (g)
        ("packaged meals", "energy", "150", "350", "g", "525", "kcal"),
        ("packaged meals", "protein", "8.5", "350", "g", "29.8", "g"),
        ("packaged meals", "carbohydrates", "24", "300", "g", "72", "g"),
        ("packaged meals", "sodium", "420", "300", "g", "1260", "mg"),
        # Protein Products (g)
        ("protein products", "protein", "80", "32", "g", "25.6", "g"),
        ("protein products", "cholesterol", "45", "32", "g", "14.4", "mg"),
        ("protein products", "added sugar", "1.5", "60", "g", "0.9", "g"),
        ("protein products", "energy", "380", "60", "g", "228", "kcal"),
    ],
)
def test_consistent_evidence_accepted_without_mutation(
    product_category: str,
    nutrient: str,
    per_100: str,
    serving_size: str,
    serving_unit: str,
    per_serving: str,
    unit: str,
) -> None:
    """Mutually consistent evidence must be accepted without altering any numeric token."""
    label = _build_label(
        basis_amount=per_100,
        serving_amount=per_serving,
        nutrient_label=nutrient,
        unit=unit,
        serving_size=serving_size,
        size_unit=serving_unit,
        basis="PER_100_G" if serving_unit == "g" else "PER_100_ML",
    )
    conflicts = inconsistent_serving_rows(label)
    assert conflicts == set(), (
        f"Unexpected conflict for {product_category} {nutrient}: "
        f"{per_100}{unit} per 100 vs {per_serving}{unit} per {serving_size}{serving_unit}"
    )

    # Invariant: source values MUST NOT be mutated
    assert label.table_rows[0].values == [per_100, per_serving]


# ==============================================================================
# 2. CONTRADICTORY EVIDENCE ACROSS PRODUCT CATEGORIES & NUTRIENTS
# ==============================================================================


@pytest.mark.parametrize(
    "product_category,nutrient,per_100,serving_size,serving_unit,per_serving,unit",
    [
        # Beverages: per 100ml says 45 kcal, but 200ml serving says 500 kcal
        ("beverages", "energy", "45", "200", "ml", "500", "kcal"),
        # Dairy: per 100g says 10g protein, but 150g serving says 2g
        ("dairy", "protein", "10", "150", "g", "2", "g"),
        # Cereal: per 100g says 68g carbs, but 40g serving says 85g
        ("cereal", "carbohydrates", "68", "40", "g", "85", "g"),
        # Snacks: per 100g says 32g fat, but 28g serving says 45g
        ("snacks", "total fat", "32", "28", "g", "45", "g"),
        # Biscuits: per 100g says 24g sugar, but 20g serving says 1g
        ("biscuits", "total sugar", "24", "20", "g", "1", "g"),
        # Sauces: per 100g says 75g fat, but 14g serving says 25g
        ("sauces", "total fat", "75", "14", "g", "25", "g"),
        # Packaged meals: per 100g says 420mg sodium, but 300g serving says 40mg
        ("packaged meals", "sodium", "420", "300", "g", "40", "mg"),
        # Protein products: per 100g says 80g protein, but 32g serving says 5g
        ("protein products", "protein", "80", "32", "g", "5", "g"),
    ],
)
def test_contradictory_evidence_flagged_without_mutation(
    product_category: str,
    nutrient: str,
    per_100: str,
    serving_size: str,
    serving_unit: str,
    per_serving: str,
    unit: str,
) -> None:
    """Contradictory evidence must be detected and flagged; numbers must remain unchanged."""
    label = _build_label(
        basis_amount=per_100,
        serving_amount=per_serving,
        nutrient_label=nutrient,
        unit=unit,
        serving_size=serving_size,
        size_unit=serving_unit,
        basis="PER_100_G" if serving_unit == "g" else "PER_100_ML",
    )
    conflicts = inconsistent_serving_rows(label)
    assert conflicts == {0}, (
        f"Contradiction missed for {product_category} {nutrient}: "
        f"{per_100} per 100 vs {per_serving} per {serving_size}{serving_unit}"
    )

    # Invariant: source values MUST NOT be mutated to force agreement
    assert label.table_rows[0].values == [per_100, per_serving]

    # Consumer insight check: contradictory row must be excluded from highlights
    insights = compose_scan_insights(label, None)
    assert not any(f"{per_100} {unit}" in h.description for h in insights.structured_highlights)
    assert any("conflict" in w.lower() for w in insights.things_to_watch)


# ==============================================================================
# 3. SUSPICIOUS DECIMAL PREVENTION (NEVER INVENT DECIMAL POINTS)
# ==============================================================================


@pytest.mark.parametrize(
    "product_category,nutrient,raw_per_100,serving_size,raw_serving,plausible_decimal",
    [
        # Milk regression: 15g fat with 250ml serving claiming 4g (plausible: 1.5g)
        ("dairy", "total fat", "15", "250", "4", "1.5"),
        # Juice: 80g sugar with 200ml serving claiming 16g (plausible: 8.0g)
        ("beverages", "total sugar", "80", "200", "16", "8.0"),
        # Cereal: 25g fibre with 40g serving claiming 1.0g (plausible: 2.5g)
        ("cereal", "dietary fibre", "25", "40", "1.0", "2.5"),
        # Snack: 120g carbs with 30g serving claiming 3.6g (plausible: 12.0g)
        ("snacks", "carbohydrates", "120", "30", "3.6", "12.0"),
        # Sauce: 35g salt with 15g serving claiming 0.5g (plausible: 3.5g)
        ("sauces", "salt", "35", "15", "0.5", "3.5"),
        # Protein bar: 200g protein with 50g serving claiming 10g (plausible: 20.0g)
        ("protein products", "protein", "200", "50", "10", "20.0"),
    ],
)
def test_suspicious_decimal_is_not_invented(
    product_category: str,
    nutrient: str,
    raw_per_100: str,
    serving_size: str,
    raw_serving: str,
    plausible_decimal: str,
) -> None:
    """The pipeline must never insert a decimal point to 'repair' inconsistent OCR."""
    label = _build_label(
        basis_amount=raw_per_100,
        serving_amount=raw_serving,
        nutrient_label=nutrient,
        unit="g",
        serving_size=serving_size,
        size_unit="g",
    )
    # The contradiction must be flagged
    conflicts = inconsistent_serving_rows(label)
    assert 0 in conflicts, f"Expected conflict for {product_category} {nutrient}"

    # The raw observed values MUST NOT be rewritten to the plausible decimal
    assert label.table_rows[0].values[0] == raw_per_100
    assert label.table_rows[0].values[0] != plausible_decimal


# ==============================================================================
# 4. SUSPICIOUS ZERO / DIGIT MUTATION PREVENTION
# ==============================================================================


@pytest.mark.parametrize(
    "product_category,nutrient,raw_per_100,serving_size,raw_serving,plausible_trimmed",
    [
        # Deleting trailing zero: 150g with 50g serving claiming 7.5g (plausible: 15g)
        ("protein products", "protein", "150", "50", "7.5", "15"),
        # Deleting zero: 300g carbs with 30g serving claiming 9g (plausible: 30g)
        ("cereal", "carbohydrates", "300", "30", "9", "30"),
        # Adding zero: 5g fat with 50g serving claiming 25g (plausible: 50g)
        ("snacks", "total fat", "5", "50", "25", "50"),
        # Deleting leading 1: 18g sodium with 100g serving claiming 8g (plausible: 8g)
        ("sauces", "sodium", "18", "100", "8", "8"),
    ],
)
def test_suspicious_zero_or_digit_is_not_mutated(
    product_category: str,
    nutrient: str,
    raw_per_100: str,
    serving_size: str,
    raw_serving: str,
    plausible_trimmed: str,
) -> None:
    """The pipeline must never add or remove digits to force arithmetic consistency."""
    label = _build_label(
        basis_amount=raw_per_100,
        serving_amount=raw_serving,
        nutrient_label=nutrient,
        unit="g",
        serving_size=serving_size,
        size_unit="g",
    )
    # Must flag contradiction or implausibility without mutating
    conflicts = inconsistent_serving_rows(label)
    implausible = _has_implausible_value(label)
    assert 0 in conflicts or implausible

    # Source value MUST remain intact
    assert label.table_rows[0].values[0] == raw_per_100
    assert label.table_rows[0].values[0] != plausible_trimmed


# ==============================================================================
# 5. UNIT MISMATCH HANDLING
# ==============================================================================


def test_unlike_units_not_falsely_flagged_without_conversion() -> None:
    """Columns with differing units (e.g. g vs mg, or kJ vs kcal) must not be compared

    as identical units nor destructively rewritten.
    """
    # Unit mismatch: basis has "g", serving has "mg"
    label = _build_label(
        basis_amount="1",
        serving_amount="500",
        nutrient_label="sodium",
        unit="g",
        serving_size="50",
    )
    label.table_rows[0].units = ["g", "mg"]
    # inconsistent_serving_rows safely ignores rows with differing units
    assert inconsistent_serving_rows(label) == set()
    assert label.table_rows[0].values == ["1", "500"]
    assert label.table_rows[0].units == ["g", "mg"]

    # Dimension mismatch: basis is per 100 ml, but serving size is given in g
    label_dim_mismatch = _build_label(
        basis_amount="10",
        serving_amount="5",
        nutrient_label="protein",
        serving_size="50",
        size_unit="g",  # Serving is g, but basis is per 100 ml
        basis="PER_100_ML",
    )
    label_dim_mismatch.table_columns = ["per 100 ml", "per serving"]
    assert inconsistent_serving_rows(label_dim_mismatch) == set()


# ==============================================================================
# 6. MISSING VALUE HANDLING (UNKNOWN != ZERO)
# ==============================================================================


@pytest.mark.parametrize(
    "missing_token",
    ["", "-", "—", "N/A", "NaN", "nil", "unknown", "missing"],
)
def test_missing_values_preserved_as_unknown_not_zero(missing_token: str) -> None:
    """Missing or non-numeric tokens must return None from interval extraction

    and must NOT be promoted to 0.0 or inferred from other rows.
    """
    assert _interval(missing_token) is None, f"Expected None for missing token: {missing_token!r}"

    label = _build_label(
        basis_amount=missing_token,
        serving_amount="5",
        nutrient_label="protein",
        serving_size="30",
    )
    # Does not crash or treat as zero (which would falsely flag conflict with 5g)
    assert inconsistent_serving_rows(label) == set()
    assert label.table_rows[0].values[0] == missing_token


# ==============================================================================
# 7. OCR NOISE HANDLING & AMBIGUOUS COLUMNS
# ==============================================================================


def test_ocr_noise_and_stray_columns_rejected_as_ambiguous() -> None:
    """Excess columns or non-numeric noise must be marked as ambiguous or ignored."""
    label = _build_label(
        basis_amount="10",
        serving_amount="3",
        nutrient_label="protein",
        serving_size="30",
    )
    # Inject stray unlabelled column
    label.table_rows[0].values.append("99*")
    label.table_rows[0].units.append("g")

    assert _has_ambiguous_value_columns(label) is True
    # Raw values remain preserved
    assert label.table_rows[0].values == ["10", "3", "99*"]


# ==============================================================================
# 8. PROPERTY-BASED RANDOMIZED SAFETY INVARIANT (ANTI-OVERFITTING)
# ==============================================================================


def test_randomized_triples_preserve_observed_numeric_evidence() -> None:
    """Generate 100+ random (per-100, serving_size, per_serving) triples.

    Verify the strict invariant:
    observed_numeric_evidence_before == observed_numeric_evidence_after
    under all consistent and contradictory conditions across diverse nutrients and units.
    """
    rng = random.Random(1337)
    nutrients = [
        ("protein", "g"),
        ("total fat", "g"),
        ("saturated fat", "g"),
        ("carbohydrates", "g"),
        ("total sugar", "g"),
        ("dietary fibre", "g"),
        ("sodium", "mg"),
        ("energy", "kcal"),
        ("calcium", "mg"),
        ("iron", "mg"),
    ]
    serving_sizes = ["15", "25", "30", "45", "60", "120", "150", "200", "250", "330"]

    for trial in range(120):
        nutrient, unit = rng.choice(nutrients)
        serving_size = rng.choice(serving_sizes)
        size_unit = "ml" if rng.random() > 0.5 else "g"

        # Generate basis value (e.g. 0.5 to 80.0)
        basis_num = round(rng.uniform(0.5, 80.0), 1)
        basis_str = str(basis_num)

        # Decide whether to make it mathematically consistent or deliberately contradictory
        is_consistent = rng.random() > 0.4
        multiplier = Decimal(serving_size) / 100
        expected_serving = Decimal(str(basis_num)) * multiplier

        if is_consistent:
            # Round to 1 decimal place or integer
            serving_str = str(round(float(expected_serving), 1))
        else:
            # Deliberately contradict: add 5x or subtract 90%
            skew = Decimal("5.0") if rng.random() > 0.5 else Decimal("0.1")
            contradicting_val = max(Decimal("0.1"), expected_serving * skew)
            serving_str = str(round(float(contradicting_val), 1))

        label = _build_label(
            basis_amount=basis_str,
            serving_amount=serving_str,
            nutrient_label=nutrient,
            unit=unit,
            serving_size=serving_size,
            size_unit=size_unit,
            basis="PER_100_G" if size_unit == "g" else "PER_100_ML",
        )

        before_values = list(label.table_rows[0].values)
        before_units = list(label.table_rows[0].units)

        # Run consistency detection and insight generation
        conflicts = inconsistent_serving_rows(label)
        insights = compose_scan_insights(label, None)

        # CORE SAFETY INVARIANT: Evidence MUST NOT be mutated
        assert label.table_rows[0].values == before_values, (
            f"Trial {trial}: Values mutated from {before_values} to {label.table_rows[0].values}!"
        )
        assert label.table_rows[0].units == before_units, (
            f"Trial {trial}: Units mutated from {before_units} to {label.table_rows[0].units}!"
        )

        # If contradictory, the conflicting row must not appear as a positive highlight
        if conflicts:
            assert not any(
                f"{basis_str} {unit}" in h.description for h in insights.structured_highlights
            )
