"""Owner-scoped package answers must not invent values, safety, or citations."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai.food_understanding.schemas import (
    ConfidenceLevel,
    ConfidenceSummary,
    DetectionMethod,
    IngredientExtraction,
    InputKind,
    NutritionExtraction,
    NutritionRow,
    R3ScanResult,
    TextCandidate,
    Timing,
)
from ai.food_understanding.store import EphemeralScanStore
from backend import product_api, r3_api
from backend.auth import User, current_user


@pytest.fixture
def owner() -> User:
    return User("scan-owner", None, "owner@example.test", "Owner", None)


@pytest.fixture
def scan() -> R3ScanResult:
    return R3ScanResult(
        scan_id="owned-scan",
        trace_id="scan-context-test",
        status="COMPLETED",
        input_kind=InputKind.PRODUCT,
        input_metadata=[],
        image_quality={},
        preprocessing={},
        nutrition=NutritionExtraction(
            basis="PER_100_ML",
            table_columns=["per 100 ml", "per serving", "% RDA per serving"],
            table_rows=[
                NutritionRow(label="protein", values=["3.6", "9", "18"], units=["g", "g", "%"]),
                NutritionRow(label="calcium", values=["200", "500"], units=["mg", "mg"]),
            ],
            serving_size_value="250",
            serving_size_unit="ml",
        ),
        ingredients=IngredientExtraction(
            raw_text="Pasteurized milk", allergen_text="CONTAINS MILK"
        ),
        product_name_candidates=[
            TextCandidate(
                value="Example label",
                confidence=0.9,
                method=DetectionMethod.OCR_LAYOUT,
                source_view_id="front",
            ),
        ],
        confidence_summary=ConfidenceSummary(level=ConfidenceLevel.MEDIUM),
        timings=Timing(
            validation_ms=0,
            quality_ms=0,
            preprocessing_ms=0,
            detection_ms=0,
            barcode_qr_ms=0,
            ocr_ms=0,
            extraction_ms=0,
            total_ms=0,
        ),
    )


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch, scan: R3ScanResult, owner: User) -> Iterator[TestClient]:
    store = EphemeralScanStore()
    store.save(scan, owner_id=owner.id)
    monkeypatch.setattr(r3_api, "postgres_store", None)
    monkeypatch.setattr(r3_api, "scan_store", store)
    monkeypatch.setattr(product_api, "postgres_store", None)
    monkeypatch.setattr(product_api, "product_store", product_api.ProductStore())
    app = FastAPI()
    app.include_router(product_api.router)
    app.dependency_overrides[current_user] = lambda: owner
    with TestClient(app) as client:
        yield client


def test_scan_summary_quotes_structured_evidence(api: TestClient) -> None:
    response = api.post(
        "/api/v1/assistant/messages", json={"scan_id": "owned-scan", "message": "Explain this scan"}
    )
    assert response.status_code == 200
    payload = response.json()
    assert "Example label" in payload["answer"]
    assert "Pasteurized milk" in payload["answer"]
    assert "CONTAINS MILK" in payload["answer"]
    assert "Protein: 3.6 g (per 100 ml)" in payload["answer"]
    assert "Protein: 9 g (per serving)" in payload["answer"]
    assert "Calcium: 200 mg (per 100 ml)" in payload["answer"]
    assert "Package serving size / OCR: 250 ml" in payload["answer"]
    assert "18" not in payload["answer"]  # RDA is not a nutrient amount.
    assert payload["generation_mode"] == "DETERMINISTIC_SCAN_EVIDENCE"
    assert payload["citations"] == []


@pytest.mark.parametrize(
    "statement", ["CONTAINS MILK", "May contain milk and peanuts", "Milk-free; may contain soy"]
)
def test_allergen_qualifiers_are_quoted_not_reinterpreted(
    scan: R3ScanResult, statement: str
) -> None:
    scan.ingredients.allergen_text = statement
    answer, evidence = product_api._scan_assistant_answer(scan, "Is this safe for my milk allergy?")
    assert f"Package allergen statement / OCR: {statement}" in evidence
    assert "cannot certify it safe" in answer
    assert "not evidence of absence" in answer
    if "may contain" in statement.casefold():
        assert "Contains: Milk" not in answer


def test_no_explicit_statement_is_not_allergen_free(scan: R3ScanResult) -> None:
    scan.ingredients.allergen_text = ""
    answer, evidence = product_api._scan_assistant_answer(scan, "Which allergens are present?")
    assert "No explicit package allergen statement was recovered" in answer
    assert "does not establish allergy safety" in answer
    assert evidence == []


@pytest.mark.parametrize(
    "basis, expected",
    [
        ("PER_100_G", "per 100 g"),
        ("PER_100_ML", "per 100 ml"),
        ("PER_SERVING", "per serving"),
        ("UNKNOWN", "basis unknown"),
    ],
)
def test_exact_nutrition_basis_without_conversion(
    scan: R3ScanResult, basis: str, expected: str
) -> None:
    scan.nutrition = NutritionExtraction.model_validate(
        {"basis": basis, "table_rows": [{"label": "protein", "values": ["<0.5 g"]}]}
    )
    answer, _ = product_api._scan_assistant_answer(scan, "How much protein?")
    assert f"Protein: <0.5 g ({expected})" in answer
    assert "Serving size is unknown" in answer
    assert "No serving or unit conversion was inferred" in answer


def test_only_requested_nutrients_and_missing_amount_remain_unknown(scan: R3ScanResult) -> None:
    answer, _ = product_api._scan_assistant_answer(scan, "How much protein and sodium?")
    assert "Protein: 3.6 g" in answer
    assert "Sodium amount is unknown" in answer
    assert "Calcium:" not in answer
    assert "Sodium: 0" not in answer


def test_serving_size_does_not_create_a_serving_amount(scan: R3ScanResult) -> None:
    scan.nutrition.table_columns = ["per 100 ml"]
    scan.nutrition.table_rows = [NutritionRow(label="protein", values=["3.6"], units=["g"])]
    answer, _ = product_api._scan_assistant_answer(scan, "How much protein per serving?")
    assert "Protein: 3.6 g (per 100 ml)" in answer
    assert "250 ml" in answer
    assert "9 g" not in answer
    assert "No serving or unit conversion was inferred" in answer


@pytest.mark.parametrize(
    "row",
    [
        NutritionRow(label="protein", values=["3.6"]),
        NutritionRow(label="protein", values=["3.6 mg"], units=["g"]),
        NutritionRow(label="protein", values=["3.6"], units=["%"]),
        NutritionRow(label="unrecognized", values=["3.6"], units=["g"]),
        NutritionRow(label="protein", values=["-3.6"], units=["g"]),
    ],
)
def test_missing_conflicting_or_invalid_nutrition_is_not_invented(
    scan: R3ScanResult, row: NutritionRow
) -> None:
    scan.nutrition.table_rows = [row]
    answer, _ = product_api._scan_assistant_answer(scan, "How much protein?")
    assert "nutrition amount is unknown" in answer
    assert "Protein:" not in answer


def test_ambiguous_column_alignment_stays_unknown(scan: R3ScanResult) -> None:
    scan.nutrition.table_rows = [NutritionRow(label="protein", values=["9"], units=["g"])]
    answer, _ = product_api._scan_assistant_answer(scan, "How much protein?")
    assert "9 g (basis/column association unknown)" in answer
    assert "9 g (per 100 ml)" not in answer


def test_added_sugar_does_not_answer_with_total_sugar(scan: R3ScanResult) -> None:
    scan.nutrition.table_rows = [NutritionRow(label="total sugar", values=["5"], units=["g"])]
    answer, _ = product_api._scan_assistant_answer(scan, "How much added sugar?")
    assert "nutrition amount is unknown" in answer
    assert "5 g" not in answer


def test_unknown_question_does_not_get_unrelated_nova_answer(scan: R3ScanResult) -> None:
    answer, evidence = product_api._scan_assistant_answer(scan, "Will this cure a disease?")
    assert "insufficient" in answer
    assert "unknown" in answer
    assert evidence == []


def test_scan_ocr_is_not_sent_to_llm_or_unrelated_retrieval(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError(
            "Scan observations cannot be replaced by synthesis or unrelated citations"
        )

    monkeypatch.setattr(product_api, "generate_assistant_answer", forbidden)
    monkeypatch.setattr(product_api, "retrieve_knowledge", forbidden)
    monkeypatch.setattr(product_api, "retrieve_health_effects", forbidden)
    response = api.post(
        "/api/v1/assistant/messages",
        json={"scan_id": "owned-scan", "message": "Tell me about calcium in this scan"},
    )
    assert response.status_code == 200
    assert "Calcium: 200 mg" in response.json()["answer"]
    assert response.json()["citations"] == []


def test_cross_user_and_missing_scan_denied_before_quota(api: TestClient, owner: User) -> None:
    other = User("other", None, "other@example.test", "Other", None)
    cast(FastAPI, api.app).dependency_overrides[current_user] = lambda: other
    for scan_id in ("owned-scan", "missing"):
        response = api.post(
            "/api/v1/assistant/messages", json={"scan_id": scan_id, "message": "Explain scan"}
        )
        assert response.status_code == 404
        assert "Pasteurized" not in response.text
    assert product_api.product_store.assistant_usage == {}
    cast(FastAPI, api.app).dependency_overrides[current_user] = lambda: owner
    assert (
        api.post(
            "/api/v1/assistant/messages", json={"scan_id": "owned-scan", "message": "Explain scan"}
        ).status_code
        == 200
    )
    assert product_api.product_store.assistant_usage[(owner.id, datetime.now(UTC).date())] == 1


def test_diary_scan_references_are_owner_scoped_on_create_and_patch(
    api: TestClient, owner: User
) -> None:
    owned = api.post("/api/v1/diary", json={"name": "Owner meal", "scan_id": "owned-scan"})
    assert owned.status_code == 201
    other = User("other", None, "other@example.test", "Other", None)
    cast(FastAPI, api.app).dependency_overrides[current_user] = lambda: other
    for scan_id in ("owned-scan", "missing"):
        denied = api.post("/api/v1/diary", json={"name": "Other meal", "scan_id": scan_id})
        assert denied.status_code == 404
    assert api.get("/api/v1/diary").json() == []
    manual = api.post("/api/v1/diary", json={"name": "Manual meal"})
    assert manual.status_code == 201
    entry_id = manual.json()["id"]
    denied_patch = api.patch(f"/api/v1/diary/{entry_id}", json={"scan_id": "owned-scan"})
    assert denied_patch.status_code == 404
    assert api.get("/api/v1/diary").json()[0]["scan_id"] is None
    cast(FastAPI, api.app).dependency_overrides[current_user] = lambda: owner
    cleared = api.patch(f"/api/v1/diary/{owned.json()['id']}", json={"scan_id": None})
    assert cleared.status_code == 200
    assert cleared.json()["scan_id"] is None
