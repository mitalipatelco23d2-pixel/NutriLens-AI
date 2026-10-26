from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ai.food_understanding.schemas import IngredientExtraction, NutritionExtraction
from backend.auth import User, create_session_token, current_user, user_store
from backend.entitlements import PlanCode, SpecialRole, SubscriptionStatus
from backend.main import app
from backend.product_api import AccountProfileRecord, DiaryEntry, NutrientSnapshot, ProductStore

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


def test_profile_diary_pantry_and_analytics_journey() -> None:
    headers = _headers("journey-user", "journey@example.com")

    profile = client.put(
        "/api/v1/profile",
        headers=headers,
        json={
            "goal": "low-sodium",
            "allergens": ["peanuts"],
            "dietary_preferences": ["vegetarian"],
            "consent_personalization": True,
            "daily_targets": {"protein_g": 20, "calcium_mg": 480},
        },
    )
    assert profile.status_code == 200

    diary = client.post(
        "/api/v1/diary",
        headers=headers,
        json={
            "name": "Oat breakfast",
            "serving_grams": 120,
            "nutrients": {
                "calories": 320,
                "protein_g": 14,
                "sodium_mg": 180,
                "fiber_g": 8,
                "vitamin_c_mg": 12,
                "calcium_mg": 240,
                "iron_mg": 4.5,
                "potassium_mg": 420,
            },
        },
    )
    assert diary.status_code == 201
    diary_id = diary.json()["id"]
    updated_diary = client.patch(
        f"/api/v1/diary/{diary_id}",
        headers=headers,
        json={"name": "Oat and fruit breakfast", "serving_grams": 140},
    )
    assert updated_diary.status_code == 200
    assert updated_diary.json()["name"] == "Oat and fruit breakfast"
    assert updated_diary.json()["serving_grams"] == 140

    pantry = client.post(
        "/api/v1/pantry",
        headers=headers,
        json={"name": "Rolled oats", "quantity": 1, "unit": "kg"},
    )
    assert pantry.status_code == 201
    pantry_id = pantry.json()["id"]
    updated_pantry = client.patch(
        f"/api/v1/pantry/{pantry_id}",
        headers=headers,
        json={"quantity": 2, "expires_on": "2030-01-15"},
    )
    assert updated_pantry.status_code == 200
    assert updated_pantry.json()["quantity"] == 2
    assert updated_pantry.json()["expires_on"] == "2030-01-15"
    assert (
        client.post(
            "/api/v1/pantry",
            headers=headers,
            json={"name": "Cooked white beans", "quantity": 1, "unit": "cup"},
        ).status_code
        == 201
    )
    recipes = client.get("/api/v1/recipes/recommendations", headers=headers)
    assert recipes.status_code == 200
    assert (
        recipes.json()[0]["method"]
        == "DETERMINISTIC_PANTRY_COVERAGE_WITH_FUNCTIONAL_SUBSTITUTIONS_V2"
    )
    assert recipes.json()[0]["source_version"] == "0.2.0"
    assert recipes.json()[0]["preparation_complexity"] == {
        "band": "BASIC",
        "written_steps": 2,
        "required_ingredients": 2,
        "method": "CURATED_TEMPLATE_COUNT_BAND_V1",
        "limitation": (
            "A structural estimate from written step and required-ingredient counts only. It does "
            "not measure time, equipment, cooking skill, accessibility or individual difficulty."
        ),
    }
    chickpea_recipe = next(
        item for item in recipes.json() if item["recipe_id"] == "chickpea-tomato-salad"
    )
    assert chickpea_recipe["available_substitutions"][0] == {
        "missing_ingredient": "chickpea",
        "available_alternative": "white beans",
        "function": "cooked legume base",
        "limitation": "Texture, flavor and label-reported nutrients differ.",
    }
    analytics = client.get("/api/v1/analytics/summary", headers=headers)
    assert analytics.status_code == 200
    assert analytics.json()["diary_entries"] == 1
    assert analytics.json()["totals"]["protein_g"] == 14
    assert analytics.json()["totals"]["calcium_mg"] == 240
    assert analytics.json()["daily_averages"]["iron_mg"] == 4.5
    assert analytics.json()["goal_tracking_state"] == "AVAILABLE"
    assert analytics.json()["goal_progress"] == [
        {
            "nutrient": "protein_g",
            "label": "Protein",
            "unit": "g",
            "daily_average": 14.0,
            "user_target": 20.0,
            "percent_of_target": 70.0,
        },
        {
            "nutrient": "calcium_mg",
            "label": "Calcium",
            "unit": "mg",
            "daily_average": 240.0,
            "user_target": 480.0,
            "percent_of_target": 50.0,
        },
    ]
    assert "does not assess nutritional adequacy" in analytics.json()["goal_tracking_limitation"]
    trend = client.get("/api/v1/analytics/trend", headers=headers, params={"days": 7})
    assert trend.status_code == 200
    assert len(trend.json()) == 7
    assert trend.json()[-1]["calories"] == 320
    assert trend.json()[-1]["vitamin_c_mg"] == 12
    report = client.get("/api/v1/analytics/export.csv", headers=headers)
    assert report.status_code == 200
    assert report.headers["content-type"].startswith("text/csv")
    assert "Oat and fruit breakfast" in report.text
    assert "vitamin_c_mg" in report.text
    assert ",240.0,4.5,420.0," in report.text


def test_recipe_nutrition_comparison_normalizes_supplied_totals_without_ranking() -> None:
    headers = _headers("recipe-compare", "recipe-compare@example.com")
    compared = client.post(
        "/api/v1/recipes/compare",
        headers=headers,
        json={
            "candidates": [
                {
                    "name": "Bean stew",
                    "servings": 4,
                    "source_label": "Package labels and measured ingredients",
                    "nutrients": {
                        "calories": 1200,
                        "protein_g": 60,
                        "sodium_mg": 1600,
                        "fiber_g": 40,
                    },
                },
                {
                    "name": "Vegetable soup",
                    "servings": 2,
                    "nutrients": {
                        "calories": 500,
                        "protein_g": 20,
                        "sodium_mg": 900,
                        "fiber_g": 18,
                    },
                },
            ]
        },
    )
    assert compared.status_code == 200
    assert compared.json()["candidates"][0]["per_serving"]["calories"] == 300
    assert compared.json()["candidates"][0]["per_serving"]["protein_g"] == 15
    assert compared.json()["candidates"][1]["per_serving"]["fiber_g"] == 9
    assert compared.json()["candidates"][0]["nutrients"]["calories"] == 1200
    assert "no recipe is ranked" in compared.json()["limitation"]
    assert "recommended" not in compared.json()

    duplicate = client.post(
        "/api/v1/recipes/compare",
        headers=headers,
        json={
            "candidates": [
                {"name": "Same", "servings": 1, "nutrients": {}},
                {"name": " same ", "servings": 2, "nutrients": {}},
            ]
        },
    )
    assert duplicate.status_code == 422
    assert duplicate.json()["detail"] == "Recipe names must be unique."


def test_recipe_nutrition_comparison_requires_authentication() -> None:
    response = client.post(
        "/api/v1/recipes/compare",
        json={
            "candidates": [
                {"name": "One", "nutrients": {}},
                {"name": "Two", "nutrients": {}},
            ]
        },
    )
    assert response.status_code == 401


def test_use_soon_recipe_suggestions_use_only_owner_marked_or_dated_items() -> None:
    owner = _headers("use-soon-owner", "use-soon-owner@example.com")
    other = _headers("use-soon-other", "use-soon-other@example.com")
    today = datetime.now(UTC).date()
    pantry_payloads = [
        {
            "name": "Chickpea",
            "quantity": 1,
            "unit": "bowl",
            "item_role": "LEFTOVER",
        },
        {
            "name": "Tomato",
            "quantity": 2,
            "unit": "item",
            "expires_on": (today + timedelta(days=2)).isoformat(),
        },
        {
            "name": "Spinach",
            "quantity": 1,
            "unit": "bag",
            "expires_on": (today - timedelta(days=1)).isoformat(),
        },
    ]
    for payload in pantry_payloads:
        assert client.post("/api/v1/pantry", headers=owner, json=payload).status_code == 201

    response = client.get("/api/v1/recipes/use-soon", headers=owner)
    assert response.status_code == 200
    payload = response.json()
    salad = next(
        item
        for item in payload["suggestions"]
        if item["recipe"]["recipe_id"] == "chickpea-tomato-salad"
    )
    attention = {item["name"]: item["reasons"] for item in salad["attention_items"]}
    assert attention == {
        "Chickpea": ["USER_MARKED_LEFTOVER"],
        "Tomato": ["EXPIRING_SOON"],
    }
    assert "Spinach" not in attention
    assert "never use expired or spoiled food" in payload["limitation"]
    assert "nutrition" in payload["limitation"]
    assert client.get("/api/v1/recipes/use-soon", headers=other).json()["suggestions"] == []


def test_bmi_context_requires_consent_and_returns_only_adult_formula_result() -> None:
    owner = _headers("bmi-owner", "bmi-owner@example.com")
    other = _headers("bmi-other", "bmi-other@example.com")
    empty = client.get("/api/v1/profile/bmi-context", headers=owner)
    assert empty.status_code == 200
    assert empty.json()["state"] == "NOT_CONFIGURED"
    assert empty.json()["bmi"] is None

    without_consent = client.put(
        "/api/v1/profile",
        headers=owner,
        json={"body_context": {"height_cm": 175, "weight_kg": 70}},
    )
    assert without_consent.status_code == 422
    child_context = client.put(
        "/api/v1/profile",
        headers=owner,
        json={
            "body_context": {
                "adult_attestation": False,
                "consent_bmi_context": True,
                "height_cm": 175,
                "weight_kg": 70,
            }
        },
    )
    assert child_context.status_code == 422

    saved = client.put(
        "/api/v1/profile",
        headers=owner,
        json={
            "body_context": {
                "adult_attestation": True,
                "consent_bmi_context": True,
                "height_cm": 175,
                "weight_kg": 70,
            }
        },
    )
    assert saved.status_code == 200
    result = client.get("/api/v1/profile/bmi-context", headers=owner)
    assert result.status_code == 200
    assert result.json()["state"] == "AVAILABLE"
    assert result.json()["bmi"] == 22.86
    assert result.json()["height_cm"] == 175
    assert "category" not in result.json()
    assert "recommend" not in result.json()
    assert "does not assign a category" in result.json()["limitation"]
    assert client.get("/api/v1/profile/bmi-context", headers=other).json()["bmi"] is None


def test_wellness_goal_taxonomy_and_custom_goal_are_bounded() -> None:
    headers = _headers("goal-owner", "goal-owner@example.com")

    for goal in (
        "maintain-weight",
        "lose-weight-gradually",
        "gain-weight-gradually",
        "improve-nutrition",
    ):
        saved = client.put("/api/v1/profile", headers=headers, json={"goal": goal})
        assert saved.status_code == 200
        assert saved.json()["goal"] == goal
        assert saved.json()["custom_goal"] is None

    custom = client.put(
        "/api/v1/profile",
        headers=headers,
        json={"goal": "custom", "custom_goal": "  Cook at home more often  "},
    )
    assert custom.status_code == 200
    assert custom.json()["custom_goal"] == "Cook at home more often"

    for invalid in (
        {"goal": "custom"},
        {"goal": "custom", "custom_goal": "   "},
        {"goal": "balanced", "custom_goal": "Hidden custom instruction"},
        {"goal": "custom", "custom_goal": "x" * 121},
        {"goal": "rapid-weight-loss"},
    ):
        assert client.put("/api/v1/profile", headers=headers, json=invalid).status_code == 422


def test_bmi_context_rejects_partial_or_out_of_bounds_measurements() -> None:
    headers = _headers("bmi-invalid", "bmi-invalid@example.com")
    for body_context in (
        {
            "adult_attestation": True,
            "consent_bmi_context": True,
            "height_cm": 175,
        },
        {
            "adult_attestation": True,
            "consent_bmi_context": True,
            "height_cm": 99,
            "weight_kg": 70,
        },
        {
            "adult_attestation": True,
            "consent_bmi_context": True,
            "height_cm": 175,
            "weight_kg": 501,
        },
    ):
        assert (
            client.put(
                "/api/v1/profile",
                headers=headers,
                json={"body_context": body_context},
            ).status_code
            == 422
        )


def test_analytics_csv_neutralizes_spreadsheet_formulas() -> None:
    headers = _headers("csv-user", "csv@example.com")
    created = client.post(
        "/api/v1/diary",
        headers=headers,
        json={"name": '=HYPERLINK("https://invalid.example")', "nutrients": {}},
    )
    assert created.status_code == 201

    report = client.get("/api/v1/analytics/export.csv", headers=headers)
    assert report.status_code == 200
    assert "'=HYPERLINK" in report.text


def test_favorites_are_durable_idempotent_and_owner_scoped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.product_api as product_api

    owner_headers = _headers("favorite-owner", "favorite-owner@example.com")
    other_headers = _headers("favorite-other", "favorite-other@example.com")
    scan = SimpleNamespace(
        product_name_candidates=[SimpleNamespace(value="Owner oats")],
        brand_candidates=[SimpleNamespace(value="Example brand")],
    )

    def owned_scan(scan_id: str, user: User) -> SimpleNamespace:
        if scan_id != "favorite-scan" or user.email != "favorite-owner@example.com":
            from ai.food_understanding.store import ScanNotFoundError

            raise ScanNotFoundError(scan_id)
        return scan

    monkeypatch.setattr(product_api, "get_owned_scan_result", owned_scan)

    first = client.put("/api/v1/favorites/favorite-scan", headers=owner_headers)
    second = client.put("/api/v1/favorites/favorite-scan", headers=owner_headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["product_name"] == "Owner oats"
    assert second.json()["saved_at"] == first.json()["saved_at"]
    assert len(client.get("/api/v1/favorites", headers=owner_headers).json()) == 1
    assert client.get("/api/v1/favorites", headers=other_headers).json() == []
    assert client.put("/api/v1/favorites/favorite-scan", headers=other_headers).status_code == 404
    assert (
        client.delete("/api/v1/favorites/favorite-scan", headers=owner_headers).status_code == 204
    )
    assert (
        client.delete("/api/v1/favorites/favorite-scan", headers=owner_headers).status_code == 404
    )


def test_universal_search_combines_only_owner_scans_with_governed_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.product_api as product_api

    scan = SimpleNamespace(
        scan_id="search-scan",
        product_name_candidates=[SimpleNamespace(value="Oat breakfast")],
        brand_candidates=[SimpleNamespace(value="Owner brand")],
    )
    monkeypatch.setattr(
        product_api,
        "_owned_scans",
        lambda user: [scan] if user.email == "search-owner@example.com" else [],
    )
    monkeypatch.setattr(product_api, "retrieve_knowledge", lambda query, limit: [])
    owner_headers = _headers("search-owner", "search-owner@example.com")
    other_headers = _headers("search-other", "search-other@example.com")

    found = client.get("/api/v1/search", headers=owner_headers, params={"q": "oat"})
    assert found.status_code == 200
    scan_result = next(item for item in found.json()["items"] if item["kind"] == "SCAN")
    assert scan_result["id"] == "search-scan"
    assert "not a complete food catalogue" in found.json()["limitation"]
    other_items = client.get("/api/v1/search", headers=other_headers, params={"q": "oat"}).json()[
        "items"
    ]
    assert all(item["kind"] != "SCAN" for item in other_items)
    assert other_items[0]["kind"] == "SUBSTITUTION"
    assert client.get("/api/v1/search", headers=owner_headers, params={"q": "x"}).status_code == 422


def test_analytics_period_is_requested_but_entitlement_capped() -> None:
    headers = _headers("period-user", "period@example.com")
    short = client.get("/api/v1/analytics/summary", headers=headers, params={"days": 3})
    long = client.get("/api/v1/analytics/summary", headers=headers, params={"days": 90})
    assert short.status_code == 200
    assert short.json()["period_days"] == 3
    assert long.status_code == 200
    assert long.json()["period_days"] == 7


def test_meal_comparison_and_analytics_drilldown_are_owner_scoped() -> None:
    owner = _headers("meal-compare-owner", "meal-compare-owner@example.com")
    other = _headers("meal-compare-other", "meal-compare-other@example.com")
    first = client.post(
        "/api/v1/diary",
        headers=owner,
        json={
            "name": "Logged breakfast",
            "serving_grams": 200,
            "nutrients": {"calories": 300, "protein_g": 12, "fiber_g": 8},
        },
    ).json()
    second = client.post(
        "/api/v1/diary",
        headers=owner,
        json={
            "name": "Logged lunch",
            "serving_grams": 250,
            "nutrients": {"calories": 500, "protein_g": 20, "sodium_mg": 600},
        },
    ).json()

    compared = client.post(
        "/api/v1/diary/compare",
        headers=owner,
        json={"entry_ids": [first["id"], second["id"]]},
    )
    assert compared.status_code == 200
    payload = compared.json()
    assert [item["name"] for item in payload["candidates"]] == [
        "Logged breakfast",
        "Logged lunch",
    ]
    assert payload["candidates"][0]["logged_serving"]["calories"] == 300
    assert payload["candidates"][0]["per_100g"]["calories"] == 150
    assert "recommended_entry_id" not in payload
    assert "no meal is ranked as healthier" in payload["limitation"]

    duplicate = client.post(
        "/api/v1/diary/compare",
        headers=owner,
        json={"entry_ids": [first["id"], first["id"]]},
    )
    assert duplicate.status_code == 422
    assert (
        client.post(
            "/api/v1/diary/compare",
            headers=other,
            json={"entry_ids": [first["id"], second["id"]]},
        ).status_code
        == 404
    )

    today = datetime.now(UTC).date().isoformat()
    drilldown = client.get(
        "/api/v1/analytics/drilldown",
        headers=owner,
        params={"days": 90, "date": today},
    )
    assert drilldown.status_code == 200
    assert drilldown.json()["period_days"] == 7
    assert {item["name"] for item in drilldown.json()["entries"]} == {
        "Logged breakfast",
        "Logged lunch",
    }
    assert (
        client.get(
            "/api/v1/analytics/drilldown",
            headers=other,
            params={"days": 7, "date": today},
        ).json()["entries"]
        == []
    )


def test_equal_window_analytics_comparison_produces_neutral_evidence_stories() -> None:
    owner = _headers("analytics-compare-owner", "analytics-compare@example.com")
    other = _headers("analytics-compare-other", "analytics-other@example.com")
    now = datetime.now(UTC)
    for name, eaten_at, calories, protein in [
        ("Previous meal", now - timedelta(days=7), 100, 5),
        ("Current meal", now, 200, 8),
    ]:
        created = client.post(
            "/api/v1/diary",
            headers=owner,
            json={
                "name": name,
                "eaten_at": eaten_at.isoformat(),
                "nutrients": {"calories": calories, "protein_g": protein},
            },
        )
        assert created.status_code == 201

    response = client.get("/api/v1/analytics/compare", headers=owner, params={"days": 7})
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "AVAILABLE"
    assert payload["current"]["diary_entries"] == 1
    assert payload["previous"]["diary_entries"] == 1
    energy = next(item for item in payload["changes"] if item["nutrient"] == "calories")
    assert energy == {
        "nutrient": "calories",
        "label": "Energy",
        "unit": "kcal/day",
        "direction": "HIGHER",
        "absolute_change": 100.0,
        "percent_change": 100.0,
    }
    assert any("100 kcal/day higher" in story["evidence"] for story in payload["stories"])
    assert "does not assess improvement" in payload["limitation"]
    assert "recommended" not in payload
    assert "score" not in payload

    isolated = client.get("/api/v1/analytics/compare", headers=other, params={"days": 7})
    assert isolated.status_code == 200
    assert isolated.json()["state"] == "INSUFFICIENT_HISTORY"
    assert isolated.json()["changes"] == []


def test_analytics_comparison_respects_history_entitlement() -> None:
    headers = _headers("analytics-compare-cap", "analytics-cap@example.com")
    response = client.get("/api/v1/analytics/compare", headers=headers, params={"days": 90})
    assert response.status_code == 200
    assert response.json()["period_days"] == 7


def test_dietary_patterns_require_history_and_remain_descriptive() -> None:
    owner = _headers("pattern-owner", "pattern-owner@example.com")
    other = _headers("pattern-other", "pattern-other@example.com")
    insufficient = client.get("/api/v1/analytics/patterns", headers=owner)
    assert insufficient.status_code == 200
    assert insufficient.json()["state"] == "INSUFFICIENT_HISTORY"
    assert insufficient.json()["observations"] == []

    now = datetime.now(UTC).replace(hour=8, minute=0, second=0, microsecond=0)
    for offset in range(7):
        created = client.post(
            "/api/v1/diary",
            headers=owner,
            json={
                "name": "Oats" if offset < 3 else f"Meal {offset}",
                "eaten_at": (now - timedelta(days=offset)).isoformat(),
                "serving_grams": 100,
                "nutrients": {"calories": 200 + offset * 10, "protein_g": 8},
            },
        )
        assert created.status_code == 201

    patterns = client.get("/api/v1/analytics/patterns", headers=owner, params={"days": 90})
    assert patterns.status_code == 200
    payload = patterns.json()
    assert payload["period_days"] == 7
    assert payload["state"] == "AVAILABLE"
    assert payload["observed_days"] == 7
    assert {item["kind"] for item in payload["observations"]} == {
        "LOGGING_COVERAGE",
        "RECURRING_ENTRY",
        "MEAL_TIMING",
        "NUTRIENT_RANGE",
    }
    assert "do not classify a diet" in payload["limitation"]
    assert client.get("/api/v1/analytics/patterns", headers=other).json()["observed_days"] == 0


def test_assistant_uses_governed_nutrient_role_reference() -> None:
    headers = _headers("nutrient-role-user", "nutrient-role@example.com")
    response = client.post(
        "/api/v1/assistant/messages",
        headers=headers,
        json={"message": "What role does calcium have?"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert "structure of bones and teeth" in payload["answer"]
    assert "not a diagnosis" in payload["answer"]
    assert payload["citations"][0]["authority"] == "NIH Office of Dietary Supplements"


def test_cross_user_delete_is_not_possible() -> None:
    owner = _headers("record-owner", "owner@example.com")
    other = _headers("record-other", "other@example.com")
    created = client.post(
        "/api/v1/diary",
        headers=owner,
        json={"name": "Private meal", "nutrients": {}},
    )
    entry_id = created.json()["id"]

    assert client.delete(f"/api/v1/diary/{entry_id}", headers=other).status_code == 404
    assert client.delete(f"/api/v1/diary/{entry_id}", headers=owner).status_code == 204


def test_expiry_notification_is_owner_scoped_and_can_be_read() -> None:
    owner = _headers("notification-owner", "notify-owner@example.com")
    other = _headers("notification-other", "notify-other@example.com")
    pantry = client.post(
        "/api/v1/pantry",
        headers=owner,
        json={
            "name": "Fresh spinach",
            "quantity": 1,
            "unit": "bag",
            "expires_on": datetime.now(UTC).date().isoformat(),
        },
    )
    assert pantry.status_code == 201
    pantry_id = pantry.json()["id"]

    notifications = client.get("/api/v1/notifications", headers=owner)
    assert notifications.status_code == 200
    notification = notifications.json()[0]
    assert notification["kind"] == "PANTRY_EXPIRY"
    assert notification["read_at"] is None
    assert "Verify the package date" in notification["body"]

    assert (
        client.patch(f"/api/v1/notifications/{notification['id']}/read", headers=other).status_code
        == 404
    )
    read = client.patch(f"/api/v1/notifications/{notification['id']}/read", headers=owner)
    assert read.status_code == 200
    assert read.json()["read_at"] is not None

    cleared = client.patch(
        f"/api/v1/pantry/{pantry_id}",
        headers=owner,
        json={"expires_on": "2030-01-01"},
    )
    assert cleared.status_code == 200
    assert client.get("/api/v1/notifications", headers=owner).json() == []


def test_user_defined_low_stock_alert_and_durable_shopping_list_are_owner_scoped() -> None:
    owner = _headers("low-stock-owner", "low-stock-owner@example.com")
    other = _headers("low-stock-other", "low-stock-other@example.com")
    rice = client.post(
        "/api/v1/pantry",
        headers=owner,
        json={
            "name": "Rice",
            "quantity": 1,
            "unit": "kg",
            "low_stock_threshold": 1.5,
        },
    )
    assert rice.status_code == 201
    rice_id = rice.json()["id"]
    unconfigured = client.post(
        "/api/v1/pantry",
        headers=owner,
        json={"name": "Cumin", "quantity": 0.1, "unit": "kg"},
    )
    assert unconfigured.status_code == 201

    low_stock = client.get("/api/v1/pantry/low-stock", headers=owner)
    assert low_stock.status_code == 200
    assert [item["name"] for item in low_stock.json()["items"]] == ["Rice"]
    assert "does not infer" in low_stock.json()["limitation"]
    assert client.get("/api/v1/pantry/low-stock", headers=other).json()["items"] == []

    notifications = client.get("/api/v1/notifications", headers=owner).json()
    alert = next(item for item in notifications if item["kind"] == "PANTRY_LOW_STOCK")
    assert "1 kg" in alert["body"]
    assert "1.5 kg threshold" in alert["body"]

    generated = client.post("/api/v1/shopping-list/from-low-stock", headers=owner)
    assert generated.status_code == 200
    assert generated.json()["generated_count"] == 1
    shopping_item = generated.json()["items"][0]
    assert shopping_item["name"] == "Rice"
    assert shopping_item["source"] == "LOW_STOCK"
    assert shopping_item["quantity"] is None
    assert shopping_item["unit"] is None
    assert "Verify" in generated.json()["limitation"]

    repeated = client.post("/api/v1/shopping-list/from-low-stock", headers=owner)
    assert repeated.json()["generated_count"] == 0
    assert len(repeated.json()["items"]) == 1
    assert client.get("/api/v1/shopping-list", headers=other).json() == []

    checked = client.patch(
        f"/api/v1/shopping-list/{shopping_item['id']}",
        headers=owner,
        json={"checked": True},
    )
    assert checked.status_code == 200
    assert checked.json()["checked"] is True
    assert (
        client.patch(
            f"/api/v1/shopping-list/{shopping_item['id']}",
            headers=other,
            json={"checked": True},
        ).status_code
        == 404
    )

    replenished = client.patch(
        f"/api/v1/pantry/{rice_id}",
        headers=owner,
        json={"quantity": 2},
    )
    assert replenished.status_code == 200
    assert client.get("/api/v1/pantry/low-stock", headers=owner).json()["items"] == []
    assert client.get("/api/v1/shopping-list", headers=owner).json() == []
    assert not any(
        item["kind"] == "PANTRY_LOW_STOCK"
        for item in client.get("/api/v1/notifications", headers=owner).json()
    )


def test_manual_shopping_list_crud_and_account_export() -> None:
    owner = _headers("shopping-owner", "shopping-owner@example.com")
    created = client.post(
        "/api/v1/shopping-list",
        headers=owner,
        json={"name": "Lentils"},
    )
    assert created.status_code == 201
    item_id = created.json()["id"]
    assert created.json()["source"] == "USER_ADDED"

    renamed = client.patch(
        f"/api/v1/shopping-list/{item_id}",
        headers=owner,
        json={"name": "Red lentils"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Red lentils"
    assert (
        client.get("/api/v1/account/export", headers=owner).json()["shopping_list"][0]["name"]
        == "Red lentils"
    )
    assert client.delete(f"/api/v1/shopping-list/{item_id}", headers=owner).status_code == 204
    assert client.get("/api/v1/shopping-list", headers=owner).json() == []


def test_account_export_and_confirmed_deletion() -> None:
    headers = _headers("privacy-user", "privacy@example.com")
    client.post(
        "/api/v1/diary",
        headers=headers,
        json={"name": "Exported meal", "nutrients": {"calories": 210}},
    )
    exported = client.get("/api/v1/account/export", headers=headers)
    assert exported.status_code == 200
    assert exported.json()["diary"][0]["name"] == "Exported meal"

    rejected = client.request(
        "DELETE", "/api/v1/account", headers=headers, json={"confirmation": "NO"}
    )
    assert rejected.status_code == 422
    deleted = client.request(
        "DELETE", "/api/v1/account", headers=headers, json={"confirmation": "DELETE"}
    )
    assert deleted.status_code == 204
    assert client.get("/api/v1/profile", headers=headers).status_code == 401


def test_household_profiles_are_owner_scoped_manageable_and_exported() -> None:
    owner = _headers("household-owner", "household-owner@example.com")
    other = _headers("household-other", "household-other@example.com")
    payload = {
        "display_name": "Sam",
        "relationship": "Partner",
        "profile": {
            "goal": "low-sodium",
            "allergens": ["peanut"],
            "dietary_preferences": ["vegetarian"],
            "consent_personalization": False,
            "daily_targets": {"sodium_mg": 1800},
        },
    }

    created = client.post("/api/v1/profile/household", headers=owner, json=payload)
    assert created.status_code == 201
    profile_id = created.json()["id"]
    assert created.json()["display_name"] == "Sam"
    assert created.json()["profile"]["consent_personalization"] is False
    assert created.json()["created_at"] == created.json()["updated_at"]

    listed = client.get("/api/v1/profile/household", headers=owner)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [profile_id]
    assert client.get("/api/v1/profile/household", headers=other).json() == []

    updated_payload = {
        **payload,
        "display_name": "Samira",
        "profile": {**payload["profile"], "consent_personalization": True},
    }
    assert (
        client.put(
            f"/api/v1/profile/household/{profile_id}",
            headers=other,
            json=updated_payload,
        ).status_code
        == 404
    )
    updated = client.put(
        f"/api/v1/profile/household/{profile_id}",
        headers=owner,
        json=updated_payload,
    )
    assert updated.status_code == 200
    assert updated.json()["display_name"] == "Samira"
    assert updated.json()["created_at"] == created.json()["created_at"]
    assert updated.json()["profile"]["consent_personalization"] is True

    exported = client.get("/api/v1/account/export", headers=owner)
    assert exported.status_code == 200
    assert exported.json()["household_profiles"][0]["id"] == profile_id

    assert (
        client.delete(f"/api/v1/profile/household/{profile_id}", headers=other).status_code == 404
    )
    assert (
        client.delete(f"/api/v1/profile/household/{profile_id}", headers=owner).status_code == 204
    )
    assert client.get("/api/v1/profile/household", headers=owner).json() == []


def test_household_profile_rejects_blank_name_and_caps_members() -> None:
    headers = _headers("household-limit", "household-limit@example.com")
    assert (
        client.post(
            "/api/v1/profile/household", headers=headers, json={"display_name": "   "}
        ).status_code
        == 422
    )
    for index in range(10):
        response = client.post(
            "/api/v1/profile/household",
            headers=headers,
            json={"display_name": f"Member {index + 1}"},
        )
        assert response.status_code == 201
    capped = client.post(
        "/api/v1/profile/household",
        headers=headers,
        json={"display_name": "Member 11"},
    )
    assert capped.status_code == 409
    assert capped.json()["detail"] == "Household profile limit reached (10)."


def test_research_endpoint_requires_governed_role() -> None:
    headers = _headers("consumer-user", "consumer@example.com")

    assert client.get("/api/v1/research/aggregate", headers=headers).status_code == 403


def test_research_aggregate_suppresses_small_cohorts_and_returns_totals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.product_api as product_api

    researcher = User(
        id="researcher-user",
        google_subject="researcher-user",
        email="researcher@example.com",
        name="Researcher",
        avatar_url=None,
        plan=PlanCode.FREE,
        subscription_status=SubscriptionStatus.FREE,
        roles=frozenset({SpecialRole.RESEARCHER}),
    )
    app.dependency_overrides[current_user] = lambda: researcher
    try:
        monkeypatch.setattr(
            product_api.product_store,
            "research_summary",
            lambda: (4, 10, NutrientSnapshot(calories=1_000)),
        )
        suppressed = client.get("/api/v1/research/aggregate")
        assert suppressed.status_code == 200
        assert suppressed.json()["state"] == "INSUFFICIENT_COHORT"
        assert suppressed.json()["deidentified_user_count"] is None
        assert suppressed.json()["nutrient_totals"] is None

        monkeypatch.setattr(
            product_api.product_store,
            "research_summary",
            lambda: (20, 120, NutrientSnapshot(calories=24_000, protein_g=1_200)),
        )
        available = client.get("/api/v1/research/aggregate")
    finally:
        app.dependency_overrides.pop(current_user, None)

    assert available.status_code == 200
    assert available.json()["state"] == "AVAILABLE"
    assert available.json()["deidentified_user_count"] == 20
    assert available.json()["diary_entry_count"] is None
    assert available.json()["nutrient_totals"] is None


def test_in_memory_research_summary_aggregates_without_user_identifiers() -> None:
    store = ProductStore()
    for index in range(5):
        store.put_account_profile(
            f"aggregate-user-{index}",
            AccountProfileRecord(full_name=f"Participant {index}", research_insights_consent=True),
        )
        store.add_diary(
            f"aggregate-user-{index}",
            DiaryEntry(
                id=f"aggregate-entry-{index}",
                name="Synthetic meal",
                nutrients=NutrientSnapshot(calories=100, protein_g=10),
            ),
        )

    store.put_account_profile(
        "opted-out-user",
        AccountProfileRecord(full_name="Opted Out", research_insights_consent=False),
    )
    store.add_diary(
        "opted-out-user",
        DiaryEntry(
            id="opted-out-entry",
            name="Private meal",
            nutrients=NutrientSnapshot(calories=9_999, protein_g=999),
        ),
    )

    users, entries, totals = store.research_summary()
    assert (users, entries) == (5, 5)
    assert totals.calories == 500
    assert totals.protein_g == 50


def test_product_similarity_is_owner_scoped_bounded_and_entitlement_gated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.product_api as product_api

    def scan(scan_id: str, name: str, calories: str, protein: str) -> SimpleNamespace:
        return SimpleNamespace(
            scan_id=scan_id,
            product_name_candidates=[SimpleNamespace(value=name)],
            nutrition=SimpleNamespace(
                basis="PER_100_G",
                table_rows=[
                    SimpleNamespace(label="Energy", values=[calories]),
                    SimpleNamespace(label="Protein", values=[protein]),
                ],
            ),
        )

    target = scan("target", "Target oats", "380 kcal", "12 g")
    close = scan("close", "Similar oats", "370 kcal", "11 g")
    sparse = SimpleNamespace(
        scan_id="sparse",
        product_name_candidates=[SimpleNamespace(value="Sparse")],
        nutrition=SimpleNamespace(
            basis="PER_100_G",
            table_rows=[SimpleNamespace(label="Energy", values=["200 kcal"])],
        ),
    )
    monkeypatch.setattr(product_api, "get_owned_scan_result", lambda scan_id, user: target)
    monkeypatch.setattr(product_api, "_owned_scans", lambda user: [target, close, sparse])

    assert (
        client.get(
            "/api/v1/recommendations/similar/target",
            headers=_headers("similar-free", "similar-free@example.com"),
        ).status_code
        == 403
    )
    demo = User(
        id="similar-demo",
        google_subject="similar-demo",
        email="similar-demo@example.com",
        name="Similarity Demo",
        avatar_url=None,
        roles=frozenset({SpecialRole.DEMO}),
    )
    app.dependency_overrides[current_user] = lambda: demo
    try:
        response = client.get("/api/v1/recommendations/similar/target")
    finally:
        app.dependency_overrides.pop(current_user, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "AVAILABLE"
    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["scan_id"] == "close"
    assert payload["candidates"][0]["compared_nutrients"] == ["energy", "protein"]
    assert "not a health ranking" in payload["limitation"]


def test_recommendations_respect_consent_and_compare_owned_scan_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.product_api as product_api

    headers = _headers("comparison-user", "comparison@example.com")
    client.put(
        "/api/v1/profile",
        headers=headers,
        json={
            "goal": "low-sugar",
            "allergens": ["peanuts"],
            "dietary_preferences": [],
            "consent_personalization": False,
        },
    )
    scans = {
        "scan-a": SimpleNamespace(
            ingredients=IngredientExtraction(raw_text="sugar, glucose syrup, salt"),
            nutrition=NutritionExtraction(),
            product_name_candidates=[SimpleNamespace(value="Sugared sample")],
        ),
        "scan-b": SimpleNamespace(
            ingredients=IngredientExtraction(raw_text="oats"),
            nutrition=NutritionExtraction(),
            product_name_candidates=[SimpleNamespace(value="Oat sample")],
        ),
    }
    monkeypatch.setattr(
        product_api,
        "get_owned_scan_result",
        lambda scan_id, _user: scans[scan_id],
    )

    recommendation = client.get("/api/v1/recommendations/scans/scan-a", headers=headers)
    assert recommendation.status_code == 200
    assert recommendation.json()["profile_used"] is False
    assert recommendation.json()["personalization_state"] == "DISABLED_NO_CONSENT"

    client.put(
        "/api/v1/profile",
        headers=headers,
        json={
            "goal": "low-sugar",
            "allergens": [],
            "dietary_preferences": [],
            "consent_personalization": True,
        },
    )
    comparison = client.post(
        "/api/v1/recommendations/compare",
        headers=headers,
        json={"scan_ids": ["scan-a", "scan-b"]},
    )
    assert comparison.status_code == 200
    assert comparison.json()["method"] == "DETERMINISTIC_OBSERVED_SIGNAL_COMPARISON_V1"
    assert comparison.json()["candidates"][0]["scan_id"] == "scan-b"
    assert comparison.json()["recommended_scan_id"] == "scan-b"
    assert comparison.json()["profile_used"] is True
    assert any(
        "saved lower-sugar preference" in evidence
        for candidate in comparison.json()["candidates"]
        for evidence in candidate["evidence"]
    )
    assert "health score" in comparison.json()["disclaimer"]


def test_counterfactuals_ablate_only_observed_label_signal_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.product_api as product_api

    headers = _headers("counterfactual-user", "counterfactual@example.com")
    scans = {
        "observed": SimpleNamespace(
            ingredients=IngredientExtraction(raw_text="sugar, glucose syrup, salt"),
            nutrition=NutritionExtraction(),
        ),
        "plain": SimpleNamespace(
            ingredients=IngredientExtraction(raw_text="oats"),
            nutrition=NutritionExtraction(),
        ),
    }
    monkeypatch.setattr(
        product_api,
        "get_owned_scan_result",
        lambda scan_id, _user: scans[scan_id],
    )

    response = client.get("/api/v1/recommendations/scans/observed/counterfactuals", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "AVAILABLE"
    assert payload["scan_id"] == "observed"
    assert {item["factor_id"] for item in payload["factors"]} >= {
        "hidden-sugars",
        "sodium-sources",
    }
    assert all(
        item["method"] == "SINGLE_OBSERVED_SIGNAL_CATEGORY_ABLATION_V1"
        and "No other result is inferred" in item["result_change"]
        for item in payload["factors"]
    )
    assert "do not predict" in payload["limitation"]
    assert "health outcome" in payload["limitation"]

    no_signals = client.get("/api/v1/recommendations/scans/plain/counterfactuals", headers=headers)
    assert no_signals.status_code == 200
    assert no_signals.json()["state"] == "NO_OBSERVED_SIGNALS"
    assert no_signals.json()["factors"] == []


def test_compare_scans_detailed_nutrition_allergens_and_neutral_missing_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.product_api as product_api
    from ai.food_understanding.schemas import NutritionRow, NutritionValue

    headers = _headers("compare-user", "compare-user@example.com")
    scan1 = SimpleNamespace(
        ingredients=IngredientExtraction(raw_text="soy flour", allergen_text="Contains: Soy"),
        nutrition=NutritionExtraction(
            basis="PER_100_G",
            serving_size_value="50",
            serving_size_unit="g",
            table_rows=[
                NutritionRow(
                    label="Energy",
                    canonical_label="energy",
                    parsed_values=[NutritionValue(value="400", unit="kcal", basis="PER_100_G")],
                ),
                NutritionRow(
                    label="Protein",
                    canonical_label="protein",
                    parsed_values=[NutritionValue(value="10", unit="g", basis="PER_100_G")],
                ),
                NutritionRow(
                    label="Dietary Fiber",
                    canonical_label="dietary_fiber",
                    parsed_values=[NutritionValue(value="5", unit="g", basis="PER_100_G")],
                ),
            ],
        ),
        product_name_candidates=[SimpleNamespace(value="Soy Crisps")],
        brand_candidates=[SimpleNamespace(value="HealthySnack")],
    )
    scan2 = SimpleNamespace(
        ingredients=IngredientExtraction(raw_text="milk, sugar", allergen_text="Contains: Milk"),
        nutrition=NutritionExtraction(
            basis="PER_SERVING",
            serving_size_value="25",
            serving_size_unit="g",
            table_rows=[
                NutritionRow(
                    label="Energy",
                    canonical_label="energy",
                    parsed_values=[NutritionValue(value="100", unit="kcal", basis="PER_SERVING")],
                ),
                NutritionRow(
                    label="Protein",
                    canonical_label="protein",
                    parsed_values=[NutritionValue(value="2", unit="g", basis="PER_SERVING")],
                ),
                # Fiber is missing / not reported on label
            ],
        ),
        product_name_candidates=[SimpleNamespace(value="Milk Bar")],
        brand_candidates=[SimpleNamespace(value="SweetCo")],
    )
    monkeypatch.setattr(
        product_api,
        "get_owned_scan_result",
        lambda scan_id, _user: scan1 if scan_id == "s1" else scan2,
    )

    response = client.post(
        "/api/v1/recommendations/compare",
        headers=headers,
        json={"scan_ids": ["s1", "s2"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["candidates"]) == 2

    c1 = next(c for c in data["candidates"] if c["scan_id"] == "s1")
    c2 = next(c for c in data["candidates"] if c["scan_id"] == "s2")

    assert c1["product_name"] == "Soy Crisps"
    assert c1["brand_name"] == "HealthySnack"
    assert c1["serving_size"] == "50 g"
    assert c1["nutrients_per_100"]["energy_kcal"] == 400.0
    assert c1["nutrients_per_100"]["protein_g"] == 10.0
    assert c1["nutrients_per_serving"]["energy_kcal"] == 200.0  # normalized (50g / 100g * 400)
    assert c1["nutrients_per_serving"]["protein_g"] == 5.0
    assert c1["nutrients_per_100"]["fiber_g"] == 5.0
    assert c1["nutrients_per_serving"]["fiber_g"] == 2.5
    assert c1["allergens"] == ["soybeans"]

    assert c2["product_name"] == "Milk Bar"
    assert c2["brand_name"] == "SweetCo"
    assert c2["serving_size"] == "25 g"
    assert c2["nutrients_per_serving"]["energy_kcal"] == 100.0
    assert c2["nutrients_per_100"]["energy_kcal"] == 400.0  # normalized (100g / 25g * 100)
    assert c2["nutrients_per_serving"]["protein_g"] == 2.0
    assert c2["nutrients_per_100"]["protein_g"] == 8.0
    # Fiber is neutral None / missing (not 0)
    assert c2["nutrients_per_serving"]["fiber_g"] is None
    assert c2["nutrients_per_100"]["fiber_g"] is None
    assert c2["allergens"] == ["milk"]


def test_personal_fit_score_and_better_alternatives_filtering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify Personal Fit Score reasons and profile-filtered better alternatives."""
    import backend.product_api as product_api
    from ai.food_understanding.schemas import NutritionRow, NutritionValue

    headers = _headers("fit-score-user", "fit@example.com")

    # 1. User with Hypertension and Vegan dietary preference
    client.put(
        "/api/v1/profile",
        headers=headers,
        json={
            "goal": "low-sodium",
            "dietary_style": "Vegan",
            "health_conditions": ["Hypertension"],
            "allergens": ["dairy"],
            "consent_personalization": True,
        },
    )

    # Scanned high-sodium salty cheese snack
    high_sodium_snack = SimpleNamespace(
        ingredients=IngredientExtraction(raw_text="cheese, salt, milk solids"),
        nutrition=NutritionExtraction(
            table_rows=[
                NutritionRow(
                    label="Sodium",
                    canonical_label="sodium",
                    parsed_values=[NutritionValue(value="850", unit="mg", basis="PER_100_G")],
                )
            ]
        ),
        product_name_candidates=[SimpleNamespace(value="Salty Cheese Puff")],
        brand_candidates=[SimpleNamespace(value="SnackCo")],
    )

    monkeypatch.setattr(
        product_api,
        "get_owned_scan_result",
        lambda _scan_id, _user: high_sodium_snack,
    )

    resp = client.get("/api/v1/recommendations/scans/test-snack", headers=headers)
    assert resp.status_code == 200
    data = resp.json()

    # Fit score must reflect conflicts
    fit_score = data["fit_score"]
    assert fit_score["category"] in {"POOR_FIT", "MODERATE_FIT"}
    assert any("Dietary style" in r or "Animal" in r or "Vegan" in r for r in fit_score["reasons"])

    # Better alternatives must be provided and filtered for Vegan & Hypertension
    alternatives = data["better_alternatives"]
    assert len(alternatives) > 0
    # Greek yogurt contains dairy -> must be filtered out for Vegan/dairy allergen
    assert not any("Yogurt" in alt["name"] for alt in alternatives)
    # Roasted chickpeas (salt-free) is vegan and addresses Hypertension -> prioritized
    assert any("Chickpeas" in alt["name"] or "Oats" in alt["name"] for alt in alternatives)
