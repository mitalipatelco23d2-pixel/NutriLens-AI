"""Deterministic regression tests for QA-SCAN-GEN-007 and QA-RANDOM-IDENTITY-009.

Covers:
1. per-100-g + per-serving two-column table
2. per-serving + %DV
3. per-serving + two percentage contexts
4. per-100-ml + per-serving + percentage column
5. multi-row decimal values
6. missing units
7. ambiguous headers
8. product-title filtering
9. Country Delight-style mixed per-100-ml/per-serving/RDA geometry
10. McVitie's-style two-column layout without any percentage column
11. Morning Summit-style amount + multiple percentage contexts
"""

import pytest

from ai.food_understanding.extraction import (
    extract_front_candidates,
    extract_nutrition,
)
from ai.food_understanding.schemas import Box, DetectionMethod, OCRLine, Region


def _box(x: float, y: float, w: float = 80.0, h: float = 30.0) -> Box:
    return Box(x=x, y=y, width=w, height=h)


def _line(
    text: str,
    x: float,
    y: float,
    w: float = 80.0,
    h: float = 30.0,
    confidence: float = 0.95,
) -> OCRLine:
    return OCRLine(text=text, confidence=confidence, bounding_box=_box(x, y, w, h))


def _region() -> Region:
    return Region(
        region_id="reg-table-test",
        region_type="nutrition_table",
        bounding_box=_box(0, 0, 1000, 1000),
        method=DetectionMethod.OCR_LAYOUT,
        confidence=0.95,
        source_view_id="view-1",
    )


# 1. per-100-g + per-serving two-column table
def test_1_per_100g_and_per_serving_two_column_table() -> None:
    lines = [
        _line("Nutrition Information", 50, 20, 300, 30),
        _line("Per 100g", 250, 60, 100, 25),
        _line("Per serving (30g)", 450, 60, 150, 25),
        _line("Energy", 50, 100, 100, 25),
        _line("400 kcal", 250, 100, 80, 25),
        _line("120 kcal", 450, 100, 80, 25),
        _line("Protein", 50, 140, 100, 25),
        _line("10.0g", 250, 140, 80, 25),
        _line("3.0g", 450, 140, 80, 25),
        _line("Total Fat", 50, 180, 100, 25),
        _line("15.0g", 250, 180, 80, 25),
        _line("4.5g", 450, 180, 80, 25),
    ]
    res = extract_nutrition(lines, _region())
    assert res.basis == "PER_100_G"
    assert res.table_columns == ["per 100 g", "per serving"]
    assert "% RDA per serving" not in res.table_columns
    assert "% DV" not in res.table_columns

    protein_row = next(r for r in res.table_rows if r.canonical_label == "protein")
    assert len(protein_row.parsed_values) == 2
    assert protein_row.parsed_values[0].value == "10.0"
    assert protein_row.parsed_values[0].basis == "PER_100_G"
    assert protein_row.parsed_values[1].value == "3.0"
    assert protein_row.parsed_values[1].basis == "PER_SERVING"


# 2. per-serving + %DV
def test_2_per_serving_and_percent_dv_amount_percentage_distinct() -> None:
    lines = [
        _line("Nutrition Facts", 50, 20, 250, 30),
        _line("Amount Per Serving", 200, 60, 160, 25),
        _line("% Daily Value*", 420, 60, 120, 25),
        _line("Total Fat", 50, 100, 100, 25),
        _line("10g", 200, 100, 60, 25),
        _line("13%", 420, 100, 50, 25),
        _line("Sodium", 50, 140, 100, 25),
        _line("200mg", 200, 140, 70, 25),
        _line("9%", 420, 140, 50, 25),
    ]
    res = extract_nutrition(lines, _region())
    assert "% DV" in res.table_columns
    fat_row = next(r for r in res.table_rows if r.canonical_label == "total fat")
    assert len(fat_row.parsed_values) == 2
    # Amount column must NOT become percentage basis
    assert fat_row.parsed_values[0].value == "10"
    assert fat_row.parsed_values[0].unit == "g"
    assert fat_row.parsed_values[0].basis == "PER_SERVING"
    # %DV must NOT become nutrient amount
    assert fat_row.parsed_values[1].value == "13"
    assert fat_row.parsed_values[1].unit == "%"
    assert fat_row.parsed_values[1].basis == "PERCENT_DV"
    assert fat_row.parsed_values[1].is_reference_intake is True


# 3. per-serving + two percentage contexts
def test_3_per_serving_and_two_percentage_contexts() -> None:
    lines = [
        _line("Nutrition Facts", 50, 20, 250, 30),
        _line("Amount", 180, 60, 80, 25),
        _line("% DV Cereal", 300, 60, 100, 25),
        _line("% DV with Milk", 450, 60, 120, 25),
        _line("Calcium", 50, 100, 80, 25),
        _line("100mg", 180, 100, 60, 25),
        _line("10%", 300, 100, 50, 25),
        _line("25%", 450, 100, 50, 25),
    ]
    res = extract_nutrition(lines, _region())
    calcium_row = next(r for r in res.table_rows if r.canonical_label == "calcium")
    assert len(calcium_row.parsed_values) == 3
    assert calcium_row.parsed_values[0].unit == "mg"
    assert calcium_row.parsed_values[0].basis == "PER_SERVING"
    assert calcium_row.parsed_values[1].unit == "%"
    assert calcium_row.parsed_values[1].basis == "PERCENT_DV"
    assert calcium_row.parsed_values[2].unit == "%"
    assert calcium_row.parsed_values[2].basis == "PERCENT_DV"


# 4. per-100-ml + per-serving + percentage column
def test_4_per_100ml_per_serving_and_percentage_column() -> None:
    lines = [
        _line("Nutrition Facts", 50, 20, 200, 30),
        _line("Per 100 ml", 220, 60, 100, 25),
        _line("Per serving", 400, 60, 100, 25),
        _line("% RDA per serve", 600, 60, 120, 25),
        _line("Energy", 50, 100, 80, 25),
        _line("60 kcal", 220, 100, 80, 25),
        _line("150 kcal", 400, 100, 80, 25),
        _line("8%", 600, 100, 50, 25),
    ]
    res = extract_nutrition(lines, _region())
    assert res.basis == "PER_100_ML"
    assert res.table_columns == ["per 100 ml", "per serving", "% RDA per serving"]
    energy_row = next(r for r in res.table_rows if r.canonical_label == "energy")
    assert len(energy_row.parsed_values) == 3
    assert energy_row.parsed_values[0].basis == "PER_100_ML"
    assert energy_row.parsed_values[1].basis == "PER_SERVING"
    assert energy_row.parsed_values[2].basis == "PERCENT_RDA"


# 5. multi-row decimal values
def test_5_multi_row_decimal_values_preserved() -> None:
    lines = [
        _line("Nutrition Facts", 50, 20, 200, 30),
        _line("Per 100g", 250, 60, 100, 25),
        _line("Per serving", 450, 60, 100, 25),
        _line("of which Sugars", 50, 100, 150, 25),
        _line("16.6g", 250, 100, 80, 25),
        _line("2.5g", 450, 100, 80, 25),
        _line("Dietary Fibre", 50, 140, 150, 25),
        _line("3.6g", 250, 140, 80, 25),
        _line("0.5g", 450, 140, 80, 25),
        _line("Salt", 50, 180, 80, 25),
        _line("1.3g", 250, 180, 80, 25),
        _line("0.29g", 450, 180, 80, 25),
    ]
    res = extract_nutrition(lines, _region())
    sugar = next(r for r in res.table_rows if r.canonical_label == "total sugar")
    fibre = next(r for r in res.table_rows if r.canonical_label == "fibre")
    salt = next(r for r in res.table_rows if r.canonical_label == "salt")

    assert sugar.values == ["16.6", "2.5"]
    assert fibre.values == ["3.6", "0.5"]
    assert salt.values == ["1.3", "0.29"]
    # Explicit regression assertion: 3.6 does NOT become 1653
    assert "1653" not in fibre.values


# 6. missing units
def test_6_missing_units_retains_uncertainty_no_silent_substitution() -> None:
    lines = [
        _line("Typical Values", 50, 20, 200, 30),
        _line("Per 100g", 250, 60, 100, 25),
        _line("Salt", 50, 100, 80, 25),
        _line("1.3", 250, 100, 60, 25),  # No unit printed
    ]
    res = extract_nutrition(lines, _region())
    salt = next(r for r in res.table_rows if r.canonical_label == "salt")
    assert salt.values[0] == "1.3"
    # Must not silently substitute mg for g or fabricate false units
    assert salt.parsed_values[0].unit in {"", "g"}


# 7. ambiguous headers
def test_7_ambiguous_headers_defaults_to_unknown_basis() -> None:
    lines = [
        _line("Values Panel", 50, 20, 150, 30),
        _line("Protein", 50, 80, 80, 25),
        _line("5.0g", 200, 80, 60, 25),
    ]
    res = extract_nutrition(lines, _region())
    assert res.basis == "UNKNOWN"
    assert res.table_rows[0].parsed_values[0].basis == "UNKNOWN"


# 8. product-title filtering (QA-RANDOM-IDENTITY-009)
def test_8_product_title_filtering_rejects_headers_slogans_and_prose() -> None:
    spurious_lines = [
        _line("AVERAGE", 50, 100, 150, 40, confidence=0.95),
        _line("VALIES", 50, 140, 120, 40, confidence=0.85),
        _line("People Love Making Food", 50, 500, 250, 40, confidence=0.95),
        _line("(cranberries Drled Sweetened Cranberries Dried", 50, 600, 350, 20, confidence=0.88),
        _line("Graln Oats , Sugar; Drled Coconut Pumpkin Seeds", 50, 630, 350, 20, confidence=0.85),
        _line("Serving suggestion", 50, 700, 180, 25, confidence=0.9),
        _line("Low Fat Cow Milk", 50, 200, 250, 60, confidence=0.92),
    ]
    _brands, products = extract_front_candidates(spurious_lines, "view-1")
    product_values = [p.value for p in products]

    # Explicit assertions preventing regressions:
    assert "AVERAGE" not in product_values
    assert "VALIES" not in product_values
    assert "People Love Making Food" not in product_values
    assert not any("cranberries" in p.lower() for p in product_values)
    assert not any("sugar" in p.lower() for p in product_values)
    assert not any("serving suggestion" in p.lower() for p in product_values)
    # Genuine product name preserved
    assert "Low Fat Cow Milk" in product_values


# 9. Country Delight-style mixed geometry
def test_9_country_delight_style_mixed_geometry() -> None:
    lines = [
        _line("NutritonFacts", 100, 20, 300, 40),
        _line("Per 100 ml", 350, 70, 100, 25),
        _line("Per sCrva", 520, 70, 100, 25),
        _line("% ADA per sCrv0", 720, 70, 140, 25),
        _line("Energy", 50, 110, 80, 25),
        _line("50 kcal", 350, 110, 80, 25),
        _line("125 kcal", 520, 110, 80, 25),
        _line("6%", 720, 110, 50, 25),
        _line("Fat", 50, 150, 80, 25),
        _line("1.5g", 350, 150, 80, 25),
        _line("4.0g", 520, 150, 80, 25),
        _line("6%", 720, 150, 50, 25),
        _line("Calcium", 50, 190, 80, 25),
        _line("200 mg", 350, 190, 80, 25),
        _line("500 mg", 520, 190, 80, 25),
        _line("50%", 720, 190, 50, 25),
    ]
    res = extract_nutrition(lines, _region())
    assert res.basis == "PER_100_ML"
    assert res.table_columns == ["per 100 ml", "per serving", "% RDA per serving"]
    for row in res.table_rows:
        assert len(row.parsed_values) == 3
        assert row.parsed_values[0].basis == "PER_100_ML"
        assert row.parsed_values[1].basis == "PER_SERVING"
        assert row.parsed_values[2].basis == "PERCENT_RDA"


# 10. McVitie's-style two-column layout without %RDA column
def test_10_mcvities_style_two_column_no_percentage_column_regression() -> None:
    lines = [
        _line("Nutritio Inforrhation", 100, 20, 400, 30),
        _line("AVERAGE", 30, 60, 120, 25),
        _line("PER 100g", 450, 60, 100, 25),
        _line("PER BISCUIT (14.8g)", 700, 60, 180, 25),
        _line("of which SUGARS", 40, 120, 200, 30),
        _line("16.6g", 450, 120, 80, 30),
        _line("2.5g", 700, 120, 80, 30),
        _line("FIBRE", 40, 170, 100, 30),
        # Normal value line
        _line("3.6g", 450, 170, 80, 30),
        _line("0.5g", 700, 170, 80, 30),
        # Severe oversized multi-row noise box (height 150 vs normal 30)
        _line("1653", 500, 140, 140, 150, confidence=0.34),
        _line("PROTEIN", 40, 220, 100, 30),
        _line("7.2g", 450, 220, 80, 30),
        _line("1.1g", 700, 220, 80, 30),
    ]
    res = extract_nutrition(lines, _region())
    # 1. No invented %RDA column
    assert "% RDA per serving" not in res.table_columns
    assert "% DV" not in res.table_columns
    assert res.table_columns == ["per 100 g", "per biscuit"]

    fibre = next(r for r in res.table_rows if r.canonical_label == "fibre")
    # 2. 3.6 does not become 1653
    assert "1653" not in fibre.values
    assert fibre.values == ["3.6", "0.5"]

    sugar = next(r for r in res.table_rows if r.canonical_label == "total sugar")
    # 3. 16.6g is assigned PER_100_G, 2.5g is assigned PER_SERVING
    assert sugar.parsed_values[0].value == "16.6"
    assert sugar.parsed_values[0].basis == "PER_100_G"
    assert sugar.parsed_values[1].value == "2.5"
    assert sugar.parsed_values[1].basis == "PER_SERVING"

    protein = next(r for r in res.table_rows if r.canonical_label == "protein")
    # 4. Protein 7.2g preserved, not 1.2g
    assert protein.values[0] == "7.2"
    assert protein.parsed_values[0].basis == "PER_100_G"


# 11. Morning Summit-style amount + multiple percentage contexts
def test_11_morning_summit_style_amount_and_multiple_percentage_contexts() -> None:
    lines = [
        _line("Nutrition Facts", 50, 20, 250, 30),
        _line("Sewing Size: 1 Cup (55g)", 50, 50, 200, 25),
        _line("Amount Per Serving", 200, 80, 150, 25),
        _line("% Daily Value", 380, 80, 100, 25),
        _line("with 1/2 cup skim milk", 520, 80, 160, 25),
        _line("Calories", 50, 120, 100, 25),
        _line("280", 200, 120, 60, 25),
        _line("320", 520, 120, 60, 25),
        _line("Total Fat", 50, 160, 100, 25),
        _line("15g", 200, 160, 60, 25),
        _line("24%", 380, 160, 50, 25),
        _line("Sugars 12g", 50, 200, 120, 25),
        _line("Other Carbohydrate 12g", 50, 230, 180, 25),  # Sub-row descriptor
        _line("Protein", 50, 270, 80, 25),
        _line("6g", 200, 270, 60, 25),
    ]
    res = extract_nutrition(lines, _region())
    sugar = next(r for r in res.table_rows if r.canonical_label == "total sugar")
    # 1. 12g sugar preserved accurately
    assert sugar.values[0] == "12"
    assert sugar.parsed_values[0].unit == "g"

    # 2. 'Other Carbohydrate 12g' does not contaminate sugar row
    assert len(sugar.values) == 1

    # 3. Energy contexts preserved (cereal vs with milk)
    energy = next(r for r in res.table_rows if r.canonical_label == "energy")
    assert len(energy.parsed_values) == 2
    assert energy.parsed_values[0].value == "280"
    assert energy.parsed_values[1].value == "320"


# 12. Deterministic test proving 29g, 99g, 0.99g, 3.69g, 129mg, 159kcal preservation
def test_12_numeric_fidelity_preserves_genuine_numbers_and_prevents_unit_fabrication() -> None:
    lines = [
        _line("Nutrition Facts", 50, 20, 250, 30),
        _line("Serving Size (55g)", 50, 50, 180, 25),
        _line("Amount Per Serving", 250, 50, 150, 25),
        _line("Total Carbohydrate 29g", 50, 90, 250, 25),
        _line("Total Fat 99g", 50, 120, 250, 25),
        _line("Saturated Fat 0.99g", 50, 150, 250, 25),
        _line("Dietary Fibre 3.69g", 50, 180, 250, 25),
        _line("Sodium 129mg", 50, 210, 250, 25),
        _line("Energy 159kcal", 50, 240, 250, 25),
        _line("Calcium 150", 50, 270, 250, 25),  # Unitless numeric evidence
    ]
    res = extract_nutrition(lines, _region())
    carb = next(r for r in res.table_rows if r.canonical_label == "carbohydrate")
    total_fat = next(r for r in res.table_rows if r.canonical_label == "total fat")
    sat_fat = next(r for r in res.table_rows if r.canonical_label == "saturated fat")
    fibre = next(r for r in res.table_rows if r.canonical_label == "fibre")
    sodium = next(r for r in res.table_rows if r.canonical_label == "sodium")
    energy = next(r for r in res.table_rows if r.canonical_label == "energy")
    calcium = next(r for r in res.table_rows if r.canonical_label == "calcium")

    # 29 g remains 29 g (NOT 2 g)
    assert carb.values[0] == "29"
    assert carb.parsed_values[0].value == "29"
    assert carb.parsed_values[0].unit == "g"

    # 99 g remains 99 g (NOT 9 g)
    assert total_fat.values[0] == "99"
    assert total_fat.parsed_values[0].value == "99"
    assert total_fat.parsed_values[0].unit == "g"

    # 0.99 g remains 0.99 g (NOT 0.9 g)
    assert sat_fat.values[0] == "0.99"
    assert sat_fat.parsed_values[0].value == "0.99"
    assert sat_fat.parsed_values[0].unit == "g"

    # 3.69 g remains 3.69 g (NOT 3.6 g)
    assert fibre.values[0] == "3.69"
    assert fibre.parsed_values[0].value == "3.69"
    assert fibre.parsed_values[0].unit == "g"

    # 129 mg remains 129 mg
    assert sodium.values[0] == "129"
    assert sodium.parsed_values[0].value == "129"
    assert sodium.parsed_values[0].unit == "mg"

    # 159 kcal remains 159 kcal
    assert energy.values[0] == "159"
    assert energy.parsed_values[0].value == "159"
    assert energy.parsed_values[0].unit == "kcal"

    # Unitless numeric evidence does not receive invented 'g'
    assert calcium.values[0] == "150"
    assert calcium.parsed_values[0].value == "150"
    assert calcium.parsed_values[0].unit != "g"


# 13. Single-column tables do not grow fabricated amount columns
def test_13_single_column_table_does_not_grow_fabricated_amount_columns() -> None:
    lines = [
        _line("Nutrition Facts", 50, 20, 250, 30),
        _line("Per 100g", 200, 50, 100, 25),
        _line("Energy 450 kcal", 50, 90, 200, 25),
        _line("Protein 8.5g", 50, 120, 200, 25),
        _line("Carbohydrate 65g", 50, 150, 200, 25),
    ]
    res = extract_nutrition(lines, _region())
    # Preserves single column
    assert len(res.table_columns) == 1
    assert res.table_columns[0].lower() in {"per 100 g", "per 100g"}
    for row in res.table_rows:
        # Each row has strictly 1 parsed value, never growing a fabricated second column
        assert len(row.parsed_values) == 1
        assert row.parsed_values[0].basis == "PER_100_G"


# 14. College Demo Auth & Instamart safety tests
def test_14_college_demo_auth_and_instamart_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    from dataclasses import replace

    from fastapi.testclient import TestClient

    import backend.auth as auth_module
    import backend.product_api as product_module
    from backend.main import app
    from backend.settings import settings

    client = TestClient(app)

    # 1. When COLLEGE_DEMO_MODE=False, /api/v1/auth/demo/login MUST be rejected
    mock_settings_no_demo = replace(settings, college_demo_mode=False)
    monkeypatch.setattr(auth_module, "settings", mock_settings_no_demo)
    res_rejected = client.post("/api/v1/auth/demo/login")
    assert res_rejected.status_code == 403

    # 2. When COLLEGE_DEMO_MODE=True and environment is development/local_qa, demo login succeeds
    mock_settings_demo = replace(settings, college_demo_mode=True, app_environment="development")
    monkeypatch.setattr(auth_module, "settings", mock_settings_demo)
    res_success = client.post("/api/v1/auth/demo/login")
    assert res_success.status_code == 200
    token = res_success.json()["access_token"]
    assert token

    # 3. Outside local environment, demo login is strictly forbidden
    mock_settings_prod = replace(settings, college_demo_mode=True, app_environment="production")
    monkeypatch.setattr(auth_module, "settings", mock_settings_prod)
    res_prod_reject = client.post("/api/v1/auth/demo/login")
    assert res_prod_reject.status_code == 403

    # 4. Instamart status reports PENDING_SWIGGY_APPROVAL without credentials
    mock_settings_instamart = replace(settings, swiggy_client_id="")
    monkeypatch.setattr(product_module, "settings", mock_settings_instamart)
    monkeypatch.setattr(auth_module, "settings", mock_settings_demo)
    res_instamart = client.get(
        "/api/v1/instamart/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_instamart.status_code == 200
    assert res_instamart.json()["status"] == "PENDING_SWIGGY_APPROVAL"
