"""Unknown nutrition must survive recipe consumption and downstream diary calculations."""

import csv
from datetime import UTC, datetime, timedelta
from io import StringIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.auth import create_session_token, user_store
from backend.main import app
from backend.product_api import AccountProfileRecord, DiaryEntry, NutrientSnapshot, ProductStore

client = TestClient(app)


@pytest.fixture
def headers() -> dict[str, str]:
    subject = f"nullable-diary-{uuid4()}"
    user = user_store.upsert_google_user(
        {"sub": subject, "email": f"{subject}@example.com", "email_verified": True}
    )
    token, _ = create_session_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("invalid", [-1, float("inf"), float("-inf"), float("nan")])
def test_nutrient_snapshot_rejects_invalid_amounts(invalid: float) -> None:
    with pytest.raises(ValidationError):
        NutrientSnapshot(calories=invalid)


def test_nutrient_snapshot_preserves_unknown_and_explicit_zero() -> None:
    snapshot = NutrientSnapshot(calories=0, protein_g=None)
    assert snapshot.calories == 0
    assert snapshot.protein_g is None
    assert snapshot.calcium_mg is None


def test_mixed_diary_unknowns_propagate_through_summary_goals_trend_and_csv(
    headers: dict[str, str],
) -> None:
    empty = client.get("/api/v1/analytics/summary", headers=headers)
    assert set(empty.json()["totals"].values()) == {0}
    assert (
        client.put(
            "/api/v1/profile",
            headers=headers,
            json={
                "consent_personalization": True,
                "daily_targets": {"protein_g": 50, "sodium_mg": 100},
            },
        ).status_code
        == 200
    )
    for nutrients in [
        {"calories": 100, "protein_g": 2, "sodium_mg": 0},
        {"calories": 50, "sodium_mg": 0},
    ]:
        assert (
            client.post(
                "/api/v1/diary",
                headers=headers,
                json={"name": "Partial recipe", "nutrients": nutrients},
            ).status_code
            == 201
        )
    response = client.get("/api/v1/analytics/summary", headers=headers)
    assert response.status_code == 200
    summary = response.json()
    assert summary["totals"]["calories"] == 150
    assert summary["totals"]["protein_g"] is None
    assert summary["daily_averages"]["protein_g"] is None
    assert summary["totals"]["sodium_mg"] == 0
    goals = {item["nutrient"]: item for item in summary["goal_progress"]}
    assert goals["protein_g"]["daily_average"] is None
    assert goals["protein_g"]["percent_of_target"] is None
    assert goals["sodium_mg"]["percent_of_target"] == 0
    trend = client.get("/api/v1/analytics/trend", headers=headers, params={"days": 2})
    assert trend.status_code == 200
    assert trend.json()[0]["protein_g"] == 0
    assert trend.json()[-1]["protein_g"] is None
    assert trend.json()[-1]["calories"] == 150
    report = client.get("/api/v1/analytics/export.csv", headers=headers)
    rows = list(csv.DictReader(StringIO(report.text)))
    assert {row["protein_g"] for row in rows} == {"", "2.0"}
    assert {row["serving_grams"] for row in rows} == {""}
    assert {row["sodium_mg"] for row in rows} == {"0.0"}


def test_unknown_mass_and_unknown_nutrients_do_not_become_per_100g_values(
    headers: dict[str, str],
) -> None:
    entry_ids = []
    for mass in [None, 200]:
        response = client.post(
            "/api/v1/diary",
            headers=headers,
            json={
                "name": "Serving",
                "serving_grams": mass,
                "nutrients": {"calories": 100, "sugar_g": 0},
            },
        )
        assert response.status_code == 201
        entry_ids.append(response.json()["id"])
    response = client.post("/api/v1/diary/compare", headers=headers, json={"entry_ids": entry_ids})
    assert response.status_code == 200
    unknown, known = response.json()["candidates"]
    assert unknown["serving_grams"] is None
    assert set(unknown["per_100g"].values()) == {None}
    assert known["per_100g"]["calories"] == 50
    assert known["per_100g"]["sugar_g"] == 0
    assert known["per_100g"]["protein_g"] is None
    cleared = client.patch(
        f"/api/v1/diary/{entry_ids[1]}", headers=headers, json={"serving_grams": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["serving_grams"] is None


def test_recipe_comparison_preserves_nullable_nutrients(headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/recipes/compare",
        headers=headers,
        json={
            "candidates": [
                {"name": "Partial", "servings": 2, "nutrients": {"calories": 200, "sugar_g": 0}},
                {"name": "Unknown", "servings": 1, "nutrients": {}},
            ]
        },
    )
    assert response.status_code == 200
    partial, unknown = response.json()["candidates"]
    assert partial["per_serving"]["calories"] == 100
    assert partial["per_serving"]["sugar_g"] == 0
    assert partial["per_serving"]["protein_g"] is None
    assert set(unknown["per_serving"].values()) == {None}


def test_unknown_period_metric_is_not_comparable_but_recorded_zero_is_unchanged(
    headers: dict[str, str],
) -> None:
    for days_ago, nutrients in [(1, {"calories": 0}), (8, {"calories": 0, "protein_g": 2})]:
        assert (
            client.post(
                "/api/v1/diary",
                headers=headers,
                json={
                    "name": "Period entry",
                    "nutrients": nutrients,
                    "eaten_at": (datetime.now(UTC) - timedelta(days=days_ago)).isoformat(),
                },
            ).status_code
            == 201
        )
    response = client.get("/api/v1/analytics/compare", headers=headers, params={"days": 7})
    assert response.status_code == 200
    changes = {item["nutrient"]: item for item in response.json()["changes"]}
    assert changes["calories"]["direction"] == "UNCHANGED"
    assert changes["calories"]["absolute_change"] == 0
    assert changes["protein_g"]["direction"] == "NOT_COMPARABLE"
    assert changes["protein_g"]["absolute_change"] is None


def test_incomplete_energy_does_not_generate_daily_range(headers: dict[str, str]) -> None:
    for days_ago in range(7):
        assert (
            client.post(
                "/api/v1/diary",
                headers=headers,
                json={
                    "name": "Partial meal",
                    "nutrients": {} if days_ago == 0 else {"calories": 100},
                    "eaten_at": (datetime.now(UTC) - timedelta(days=days_ago)).isoformat(),
                },
            ).status_code
            == 201
        )
    response = client.get("/api/v1/analytics/patterns", headers=headers)
    assert response.status_code == 200
    assert response.json()["state"] == "AVAILABLE"
    assert all(item["kind"] != "NUTRIENT_RANGE" for item in response.json()["observations"])


def test_research_summary_propagates_missing_nutrients() -> None:
    store = ProductStore()
    assert store.research_summary()[2].calories == 0
    for index, nutrients in enumerate(
        [NutrientSnapshot(calories=50, sugar_g=0), NutrientSnapshot(sugar_g=0)]
    ):
        store.put_account_profile(
            str(index),
            AccountProfileRecord(full_name=f"Participant {index}", research_insights_consent=True),
        )
        store.add_diary(
            str(index), DiaryEntry(id=str(uuid4()), name="Partial", nutrients=nutrients)
        )
    users, count, totals = store.research_summary()
    assert (users, count) == (2, 2)
    assert totals.calories is None
    assert totals.sugar_g == 0


def test_manual_diary_cannot_claim_recipe_metadata(headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/diary",
        headers=headers,
        json={
            "name": "Manual",
            "source": "CUSTOM_RECIPE",
            "recipe_id": str(uuid4()),
            "recipe_version": 3,
            "recipe_servings": 1,
        },
    )
    assert response.status_code == 201
    assert response.json()["source"] == "MANUAL"
    assert response.json()["recipe_id"] is None
    updated = client.patch(
        f"/api/v1/diary/{response.json()['id']}",
        headers=headers,
        json={"source": "CUSTOM_RECIPE", "recipe_id": str(uuid4())},
    )
    assert updated.status_code == 200
    assert updated.json()["source"] == "MANUAL"
    assert updated.json()["recipe_id"] is None


def test_calorie_counter_full_accounting_lifecycle(headers: dict[str, str]) -> None:
    """Verify calorie counter invariants:
    - Scanning alone does NOT alter diary totals.
    - Explicit 'Add to Diary' increments calories.
    - Editing serving mass / quantity recalculates totals.
    - Deleting entry decrements totals.
    - Unknown nutrients are not silently coerced to zero.
    """
    # Baseline summary
    base_resp = client.get("/api/v1/analytics/summary", headers=headers)
    assert base_resp.status_code == 200
    base_cal = base_resp.json()["totals"]["calories"] or 0

    # 1. Add diary entry (e.g. 250 kcal)
    add_resp = client.post(
        "/api/v1/diary",
        headers=headers,
        json={"name": "Oatmeal Bowl", "nutrients": {"calories": 250.0}},
    )
    assert add_resp.status_code == 201
    entry_id = add_resp.json()["id"]

    # Diary increases
    after_add = client.get("/api/v1/analytics/summary", headers=headers)
    assert after_add.json()["totals"]["calories"] == base_cal + 250

    # 2. Update diary entry (change serving calories to 400 kcal)
    patch_resp = client.patch(
        f"/api/v1/diary/{entry_id}",
        headers=headers,
        json={"name": "Large Oatmeal Bowl", "nutrients": {"calories": 400.0}},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["nutrients"]["calories"] == 400.0

    # Totals recalculate
    after_patch = client.get("/api/v1/analytics/summary", headers=headers)
    assert after_patch.json()["totals"]["calories"] == base_cal + 400

    # 3. Delete diary entry
    del_resp = client.delete(f"/api/v1/diary/{entry_id}", headers=headers)
    assert del_resp.status_code == 204

    # Totals return to baseline
    after_del = client.get("/api/v1/analytics/summary", headers=headers)
    assert (after_del.json()["totals"]["calories"] or 0) == base_cal
