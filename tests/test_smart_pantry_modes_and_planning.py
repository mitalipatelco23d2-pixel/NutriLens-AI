"""Tests for smart pantry modes, deficit calculations, and recipe-to-shopping planning."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import product_api
from backend.auth import User, current_user
from backend.product_api import product_store


@pytest.fixture
def owner() -> User:
    return User("pantry-tester", None, "pantry@example.test", "Pantry Tester", None)


@pytest.fixture
def api(owner: User) -> TestClient:
    product_store.clear_user(owner.id)
    app = FastAPI()
    app.include_router(product_api.router)
    app.dependency_overrides[current_user] = lambda: owner
    return TestClient(app)


def test_smart_pantry_modes_and_ranking(api: TestClient, owner: User) -> None:
    today = datetime.now(UTC).date()
    # 1. Add pantry items
    # Dal (leftover)
    api.post(
        "/api/v1/pantry",
        json={"name": "Yellow Dal", "quantity": 100, "unit": "g", "item_role": "LEFTOVER"},
    )
    # Tomato (expiring soon)
    api.post(
        "/api/v1/pantry",
        json={
            "name": "Tomato",
            "quantity": 1,
            "unit": "unit",
            "expires_on": (today + timedelta(days=2)).isoformat(),
        },
    )
    # Onion
    api.post("/api/v1/pantry", json={"name": "Onion", "quantity": 1, "unit": "unit"})

    # Test mode COOK_WITH_WHAT_I_HAVE
    resp = api.get("/api/v1/recipes/recommendations?mode=COOK_WITH_WHAT_I_HAVE")
    assert resp.status_code == 200
    recs = resp.json()
    assert len(recs) >= 15
    # Dal Tadka needs dal, tomato, onion -> all 3 available -> top coverage
    top_recipe = recs[0]
    assert top_recipe["recipe_id"] in {
        "dal-tadka",
        "paneer-bhurji",
        "savory-oat-bowl",
        "masala-oats",
    }

    # Test mode USE_SELECTED_INGREDIENTS with selected_ingredients=paneer
    resp_selected = api.get(
        "/api/v1/recipes/recommendations?mode=USE_SELECTED_INGREDIENTS&selected_ingredients=paneer"
    )
    assert resp_selected.status_code == 200
    selected_recs = resp_selected.json()
    # Paneer recipes should be ranked at the very top
    assert any("paneer" in r["recipe_id"] for r in selected_recs[:3])

    # Test mode USE_EXPIRING_SOON
    resp_exp = api.get("/api/v1/recipes/recommendations?mode=USE_EXPIRING_SOON")
    assert resp_exp.status_code == 200
    exp_recs = resp_exp.json()
    # Recipes using Tomato (expiring) ranked highest
    assert any("tomato" in r["available_ingredients"] for r in exp_recs[:3])

    # Test mode USE_LEFTOVERS
    resp_lft = api.get("/api/v1/recipes/recommendations?mode=USE_LEFTOVERS")
    assert resp_lft.status_code == 200
    lft_recs = resp_lft.json()
    # Recipes using Dal (leftover) ranked highest
    assert any("dal" in r["available_ingredients"] for r in lft_recs[:3])


def test_recipe_deficits_and_unit_conversion(api: TestClient) -> None:
    # dal-tadka needs: dal 100g, tomato 1 unit, onion 1 unit
    # User has 40g dal, 1 tomato, 0 onion
    api.post("/api/v1/pantry", json={"name": "Dal", "quantity": 40, "unit": "g"})
    api.post("/api/v1/pantry", json={"name": "Tomato", "quantity": 1, "unit": "unit"})

    resp = api.get("/api/v1/recipes/recommendations")
    assert resp.status_code == 200
    dal_tadka = next(r for r in resp.json() if r["recipe_id"] == "dal-tadka")

    deficits_map = {d["ingredient"]: d for d in dal_tadka["deficits"]}
    # Dal: deficit of 60g
    assert deficits_map["dal"]["status"] == "DEFICIT"
    assert deficits_map["dal"]["available_quantity"] == 40.0
    assert deficits_map["dal"]["missing_quantity"] == 60.0
    assert deficits_map["dal"]["required_quantity"] == 100.0

    # Tomato: available (0 deficit)
    assert deficits_map["tomato"]["status"] == "AVAILABLE"
    assert deficits_map["tomato"]["missing_quantity"] == 0.0

    # Onion: missing
    assert deficits_map["onion"]["status"] == "MISSING"
    assert deficits_map["onion"]["missing_quantity"] == 1.0


def test_plan_template_recipe_to_shopping_list(api: TestClient, owner: User) -> None:
    # dal-tadka needs: dal 100g, tomato 1 unit, onion 1 unit (for 1 serving)
    # User has 50g dal, 0 tomato, 0 onion
    api.post("/api/v1/pantry", json={"name": "Dal", "quantity": 50, "unit": "g"})

    # Plan dal-tadka for 2 servings (requires 200g dal, 2 tomatoes, 2 onions)
    resp = api.post(
        "/api/v1/recipes/templates/dal-tadka/plan-to-shopping",
        json={"servings": 2.0},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["template_id"] == "dal-tadka"
    assert data["servings"] == 2.0
    assert data["generated_count"] >= 3

    # Check shopping list
    shopping_resp = api.get("/api/v1/shopping-list")
    assert shopping_resp.status_code == 200
    items = shopping_resp.json()
    item_map = {item["name"].lower(): item for item in items}

    # Dal needed: 200g - 50g = 150g deficit
    assert "dal" in item_map
    assert item_map["dal"]["quantity"] == 150.0
    assert item_map["dal"]["unit"] == "g"
    assert item_map["dal"]["source"] == "RECIPE_PLAN"
    assert item_map["dal"]["recipe_id"] == "dal-tadka"

    # Tomato needed: 2 units
    assert "tomato" in item_map
    assert item_map["tomato"]["quantity"] == 2.0
    assert item_map["tomato"]["unit"] == "unit"
    assert item_map["tomato"]["source"] == "RECIPE_PLAN"

    # Onion needed: 2 units
    assert "onion" in item_map
    assert item_map["onion"]["quantity"] == 2.0

    # Pantry stock must remain unchanged (planning does NOT subtract pantry)
    pantry_resp = api.get("/api/v1/pantry")
    dal_pantry = next(p for p in pantry_resp.json() if "dal" in p["name"].lower())
    assert dal_pantry["quantity"] == 50.0


def test_empty_pantry_returns_no_recipes_in_cook_with_what_i_have(
    api: TestClient, owner: User
) -> None:
    """When pantry is completely empty, COOK_WITH_WHAT_I_HAVE must return empty list."""
    product_store.clear_user(owner.id)
    resp = api.get("/api/v1/recipes/recommendations?mode=COOK_WITH_WHAT_I_HAVE")
    assert resp.status_code == 200
    assert resp.json() == []


def test_recipe_filtering_by_user_dietary_style_and_allergens(api: TestClient, owner: User) -> None:
    """Vegan user or user with dairy allergen should not receive paneer recipe recommendations."""
    product_store.clear_user(owner.id)
    # Add pantry items for paneer bhurji and dal tadka
    api.post("/api/v1/pantry", json={"name": "Paneer", "quantity": 200, "unit": "g"})
    api.post("/api/v1/pantry", json={"name": "Tomato", "quantity": 2, "unit": "unit"})
    api.post("/api/v1/pantry", json={"name": "Onion", "quantity": 2, "unit": "unit"})
    api.post("/api/v1/pantry", json={"name": "Dal", "quantity": 100, "unit": "g"})

    # Set profile to Vegan
    api.put("/api/v1/profile", json={"goal": "balanced", "dietary_style": "Vegan"})

    resp = api.get("/api/v1/recipes/recommendations")
    assert resp.status_code == 200
    recipes = resp.json()
    recipe_ids = [r["recipe_id"] for r in recipes]
    # Vegan must NOT receive paneer-bhurji or palak-paneer
    assert "paneer-bhurji" not in recipe_ids
    assert "palak-paneer" not in recipe_ids
    # But Dal Tadka is vegan and should be recommended
    assert "dal-tadka" in recipe_ids
