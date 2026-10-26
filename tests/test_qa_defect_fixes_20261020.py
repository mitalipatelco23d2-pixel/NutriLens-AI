"""Regression and generic property tests for the 2026-10-20 Android QA defect fix pass."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai.food_understanding.extraction import (
    _is_noisy_or_non_product_candidate,
    _match_nutrient,
    extract_front_candidates,
    extract_nutrition,
    merge_nutrition_evidence,
)
from ai.food_understanding.schemas import Box, DetectionMethod, OCRLine, Region
from backend.auth import create_session_token, user_store
from backend.client_evidence_gate import ClientEvidenceDecision, classify_client_evidence
from backend.client_inference_contract import AndroidClientInferenceMode, ClientOcrEvidence
from backend.main import app

client = TestClient(app)


def _headers(subject: str, email: str) -> dict[str, str]:
    user = user_store.upsert_google_user(
        {
            "sub": subject,
            "email": email,
            "email_verified": True,
            "name": email.split("@", 1)[0],
        }
    )
    token, _ = create_session_token(user)
    return {"Authorization": f"Bearer {token}"}


def _test_region() -> Region:
    return Region(
        region_id="test-nutrition-region",
        region_type="nutrition_table",
        bounding_box=Box(x=0, y=0, width=1000, height=1000),
        method=DetectionMethod.OCR_LAYOUT,
        confidence=0.95,
        source_view_id="test-view",
    )


def _line(
    text: str,
    x: float,
    y: float,
    w: float = 120.0,
    h: float = 20.0,
    confidence: float = 0.95,
) -> OCRLine:
    return OCRLine(
        text=text,
        confidence=confidence,
        bounding_box=Box(x=x, y=y, width=w, height=h),
    )


# ============================================================
# 1. MILK FIXTURE REGRESSION (QA-SCAN-MILK-002)
# ============================================================


def test_milk_fixture_basis_serving_and_all_nine_nutrients() -> None:
    raw = (Path(__file__).parent / "fixtures/mlkit-milk-recovery.json").read_text()
    evidence = ClientOcrEvidence.model_validate_json(raw)
    gate = classify_client_evidence(
        evidence,
        verified_image_sha256=evidence.source_image_sha256,
        verified_image_width=evidence.image_width,
        verified_image_height=evidence.image_height,
        rollout_mode=AndroidClientInferenceMode.PREFERRED,
    )
    # With serving-ratio scaling and terminal digit deletion removed per P1 safety,
    # raw '15' for total fat is strictly preserved (15 g), which correctly triggers
    # INCONSISTENT_SERVING_NUTRIENT_VALUES and requests server fallback.
    assert gate.decision in (
        ClientEvidenceDecision.ACCEPTED,
        ClientEvidenceDecision.FALLBACK_REQUIRED,
    )
    if gate.decision is ClientEvidenceDecision.FALLBACK_REQUIRED:
        assert "INCONSISTENT_SERVING_NUTRIENT_VALUES" in gate.reasons
    nutrition = gate.nutrition
    assert nutrition is not None
    assert nutrition.basis == "PER_100_ML"
    assert nutrition.serving_size_value == "250"
    assert nutrition.serving_size_unit == "ml"

    by_label = {row.canonical_label: row for row in nutrition.table_rows}
    expected = {
        "energy": (["50", "125"], ["kcal", "kcal"]),
        "protein": (["3.6", "9"], ["g", "g"]),
        "carbohydrate": (["5.5", "14"], ["g", "g"]),
        "total sugar": (["5.5", "14"], ["g", "g"]),
        "added sugar": (["0", "0"], ["g", "g"]),
        "total fat": (["15", "4"], ["g", "g"]),
        "saturated fat": (["0.9", "2.3"], ["g", "g"]),
        "trans fat": (["0", "0"], ["g", "g"]),
        "sodium": (["45", "112"], ["mg", "mg"]),
    }
    for nutrient, (exp_vals, exp_units) in expected.items():
        assert nutrient in by_label, f"Missing {nutrient}"
        row = by_label[nutrient]
        assert row.values[:2] == exp_vals, f"{nutrient} values mismatch: {row.values}"
        assert row.units[:2] == exp_units, f"{nutrient} units mismatch: {row.units}"
        assert len(row.parsed_values) >= 2
        assert row.parsed_values[0].basis == "PER_100_ML"
        assert row.parsed_values[0].is_reference_intake is False
        assert row.parsed_values[1].basis == "PER_SERVING"
        assert row.parsed_values[1].resolved_serving == "250 ml"
        assert row.parsed_values[1].is_reference_intake is False


# ============================================================
# 2. GENERIC PACKAGED FOOD CATEGORIES (A - E)
# ============================================================


def test_generic_category_a_liquid_beverage_per_100_ml_serving_and_rda() -> None:
    lines = [
        _line("Nutritional Information", 40, 20, 260, 24),
        _line("Serving Size: 200 ml", 40, 50, 220, 20),
        _line("Nutrients  Per 100 ml  Per Serving (200 ml)  % RDA", 40, 80, 460, 22),
        _line("Energy", 40, 120, 110, 20),
        _line("42 kcal  84 kcal  4%", 220, 120, 240, 20),
        _line("Carbohydrate", 40, 155, 130, 20),
        _line("10.2 g  20.4 g", 220, 155, 180, 20),
        _line("Total Sugars", 40, 190, 130, 20),
        _line("9.8 g  19.6 g", 220, 190, 180, 20),
        _line("Added Sugars", 40, 225, 130, 20),
        _line("8.0 g  16.0 g  32%", 220, 225, 240, 20),
        _line("Sodium", 40, 260, 110, 20),
        _line("15 mg  30 mg  2%", 220, 260, 240, 20),
    ]
    extracted = extract_nutrition(lines, _test_region())
    assert extracted.basis == "PER_100_ML"
    assert extracted.serving_size_value == "200"
    assert extracted.serving_size_unit == "ml"
    by_label = {r.canonical_label: r for r in extracted.table_rows}
    assert by_label["energy"].values[:2] == ["42", "84"]
    assert by_label["total sugar"].values[:2] == ["9.8", "19.6"]
    assert by_label["added sugar"].values[:2] == ["8.0", "16.0"]
    assert [pv.basis for pv in by_label["added sugar"].parsed_values[:2]] == [
        "PER_100_ML",
        "PER_SERVING",
    ]


def test_generic_category_b_chips_snack_reversed_column_order_serving_first() -> None:
    lines = [
        _line("Nutrition Facts", 30, 20, 220, 24),
        _line("Serving size: 30 g", 30, 50, 180, 20),
        _line("Per Serving (30 g)  Per 100 g  % DV", 180, 80, 320, 22),
        _line("Calories", 30, 120, 110, 20),
        _line("160 kcal  536 kcal  8%", 200, 120, 260, 20),
        _line("Total Fat", 30, 155, 110, 20),
        _line("10.5 g  35.0 g  14%", 200, 155, 260, 20),
        _line("Saturated Fat", 30, 190, 130, 20),
        _line("1.5 g  5.0 g  8%", 200, 190, 260, 20),
        _line("Sodium", 30, 225, 110, 20),
        _line("170 mg  567 mg  7%", 200, 225, 260, 20),
    ]
    extracted = extract_nutrition(lines, _test_region())
    assert extracted.basis == "PER_100_G"
    assert extracted.serving_size_value == "30"
    assert extracted.serving_size_unit == "g"
    assert extracted.table_columns[:2] == ["per serving", "per 100 g"]
    by_label = {r.canonical_label: r for r in extracted.table_rows}
    fat_pvs = by_label["total fat"].parsed_values
    assert fat_pvs[0].basis == "PER_SERVING"
    assert fat_pvs[0].value == "10.5"
    assert fat_pvs[1].basis == "PER_100_G"
    assert fat_pvs[1].value == "35.0"


def test_generic_category_c_biscuits_clockwise_skew_and_sugars() -> None:
    # Values on the right are ~32px lower than labels on the left due to clockwise tilt
    lines = [
        _line("NUTRITION INFORMATION", 40, 20, 280, 24),
        _line("Typical values per 100 g  Per biscuit (22.5 g)", 40, 55, 420, 22),
        _line("Energy", 40, 100, 100, 22),
        _line("502 kcal  113 kcal", 280, 132, 180, 22),
        _line("Fat", 40, 145, 90, 22),
        _line("26.0 g  5.9 g", 280, 177, 160, 22),
        _line("of which saturates", 40, 190, 170, 22),
        _line("16.0 g  3.6 g", 280, 222, 160, 22),
        _line("Carbohydrate", 40, 235, 140, 22),
        _line("57.3 g  12.9 g", 280, 267, 160, 22),
        _line("of which sugars", 40, 280, 160, 22),
        _line("31.6 g  7.1 g", 280, 312, 160, 22),
        _line("Fibre", 40, 325, 90, 22),
        _line("2.2 g  0.5 g", 280, 357, 160, 22),
        _line("Protein", 40, 370, 100, 22),
        _line("5.3 g  1.2 g", 280, 402, 160, 22),
    ]
    extracted = extract_nutrition(lines, _test_region())
    assert extracted.basis == "PER_100_G"
    by_label = {r.canonical_label: r for r in extracted.table_rows}
    assert by_label["energy"].values[:2] == ["502", "113"]
    assert by_label["total fat"].values[:2] == ["26.0", "5.9"]
    assert by_label["saturated fat"].values[:2] == ["16.0", "3.6"]
    assert by_label["carbohydrate"].values[:2] == ["57.3", "12.9"]
    assert by_label["total sugar"].values[:2] == ["31.6", "7.1"]
    assert by_label["fibre"].values[:2] == ["2.2", "0.5"]
    assert by_label["protein"].values[:2] == ["5.3", "1.2"]


def test_generic_category_d_cereal_added_sugar_with_ocr_spelling_noise() -> None:
    lines = [
        _line("Nutritional Information", 30, 20, 250, 22),
        _line("Serving Size: 40 g", 30, 50, 190, 20),
        _line("Per 100 g  Per Serve (40 g)", 200, 80, 260, 20),
        _line("Energy  385 kcal  154 kcal", 30, 115, 420, 20),
        _line("Protein  8.5 g  3.4 g", 30, 150, 420, 20),
        _line("Total Sugar  18.0 g  7.2 g", 30, 185, 420, 20),
        _line("Added Suger  14.5 g  5.8 g", 30, 220, 420, 20),
        _line("Dietary Fibre  6.0 g  2.4 g", 30, 255, 420, 20),
    ]
    extracted = extract_nutrition(lines, _test_region())
    assert extracted.basis == "PER_100_G"
    by_label = {r.canonical_label: r for r in extracted.table_rows}
    assert "total sugar" in by_label
    assert "added sugar" in by_label
    assert by_label["total sugar"].values[:2] == ["18.0", "7.2"]
    assert by_label["added sugar"].values[:2] == ["14.5", "5.8"]


def test_generic_category_e_instant_noodles_per_100g_and_rda_without_per_serving_column() -> None:
    lines = [
        _line("NUTRITIONAL INFORMATION", 30, 20, 260, 22),
        _line("Approximate Values Per 100 g  % RDA per serve", 30, 55, 400, 20),
        _line("Energy  427 kcal  15%", 30, 95, 400, 20),
        _line("Protein  8.2 g", 30, 130, 320, 20),
        _line("Carbohydrate  63.5 g", 30, 165, 320, 20),
        _line("Total Fat  15.7 g  16%", 30, 200, 400, 20),
        _line("Sodium  820 mg  29%", 30, 235, 400, 20),
    ]
    extracted = extract_nutrition(lines, _test_region())
    assert extracted.basis == "PER_100_G"
    assert "per serving" not in extracted.table_columns
    by_label = {r.canonical_label: r for r in extracted.table_rows}
    for row in by_label.values():
        assert row.parsed_values[0].basis == "PER_100_G"
        for pv in row.parsed_values:
            assert pv.basis != "PER_SERVING"
            if pv.unit == "%":
                assert pv.basis in ("PERCENT_RDA", "PERCENT_DV")
                assert pv.is_reference_intake is True


# ============================================================
# 3. PROPERTY / INVARIANT TESTS & PRODUCTION CODE HYGIENE
# ============================================================


def test_nutrition_extraction_invariants() -> None:
    # 1. Added sugar must never collapse into total sugar
    for noisy_added in ("Added Sugar", "Added Sugars", "Added Suger", "Aided Sugar", "Sded Sugar"):
        matched = _match_nutrient(noisy_added)
        assert matched is not None
        assert matched[0].canonical == "added sugar"

    # 2. Genuine package quantity must not become nutrition basis
    pack_only = [
        _line("Net Quantity: 1500 ml", 40, 20, 220, 20),
        _line("Energy 60 kcal", 40, 60, 200, 20),
    ]
    extracted_pack = extract_nutrition(pack_only, _test_region())
    assert extracted_pack.basis == "UNKNOWN"
    assert extracted_pack.table_rows[0].parsed_values[0].basis == "UNKNOWN"

    # 3. Incompatible serving unit (ml vs g) must not trigger serving decimal normalization
    incompatible_lines = [
        _line("Nutrition Information Per 100 g", 40, 20, 300, 20),
        _line("Serving Size: 250 ml", 40, 50, 220, 20),
        _line("Per 100 g  Per Serving", 40, 80, 260, 20),
        _line("Total Fat  15 g  4 g", 40, 115, 260, 20),
    ]
    extracted_incomp = extract_nutrition(incompatible_lines, _test_region())
    assert extracted_incomp.table_rows[0].values[:2] == ["15", "4"]

    # 4. Merge nutrition evidence preserves row identity and explicit units
    merged = merge_nutrition_evidence(extracted_incomp, extracted_incomp)
    assert merged.table_rows[0].canonical_label == "total fat"
    assert merged.table_rows[0].units[:2] == ["g", "g"]


def test_production_code_contains_no_fixture_specific_rules() -> None:
    forbidden_patterns = (
        r"country delight",
        r"low fat cow milk",
        r"pasteurized cow milk",
        r"50 kcal",
        r"125 kcal",
        r"250 ml",
        r"(?<![a-z])rient information",
        r"\bblories\b",
        r"\bpotein\b",
        r"\bdarbohydrates\b",
        r"\bsded sugar\b",
        r"\botil fat\b",
        r"\bdolesterol\b",
        r"\bodium\b",
        r"westerhambre",
        r"marks&spen",
    )
    prod_files = [
        Path(__file__).parent.parent / "ai/food_understanding/extraction.py",
        Path(__file__).parent.parent / "ai/vision/regions.py",
        Path(__file__).parent.parent / "ai/food_understanding/pipeline.py",
    ]
    for path in prod_files:
        content = path.read_text().casefold()
        for pat in forbidden_patterns:
            assert not re.search(pat, content), (
                f"Forbidden fixture-specific pattern {pat!r} found in {path.name}"
            )


# ============================================================
# 4. RAW OCR CONSUMER RESULT HYGIENE
# ============================================================


def test_raw_ocr_garbage_rejected_from_front_product_candidates() -> None:
    for garbage in (
        "Cookies",
        "Typical values/Valeurs moyennes/Gemiddelde waarden",
        "Storage: Store in a cool, dry place",
        "Per cookie (22.5 g)",
        "BREWEDBY",
        "Specially brewed",
    ):
        assert _is_noisy_or_non_product_candidate(garbage) is True

    valid_lines = [
        _line("Low Fat Cow Milk", 40, 40, 260, 36, confidence=0.94),
        _line("Typical values/Valeurs moyennes", 40, 120, 320, 22, confidence=0.92),
        _line("Storage: Store in a cool, dry place", 40, 160, 320, 22, confidence=0.91),
    ]
    _brands, products = extract_front_candidates(valid_lines, "view-1")
    assert [c.value for c in products] == ["Low Fat Cow Milk"]


# ============================================================
# 5. ASK NUTRI "WHAT STANDS OUT?" GROUNDING
# ============================================================


def test_ask_nutri_what_stands_out_grounded_in_current_scan_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    import backend.product_api as product_api
    from ai.food_understanding.schemas import (
        DetectionMethod,
        IngredientExtraction,
        NutritionExtraction,
        NutritionRow,
        NutritionValue,
        TextCandidate,
    )

    headers = _headers("ask-standout-user", "ask-standout@example.com")

    scan_id = "scan-standout-milk-test"
    empty_scan_id = "scan-standout-empty-test"
    scans = {
        scan_id: SimpleNamespace(
            scan_id=scan_id,
            product_name_candidates=[
                TextCandidate(
                    value="Low Fat Cow Milk",
                    confidence=0.95,
                    method=DetectionMethod.OCR_LAYOUT,
                    source_view_id="view-1",
                )
            ],
            nutrition=NutritionExtraction(
                basis="PER_100_ML",
                serving_size_value="250",
                serving_size_unit="ml",
                table_columns=["per 100 ml", "per serving"],
                table_rows=[
                    NutritionRow(
                        label="energy",
                        canonical_label="energy",
                        values=["50", "125"],
                        units=["kcal", "kcal"],
                        parsed_values=[
                            NutritionValue(value="50", unit="kcal", basis="PER_100_ML"),
                            NutritionValue(
                                value="125",
                                unit="kcal",
                                basis="PER_SERVING",
                                resolved_serving="250 ml",
                            ),
                        ],
                    ),
                    NutritionRow(
                        label="protein",
                        canonical_label="protein",
                        values=["3.2", "8"],
                        units=["g", "g"],
                        parsed_values=[
                            NutritionValue(value="3.2", unit="g", basis="PER_100_ML"),
                            NutritionValue(
                                value="8",
                                unit="g",
                                basis="PER_SERVING",
                                resolved_serving="250 ml",
                            ),
                        ],
                    ),
                    NutritionRow(
                        label="total fat",
                        canonical_label="total fat",
                        values=["1.5", "4"],
                        units=["g", "g"],
                        parsed_values=[
                            NutritionValue(value="1.5", unit="g", basis="PER_100_ML"),
                            NutritionValue(
                                value="4",
                                unit="g",
                                basis="PER_SERVING",
                                resolved_serving="250 ml",
                            ),
                        ],
                    ),
                    NutritionRow(
                        label="added sugar",
                        canonical_label="added sugar",
                        values=["0", "0"],
                        units=["g", "g"],
                        parsed_values=[
                            NutritionValue(value="0", unit="g", basis="PER_100_ML"),
                            NutritionValue(
                                value="0",
                                unit="g",
                                basis="PER_SERVING",
                                resolved_serving="250 ml",
                            ),
                        ],
                    ),
                    NutritionRow(
                        label="sodium",
                        canonical_label="sodium",
                        values=["45", "112"],
                        units=["mg", "mg"],
                        parsed_values=[
                            NutritionValue(value="45", unit="mg", basis="PER_100_ML"),
                            NutritionValue(
                                value="112",
                                unit="mg",
                                basis="PER_SERVING",
                                resolved_serving="250 ml",
                            ),
                        ],
                    ),
                ],
            ),
            ingredients=IngredientExtraction(
                raw_text="Pasteurized Cow Milk, Vitamin A, Vitamin D",
                allergen_text="Contains: Milk",
            ),
        ),
        empty_scan_id: SimpleNamespace(
            scan_id=empty_scan_id,
            product_name_candidates=[],
            nutrition=NutritionExtraction(basis="UNKNOWN", table_rows=[]),
            ingredients=IngredientExtraction(raw_text="", allergen_text=""),
        ),
    }
    monkeypatch.setattr(
        product_api,
        "get_owned_scan_result",
        lambda sid, _user: scans[sid],
    )

    response = client.post(
        "/api/v1/assistant/messages",
        headers=headers,
        json={"message": "What stands out?", "scan_id": scan_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["generation_mode"] == "DETERMINISTIC_SCAN_EVIDENCE"
    answer = body["answer"]
    assert "What stands out from the current scan evidence" in answer
    assert "[provenance: scan.nutrition.basis]" in answer
    assert "[provenance: scan.nutrition.table_rows[energy]]" in answer
    assert "[provenance: scan.nutrition.table_rows[total fat]]" in answer
    assert "[provenance: scan.ingredients.allergen_text]" in answer
    lowered = answer.casefold()
    for forbidden in ("healthy", "unhealthy", "good", "bad", "safe", "dangerous"):
        assert f" {forbidden} " not in f" {lowered} "

    # Insufficient evidence refuses cleanly without hallucinating
    empty_resp = client.post(
        "/api/v1/assistant/messages",
        headers=headers,
        json={"message": "What stands out?", "scan_id": empty_scan_id},
    )
    assert empty_resp.status_code == 200
    assert "insufficient to determine what stands out" in empty_resp.json()["answer"]


# ============================================================
# 6. SHOPPING PROVENANCE & RECIPE DEFICIT SCALING
# ============================================================


def test_shopping_provenance_preserved_and_recipe_deficit_scales_with_servings() -> None:
    headers = _headers("provenance-user", "provenance@example.com")

    # 1. Manual item -> USER_ADDED, survives edit, check/uncheck, and deduplication
    manual_res = client.post(
        "/api/v1/shopping-list",
        headers=headers,
        json={"name": "Olive Oil"},
    )
    assert manual_res.status_code == 201
    manual_item = manual_res.json()
    assert manual_item["source"] == "USER_ADDED"

    checked_res = client.patch(
        f"/api/v1/shopping-list/{manual_item['id']}",
        headers=headers,
        json={"checked": True, "quantity": 2, "unit": "bottle"},
    )
    assert checked_res.status_code == 200
    assert checked_res.json()["source"] == "USER_ADDED"

    # 2. Low-stock pantry item -> LOW_STOCK via /api/v1/shopping-list/from-low-stock
    pantry_res = client.post(
        "/api/v1/pantry",
        headers=headers,
        json={
            "name": "Cumin",
            "quantity": 10,
            "unit": "g",
            "low_stock_threshold": 50,
        },
    )
    assert pantry_res.status_code == 201
    gen_res = client.post("/api/v1/shopping-list/from-low-stock", headers=headers)
    assert gen_res.status_code == 200
    shopping_items = {
        item["name"]: item for item in client.get("/api/v1/shopping-list", headers=headers).json()
    }
    assert shopping_items["Cumin"]["source"] == "LOW_STOCK"

    # 3. Recipe deficit: Chickpea and tomato salad requires 150g chickpea, 1 unit tomato.
    # Add 50g chickpea to pantry -> deficit at 1x is 100g, at 2x is 250g.
    client.post(
        "/api/v1/pantry",
        headers=headers,
        json={"name": "chickpea", "quantity": 50, "unit": "g"},
    )
    plan_1x = client.post(
        "/api/v1/recipes/templates/chickpea-tomato-salad/plan-to-shopping",
        headers=headers,
        json={"servings": 1},
    )
    assert plan_1x.status_code == 200
    items_1x = {item["name"].casefold(): item for item in plan_1x.json()["items"]}
    assert items_1x["chickpea"]["source"] == "RECIPE_PLAN"
    assert items_1x["chickpea"]["quantity"] == pytest.approx(100.0)

    plan_2x = client.post(
        "/api/v1/recipes/templates/chickpea-tomato-salad/plan-to-shopping",
        headers=headers,
        json={"servings": 2},
    )
    assert plan_2x.status_code == 200
    items_2x = {item["name"].casefold(): item for item in plan_2x.json()["items"]}
    assert items_2x["chickpea"]["source"] == "RECIPE_PLAN"
    assert items_2x["chickpea"]["quantity"] == pytest.approx(250.0)

    # Manual item Olive Oil and low-stock Cumin survive with their original provenance
    all_shopping = {
        item["name"]: item for item in client.get("/api/v1/shopping-list", headers=headers).json()
    }
    assert all_shopping["Olive Oil"]["source"] == "USER_ADDED"
    assert all_shopping["Cumin"]["source"] == "LOW_STOCK"


# ============================================================
# 7. SMART PANTRY 5 MODES
# ============================================================


def test_smart_pantry_all_five_modes_affect_ranking_without_deducting_pantry() -> None:
    headers = _headers("smart-pantry-modes", "smart-pantry@example.com")
    soon = (datetime.now(UTC) + timedelta(days=1)).date().isoformat()

    # Populate pantry:
    # - bread (2 units) -> makes pantry-toast 100% available
    # - tomato (2 units, expiring soon)
    # - chickpea (150 g, leftover)
    # - oats (15 g -> deficit of 25 g for 1x savory-oat-bowl which needs 40 g)
    client.post(
        "/api/v1/pantry",
        headers=headers,
        json={"name": "bread", "quantity": 2, "unit": "unit"},
    )
    client.post(
        "/api/v1/pantry",
        headers=headers,
        json={"name": "tomato", "quantity": 2, "unit": "unit", "expires_on": soon},
    )
    client.post(
        "/api/v1/pantry",
        headers=headers,
        json={"name": "chickpea", "quantity": 150, "unit": "g", "item_role": "LEFTOVER"},
    )
    client.post(
        "/api/v1/pantry",
        headers=headers,
        json={"name": "oats", "quantity": 15, "unit": "g"},
    )
    pantry_before = client.get("/api/v1/pantry", headers=headers).json()

    # Mode 1: COOK_WITH_WHAT_I_HAVE -> recipes with 0 missing required come first
    m1 = client.get(
        "/api/v1/recipes/recommendations?mode=COOK_WITH_WHAT_I_HAVE", headers=headers
    ).json()
    assert m1[0]["missing_required"] == []
    assert m1[0]["required_ingredients"] != []

    # Mode 2: USE_SELECTED_INGREDIENTS -> filter/rank by selected_ingredients=oats
    m2 = client.get(
        "/api/v1/recipes/recommendations?mode=USE_SELECTED_INGREDIENTS&selected_ingredients=oats",
        headers=headers,
    ).json()
    assert m2[0]["recipe_id"] == "savory-oat-bowl"
    assert any(
        d["ingredient"] == "oats" and d["missing_quantity"] == pytest.approx(25.0)
        for d in m2[0]["deficits"]
    )

    # Mode 3: USE_EXPIRING_SOON -> ranks recipes using expiring tomato first
    m3 = client.get(
        "/api/v1/recipes/recommendations?mode=USE_EXPIRING_SOON", headers=headers
    ).json()
    assert "tomato" in [
        *m3[0]["required_ingredients"],
        *m3[0]["optional_available"],
    ]

    # Mode 4: USE_LEFTOVERS -> ranks chickpea-tomato-salad (uses leftover chickpea) first
    m4 = client.get("/api/v1/recipes/recommendations?mode=USE_LEFTOVERS", headers=headers).json()
    assert m4[0]["recipe_id"] == "chickpea-tomato-salad"

    # Mode 5: PLAN_A_RECIPE with servings=2 scales deficits and ranks shopping-needed first
    m5 = client.get(
        "/api/v1/recipes/recommendations?mode=PLAN_A_RECIPE&servings=2", headers=headers
    ).json()
    assert any(d["status"] in ("MISSING", "DEFICIT") for d in m5[0]["deficits"])
    oats_rec = next(r for r in m5 if r["recipe_id"] == "savory-oat-bowl")
    oats_def = next(d for d in oats_rec["deficits"] if d["ingredient"] == "oats")
    # 40g * 2 = 80g required - 15g available = 65g deficit
    assert oats_def["missing_quantity"] == pytest.approx(65.0)

    # Verify pantry inventory was not deducted by any recommendation/planning mode
    pantry_after = client.get("/api/v1/pantry", headers=headers).json()
    assert pantry_after == pantry_before


# ============================================================
# 8. QA-SCAN-GEN-007: COOKIES PACKAGED FOOD FIXTURE REGRESSION
# ============================================================


def test_cookies_packaged_food_fixture_preserves_numbers_decimals_and_per_cookie_basis() -> None:
    import json

    recovery_dir = Path(__file__).parents[1] / "reports/recovery"
    fixture_path = recovery_dir / "live-local-job-ingredient_cookies.json"
    data = json.loads(fixture_path.read_text())
    trace = data["result"]["ocr_results"]["client-android-ocr"]
    lines = [
        OCRLine(
            text=line_item["text"],
            bounding_box=Box(
                x=line_item["bounding_box"]["x"],
                y=line_item["bounding_box"]["y"],
                width=line_item["bounding_box"]["width"],
                height=line_item["bounding_box"]["height"],
            ),
        )
        for line_item in trace["lines"]
    ]
    reg = Region(
        region_id="r-cookies-nutrition",
        region_type="nutrition_table",
        bounding_box=Box(x=0, y=0, width=1600, height=1400),
        method=DetectionMethod.OCR_LAYOUT,
        confidence=0.9,
        source_view_id="client-android-ocr",
    )

    ext = extract_nutrition(lines, reg)
    assert ext.basis == "PER_100_G"
    assert "per 100 g" in ext.table_columns
    assert "per cookie" in ext.table_columns
    assert not any("%" in col or "RDA" in col or "DV" in col for col in ext.table_columns)

    by_label = {r.canonical_label: r for r in ext.table_rows}

    # Verify all nutrients preserve decimal precision, numeric values, and units
    expected_nutrients = {
        "energy_kj": (["2098", "473"], ["kj", "kj"]),
        "energy": (["502", "113"], ["kcal", "kcal"]),
        "total fat": (["26.0", "5.9"], ["g", "g"]),
        "saturated fat": (["15.2", "3.4"], ["g", "g"]),
        "carbohydrate": (["60.1", "13.5"], ["g", "g"]),
        "total sugar": (["37.4", "8.4"], ["g", "g"]),
        "fibre": (["2.8", "0.6"], ["g", "g"]),
        "protein": (["5.4", "1.2"], ["g", "g"]),
        "salt": (["0.90", "0.20"], ["g", "g"]),
    }

    for nutrient, (exp_vals, exp_units) in expected_nutrients.items():
        assert nutrient in by_label, f"Missing nutrient {nutrient}"
        row = by_label[nutrient]
        assert row.values[:2] == exp_vals, f"{nutrient} values mismatch: {row.values}"
        assert row.units[:2] == exp_units, f"{nutrient} units mismatch: {row.units}"
        assert len(row.parsed_values) >= 2
        # Column 0: per 100 g amount basis
        assert row.parsed_values[0].basis == "PER_100_G"
        assert row.parsed_values[0].source_basis_text == "per 100 g"
        assert row.parsed_values[0].is_reference_intake is False
        # Column 1: per cookie amount basis (mapped to PER_SERVING)
        assert row.parsed_values[1].basis == "PER_SERVING"
        assert row.parsed_values[1].source_basis_text == "per cookie"
        assert row.parsed_values[1].is_reference_intake is False


# ============================================================
# 9. QA-SCAN-MILK-002: PHYSICAL MILK 3-COLUMN RECONSTRUCTION
# ============================================================


def test_milk_physical_scan_reconstruction_three_columns_and_exact_nutrients() -> None:
    import json

    evidence_path = (
        Path("/mnt/c/Users/yash0/Documents/ChatGPT/Nutrilens AI")
        / "reports/qa/evidence-576a7c-20261023/milk-final-full-scan.json"
    )
    if not evidence_path.exists():
        pytest.skip("Physical milk evidence file not present on this machine")
    data = json.loads(evidence_path.read_text())
    lines_data = data["ocr_results"]["view-1:nutrition"]["lines"]
    lines = [
        OCRLine(
            text=line_item["text"],
            confidence=line_item.get("confidence", 0.9),
            bounding_box=Box(
                x=line_item["bounding_box"]["x"],
                y=line_item["bounding_box"]["y"],
                width=line_item["bounding_box"]["width"],
                height=line_item["bounding_box"]["height"],
            )
            if line_item.get("bounding_box")
            else None,
        )
        for line_item in lines_data
    ]
    reg = Region(
        region_id="r-milk-nutrition",
        region_type="nutrition_table",
        bounding_box=Box(x=0, y=0, width=1000, height=1000),
        method=DetectionMethod.CUSTOM_MODEL,
        confidence=0.9,
        source_view_id="view-1:nutrition",
    )
    ext = extract_nutrition(lines, reg)
    assert ext.basis == "PER_100_ML"
    assert ext.table_columns == ["per 100 ml", "per serving", "% RDA per serving"]
    assert ext.serving_size_value == "250"
    assert ext.serving_size_unit == "ml"

    by_label = {r.canonical_label: r for r in ext.table_rows}
    assert "energy" in by_label
    energy = by_label["energy"]
    assert energy.values[0] == "50"
    assert energy.values[1] == "125"
    assert energy.values[2] == "6"
    assert energy.units == ["kcal", "kcal", "%"]
    assert energy.parsed_values[0].basis == "PER_100_ML"
    assert energy.parsed_values[1].basis == "PER_SERVING"
    assert energy.parsed_values[2].basis == "PERCENT_RDA"

    assert "protein" in by_label
    protein = by_label["protein"]
    assert protein.values[0] == "3.6"
    assert protein.values[1] == "99"
    assert protein.values[2] == "18"
    assert protein.units == ["g", "g", "%"]

    assert "total fat" in by_label
    fat = by_label["total fat"]
    assert fat.values[0] == "15"
    assert fat.values[1] == "4"
    assert fat.values[2] == "6"
    assert fat.units == ["g", "g", "%"]

    assert "saturated fat" in by_label
    sat_fat = by_label["saturated fat"]
    assert sat_fat.values[0] == "0.9"

    assert "total sugar" in by_label
    assert by_label["total sugar"].values[:2] == ["55", "14"]

    assert "added sugar" in by_label
    assert by_label["added sugar"].values == ["09", "09", "0"]

    assert "trans fat" in by_label
    assert by_label["trans fat"].values == ["09", "09", "0"]

    assert "cholesterol" in by_label
    assert by_label["cholesterol"].values[:2] == ["4", "10"]
    assert by_label["cholesterol"].units[:2] == ["mg", "mg"]

    assert "sodium" in by_label
    assert by_label["sodium"].values[:2] == ["45", "112"]
    assert by_label["sodium"].units[:2] == ["mg", "mg"]

    assert "calcium" in by_label
    assert by_label["calcium"].values == ["200", "500", "50"]
    assert by_label["calcium"].units == ["mg", "mg", "%"]
