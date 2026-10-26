"""Unit and integration tests for Food Compare API.

Requirements:
- Neutral comparison by default: no universal 'healthier' declaration without explicit goal.
- Explicit goal relevance only when a supported explicit goal exists.
- Distinct handling when bases differ (PER_100_G vs PER_SERVING) without assuming equivalence.
- UNKNOWN != 0: Missing nutrient values are None, never assumed 0.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import backend.product_api as product_api
from ai.food_understanding.schemas import (
    IngredientExtraction,
    NutritionExtraction,
    NutritionRow,
)
from backend.auth import create_session_token, user_store
from backend.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _auth_headers(
    client: TestClient, sub: str, email: str, goal: str | None = None
) -> dict[str, str]:
    user = user_store.upsert_google_user(
        {
            "sub": sub,
            "email": email,
            "email_verified": True,
        }
    )
    token, _ = create_session_token(user)
    headers = {"Authorization": f"Bearer {token}"}
    client.put(
        "/api/v1/profile",
        headers=headers,
        json={
            "goal": goal,
            "allergens": [],
            "dietary_preferences": [],
            "consent_personalization": True,
        },
    )
    return headers


def test_neutral_comparison_by_default(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """When user has no explicit goal, comparison is neutral: recommended_scan_id is None."""
    headers = _auth_headers(client, "neutral-user", "neutral@example.com", goal=None)

    scan_a = SimpleNamespace(
        scan_id="scan-a",
        ingredients=IngredientExtraction(raw_text="almonds, salt"),
        nutrition=NutritionExtraction(
            basis="PER_100_G",
            table_rows=[
                NutritionRow(label="protein", values=["21"], units=["g"]),
                NutritionRow(label="fat", values=["50"], units=["g"]),
            ],
        ),
        product_name_candidates=[SimpleNamespace(value="Roasted Almonds")],
        brand_candidates=[],
    )
    scan_b = SimpleNamespace(
        scan_id="scan-b",
        ingredients=IngredientExtraction(raw_text="cashews, salt"),
        nutrition=NutritionExtraction(
            basis="PER_100_G",
            table_rows=[
                NutritionRow(label="protein", values=["18"], units=["g"]),
                NutritionRow(label="fat", values=["44"], units=["g"]),
            ],
        ),
        product_name_candidates=[SimpleNamespace(value="Roasted Cashews")],
        brand_candidates=[],
    )

    monkeypatch.setattr(
        product_api,
        "get_owned_scan_result",
        lambda sid, _user: scan_a if sid == "scan-a" else scan_b,
    )

    resp = client.post(
        "/api/v1/recommendations/compare",
        headers=headers,
        json={"scan_ids": ["scan-a", "scan-b"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["candidates"]) == 2
    # Neutral: no winner picked without explicit goal
    assert data["recommended_scan_id"] is None


def test_explicit_goal_relevance_low_sugar(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Explicit supported goal (low-sugar) picks candidate with lower sugar when comparable."""
    headers = _auth_headers(client, "sugar-user", "sugar@example.com", goal="low-sugar")

    scan_sweet = SimpleNamespace(
        scan_id="scan-sweet",
        ingredients=IngredientExtraction(raw_text="corn, sugar, salt"),
        nutrition=NutritionExtraction(
            basis="PER_100_G",
            table_rows=[
                NutritionRow(label="sugars", values=["25"], units=["g"]),
                NutritionRow(label="protein", values=["5"], units=["g"]),
            ],
        ),
        product_name_candidates=[SimpleNamespace(value="Sweet Flakes")],
        brand_candidates=[],
    )
    scan_plain = SimpleNamespace(
        scan_id="scan-plain",
        ingredients=IngredientExtraction(raw_text="corn, salt"),
        nutrition=NutritionExtraction(
            basis="PER_100_G",
            table_rows=[
                NutritionRow(label="sugars", values=["2"], units=["g"]),
                NutritionRow(label="protein", values=["5"], units=["g"]),
            ],
        ),
        product_name_candidates=[SimpleNamespace(value="Plain Flakes")],
        brand_candidates=[],
    )

    monkeypatch.setattr(
        product_api,
        "get_owned_scan_result",
        lambda sid, _user: scan_sweet if sid == "scan-sweet" else scan_plain,
    )

    resp = client.post(
        "/api/v1/recommendations/compare",
        headers=headers,
        json={"scan_ids": ["scan-sweet", "scan-plain"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["recommended_scan_id"] == "scan-plain"


def test_differing_bases_without_conversion_adds_limitation_and_no_recommendation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When bases differ (PER_100_G vs PER_SERVING) without serving size to normalize,
    direct comparison is limited.
    """
    headers = _auth_headers(client, "basis-user", "basis@example.com", goal="high-protein")

    scan_100g = SimpleNamespace(
        scan_id="scan-100g",
        ingredients=IngredientExtraction(raw_text="wheat flour"),
        nutrition=NutritionExtraction(
            basis="PER_100_G",
            serving_size_value=None,
            serving_size_unit=None,
            table_rows=[
                NutritionRow(label="protein", values=["12"], units=["g"]),
            ],
        ),
        product_name_candidates=[SimpleNamespace(value="Flour 100g")],
        brand_candidates=[],
    )
    scan_srv = SimpleNamespace(
        scan_id="scan-srv",
        ingredients=IngredientExtraction(raw_text="wheat biscuit"),
        nutrition=NutritionExtraction(
            basis="PER_SERVING",
            serving_size_value=None,
            serving_size_unit=None,
            table_rows=[
                NutritionRow(label="protein", values=["6"], units=["g"]),
            ],
        ),
        product_name_candidates=[SimpleNamespace(value="Biscuit Serving")],
        brand_candidates=[],
    )

    monkeypatch.setattr(
        product_api,
        "get_owned_scan_result",
        lambda sid, _user: scan_100g if sid == "scan-100g" else scan_srv,
    )

    resp = client.post(
        "/api/v1/recommendations/compare",
        headers=headers,
        json={"scan_ids": ["scan-100g", "scan-srv"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Must NOT guess or assume equivalence
    assert data["recommended_scan_id"] is None
    all_limitations = [lim for c in data["candidates"] for lim in c["limitations"]]
    assert any("different basis declarations" in lim for lim in all_limitations)


def test_unknown_not_equal_to_zero(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing/unknown nutrient values remain None and are NOT treated as 0g."""
    headers = _auth_headers(client, "unknown-user", "unknown@example.com", goal="high-protein")

    scan_known = SimpleNamespace(
        scan_id="scan-known",
        ingredients=IngredientExtraction(raw_text="tofu"),
        nutrition=NutritionExtraction(
            basis="PER_100_G",
            table_rows=[
                NutritionRow(label="protein", values=["8"], units=["g"]),
            ],
        ),
        product_name_candidates=[SimpleNamespace(value="Tofu")],
        brand_candidates=[],
    )
    scan_unknown = SimpleNamespace(
        scan_id="scan-unknown",
        ingredients=IngredientExtraction(raw_text="tea leaves"),
        nutrition=NutritionExtraction(
            basis="PER_100_G",
            table_rows=[
                NutritionRow(label="energy", values=["1"], units=["kcal"]),
                # Protein is completely missing / unknown
            ],
        ),
        product_name_candidates=[SimpleNamespace(value="Green Tea")],
        brand_candidates=[],
    )

    monkeypatch.setattr(
        product_api,
        "get_owned_scan_result",
        lambda sid, _user: scan_known if sid == "scan-known" else scan_unknown,
    )

    resp = client.post(
        "/api/v1/recommendations/compare",
        headers=headers,
        json={"scan_ids": ["scan-known", "scan-unknown"]},
    )
    assert resp.status_code == 200
    data = resp.json()

    c_unk = next(c for c in data["candidates"] if c["scan_id"] == "scan-unknown")
    assert c_unk["nutrients_per_100"]["protein_g"] is None  # UNKNOWN != 0
    # Must not declare recommendation when goal nutrient is unknown
    assert data["recommended_scan_id"] is None
    all_limitations = [lim for c in data["candidates"] for lim in c["limitations"]]
    assert any("unknown values cannot be assumed zero" in lim for lim in all_limitations)
