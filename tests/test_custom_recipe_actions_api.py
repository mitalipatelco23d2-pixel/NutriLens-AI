"""Generic recipe action contracts; all fixtures are synthetic, never production data."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from backend import custom_recipe_actions_api as actions
from backend import custom_recipes_api, product_api
from backend.auth import create_session_token, user_store
from backend.custom_recipes_api import CustomRecipeStore, RecipeCreate
from backend.main import app
from backend.postgres_store import PostgresStore

ROOT = "/api/v1/recipes/custom"


def recipe_input():
    return {
        "id": str(uuid4()),
        "name": "Synthetic mixed-unit recipe",
        "servings": 4,
        "ingredients": [
            {
                "name": "Red lentils",
                "quantity": 300,
                "unit": "g",
                "nutrients": {"calories": 120, "protein_g": 8, "sugar_g": 0},
            },
            {
                "name": "Water",
                "quantity": 600,
                "unit": "ml",
                "nutrients": {"calories": 0, "sugar_g": 0},
            },
        ],
    }


def consumption(**changes):
    return {
        "id": str(uuid4()),
        "expected_version": 1,
        "servings": 1.5,
        "eaten_at": datetime.now(UTC).isoformat(),
        **changes,
    }


def account():
    subject = f"recipe-action-{uuid4().hex}"
    user = user_store.upsert_google_user(
        {"sub": subject, "email": f"{subject}@example.invalid", "email_verified": True}
    )
    token, _ = create_session_token(user)
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def memory(monkeypatch):
    recipes = CustomRecipeStore()
    products = product_api.ProductStore()
    receipts = actions.RecipeActionStore()
    monkeypatch.setattr(custom_recipes_api, "custom_recipe_store", recipes)
    monkeypatch.setattr(product_api, "custom_recipe_store", recipes)
    monkeypatch.setattr(product_api, "product_store", products)
    monkeypatch.setattr(product_api, "postgres_store", None)
    monkeypatch.setattr(actions, "recipe_action_store", receipts)
    return recipes, products, receipts


def setup_recipe():
    client = TestClient(app)
    user, headers = account()
    payload = recipe_input()
    response = client.post(ROOT, headers=headers, json=payload)
    assert response.status_code == 201
    return client, user, headers, f"{ROOT}/{payload['id']}", payload


def test_consumption_snapshot_unknowns_zero_replay_edit_and_delete(memory):
    client, user, headers, path, recipe = setup_recipe()
    assert client.get("/api/v1/diary", headers=headers).json() == []
    payload = consumption()
    response = client.post(path + "/diary", headers=headers, json=payload)
    assert response.status_code == 201 and response.headers["cache-control"] == "no-store"
    entry = response.json()
    assert entry["source"] == "CUSTOM_RECIPE"
    assert entry["recipe_id"] == recipe["id"] and entry["recipe_version"] == 1
    assert entry["recipe_servings"] == 1.5 and entry["serving_grams"] is None
    assert entry["nutrients"]["calories"] == 45
    assert entry["nutrients"]["protein_g"] is None
    assert entry["nutrients"]["sugar_g"] == 0
    assert entry["nutrients"]["calcium_mg"] is None
    retry = client.post(path + "/diary", headers=headers, json=payload)
    assert retry.status_code == 200 and retry.json() == entry
    assert (
        client.post(path + "/diary", headers=headers, json=payload | {"servings": 2}).status_code
        == 409
    )
    assert len(client.get("/api/v1/diary", headers=headers).json()) == 1
    assert memory[1].list_pantry(user.id) == [] and memory[1].list_shopping_list(user.id) == []
    changed = {k: v for k, v in recipe.items() if k != "id"} | {
        "expected_version": 1,
        "name": "Edited later",
        "servings": 8,
    }
    assert client.put(path, headers=headers, json=changed).status_code == 200
    assert client.post(path + "/diary", headers=headers, json=consumption()).status_code == 409
    assert client.post(path + "/diary", headers=headers, json=payload).json() == entry
    assert client.delete(path, headers=headers, params={"expected_version": 2}).status_code == 204
    assert client.post(path + "/diary", headers=headers, json=payload).json() == entry
    assert client.delete(f"/api/v1/diary/{entry['id']}", headers=headers).status_code == 204
    assert client.post(path + "/diary", headers=headers, json=payload).status_code == 409
    assert client.get("/api/v1/diary", headers=headers).json() == []


def test_owner_isolation_authentication_and_no_client_nutrition_override(memory):
    client, _, headers, path, _ = setup_recipe()
    _, foreign = account()
    for suffix, body in [
        ("diary", consumption()),
        ("pantry-check", {"expected_version": 1, "servings": 1}),
        (
            "shopping-list",
            {
                "id": str(uuid4()),
                "expected_version": 1,
                "servings": 1,
                "ingredient_keys": ["a" * 24],
                "check_token": "a" * 64,
            },
        ),
    ]:
        assert client.post(path + "/" + suffix, json=body).status_code == 401
        assert client.post(path + "/" + suffix, headers=foreign, json=body).status_code == 404
    for extra in [{"user_id": "other"}, {"nutrients": {"calories": 999}}, {"source": "SCAN"}]:
        assert (
            client.post(path + "/diary", headers=headers, json=consumption() | extra).status_code
            == 422
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"servings": 0},
        {"servings": True},
        {"servings": "1"},
        {"servings": 1001},
        {"expected_version": True},
        {"eaten_at": "2026-01-02T12:00:00"},
        {"eaten_at": "1999-12-31T23:59:59Z"},
        {"eaten_at": (datetime.now(UTC) + timedelta(days=2)).isoformat()},
    ],
)
def test_invalid_consumption_is_rejected(memory, changes):
    client, _, headers, path, _ = setup_recipe()
    assert (
        client.post(path + "/diary", headers=headers, json=consumption(**changes)).status_code
        == 422
    )
    assert client.get("/api/v1/diary", headers=headers).json() == []


def test_check_groups_duplicate_rows_exact_names_units_and_excludes_leftovers_expiry(memory):
    recipes, products, _ = memory
    owner = "synthetic-owner"
    payload = recipe_input()
    payload["ingredients"] += [
        {"name": " RED   LENTILS ", "quantity": 100, "unit": "G"},
        {"name": "Salt", "quantity": 4, "unit": "g"},
    ]
    recipe, _ = recipes.create(owner, RecipeCreate.model_validate(payload))
    for item in [
        {"name": "red lentils", "quantity": 60, "unit": "g"},
        {"name": "red lentils", "quantity": 40, "unit": "g"},
        {"name": "red lentils soup", "quantity": 1000, "unit": "g"},
        {"name": "Water", "quantity": 1, "unit": "litre"},
        {"name": "Salt", "quantity": 10, "unit": "g", "item_role": "LEFTOVER"},
        {"name": "Salt", "quantity": 10, "unit": "g", "expires_on": "2000-01-01"},
    ]:
        products.add_pantry(owner, product_api.PantryItem(id=str(uuid4()), **item))
    before = [item.model_dump() for item in products.list_pantry(owner)]
    result = actions.check_pantry(recipe, 2, products.list_pantry(owner))
    assert len(result.ingredients) == 3
    lentils, water, salt = result.ingredients
    assert lentils.required_quantity == 200 and lentils.available_quantity == 100
    assert lentils.missing_quantity == 100 and lentils.status == "MISSING"
    assert water.status == "UNIT_MISMATCH" and water.missing_quantity is None
    assert water.available_quantity is None
    assert salt.status == "MISSING" and salt.missing_quantity == 2
    assert [item.model_dump() for item in products.list_pantry(owner)] == before
    assert products.diary == {} and products.shopping_list == {}


def test_explicit_shopping_selection_dedup_replay_and_no_resurrection(memory):
    client, user, headers, path, _ = setup_recipe()
    select = {"expected_version": 1, "servings": 2}
    check = client.post(path + "/pantry-check", headers=headers, json=select)
    assert check.status_code == 200 and check.headers["cache-control"] == "no-store"
    assert memory[1].list_shopping_list(user.id) == []
    key = check.json()["ingredients"][0]["key"]
    payload = select | {
        "id": str(uuid4()),
        "ingredient_keys": [key],
        "check_token": check.json()["check_token"],
    }
    created = client.post(path + "/shopping-list", headers=headers, json=payload)
    assert created.status_code == 201 and created.json()["generated_count"] == 1
    item = created.json()["items"][0]
    assert item["name"] == "Red lentils" and item["quantity"] == 150 and item["unit"] == "g"
    assert item["source"] == "RECIPE_PLAN"
    assert client.post(path + "/shopping-list", headers=headers, json=payload).status_code == 200
    assert (
        client.post(
            path + "/shopping-list", headers=headers, json=payload | {"id": str(uuid4())}
        ).json()["generated_count"]
        == 0
    )
    assert len(memory[1].list_shopping_list(user.id)) == 1
    assert client.delete(f"/api/v1/shopping-list/{item['id']}", headers=headers).status_code == 204
    assert client.post(path + "/shopping-list", headers=headers, json=payload).status_code == 409
    assert memory[1].list_shopping_list(user.id) == []
    assert client.get("/api/v1/diary", headers=headers).json() == []


def test_shopping_rechecks_stock_and_limit_is_all_or_nothing(memory):
    client, user, headers, path, _ = setup_recipe()
    check = client.post(
        path + "/pantry-check", headers=headers, json={"expected_version": 1, "servings": 1}
    ).json()
    payload = {
        "id": str(uuid4()),
        "expected_version": 1,
        "servings": 1,
        "ingredient_keys": [row["key"] for row in check["ingredients"]],
        "check_token": check["check_token"],
    }
    for i in range(199):
        memory[1].add_shopping_list_item(
            user.id, product_api.ShoppingListItem(id=str(uuid4()), name=f"Existing {i}")
        )
    assert client.post(path + "/shopping-list", headers=headers, json=payload).status_code == 409
    assert len(memory[1].list_shopping_list(user.id)) == 199
    assert (user.id, UUID(payload["id"])) not in memory[2].receipts
    memory[1].add_pantry(
        user.id, product_api.PantryItem(id=str(uuid4()), name="Water", quantity=1000, unit="ml")
    )
    assert client.post(path + "/shopping-list", headers=headers, json=payload).status_code == 409
    assert len(memory[1].list_shopping_list(user.id)) == 199


def test_receipt_ids_are_owner_scoped_and_cleared_with_account(memory):
    client, user, headers, path, recipe = setup_recipe()
    other, other_headers = account()
    assert client.post(ROOT, headers=other_headers, json=recipe).status_code == 201
    payload = consumption()
    first = client.post(path + "/diary", headers=headers, json=payload).json()
    second = client.post(path + "/diary", headers=other_headers, json=payload).json()
    assert first["id"] != second["id"]
    exported = client.get("/api/v1/account/export", headers=headers).json()
    assert exported["diary"] == [first]
    assert (
        client.request(
            "DELETE", "/api/v1/account", headers=headers, json={"confirmation": "DELETE"}
        ).status_code
        == 204
    )
    assert not any(key[0] == user.id for key in memory[2].receipts)
    assert any(key[0] == other.id for key in memory[2].receipts)


@pytest.fixture
def real_actions():
    url = os.environ.get("NUTRILENS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Explicit isolated test PostgreSQL URL required.")
    schema = f"recipe_actions_test_{uuid4().hex}"
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    test_url = make_conninfo(url, options=f"-c search_path={schema}")
    try:
        with psycopg.connect(test_url) as connection:
            for migration in [
                "001_v1_core.sql",
                "005_shopping_list.sql",
                "009_custom_recipes.sql",
                "010_custom_recipe_actions.sql",
                "011_account_profiles.sql",
            ]:
                connection.execute(Path("backend/migrations", migration).read_text())
            connection.execute(
                "INSERT INTO users (id,google_subject,email,display_name) VALUES "
                "('owner-a','a','a@example.invalid','A'), "
                "('owner-b','b','b@example.invalid','B')"
            )
            connection.execute(
                "INSERT INTO account_profiles (user_id,payload) VALUES "
                '(\'owner-a\',\'{"full_name":"A","research_insights_consent":true}\')'
            )
        db = PostgresStore(test_url)
        yield db, CustomRecipeStore(db), actions.RecipeActionStore(db)
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_real_transaction_concurrency_restart_isolation_deletion_cascade(real_actions):
    db, recipes, store = real_actions
    recipe, _ = recipes.create("owner-a", RecipeCreate.model_validate(recipe_input()))
    payload = actions.RecipeConsumption.model_validate(consumption())
    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(lambda _: store.consume("owner-a", recipe.id, payload), range(6)))
    assert sum(created for _, created in outcomes) == 1
    entry = outcomes[0][0]
    restarted = actions.RecipeActionStore(db)
    assert restarted.consume("owner-a", recipe.id, payload) == (entry, False)
    with pytest.raises(HTTPException) as denial:
        restarted.consume("owner-b", recipe.id, payload)
    assert denial.value.status_code == 404
    assert len(db.list_diary("owner-a", datetime.min.replace(tzinfo=UTC))) == 1
    assert db.list_diary("owner-b", datetime.min.replace(tzinfo=UTC)) == []
    users, count, totals = db.research_nutrition_summary()
    assert users == 1 and count == 1
    assert totals["calories"] == 45 and totals["protein_g"] is None
    assert totals["sugar_g"] == 0
    check = actions.check_pantry(recipe, 1, [])
    shopping = actions.RecipeShopping(
        id=uuid4(),
        expected_version=1,
        servings=1,
        ingredient_keys=[row.key for row in check.ingredients],
        check_token=check.check_token,
    )
    with ThreadPoolExecutor(max_workers=5) as pool:
        bought = list(pool.map(lambda _: restarted.shop("owner-a", recipe.id, shopping), range(5)))
    assert sum(created for _, created in bought) == 1 and len(db.list_shopping_list("owner-a")) == 2
    # A different action ID also cannot duplicate already-pending names.
    second = shopping.model_copy(update={"id": uuid4()})
    assert restarted.shop("owner-a", recipe.id, second)[0].generated_count == 0
    recipes.delete("owner-a", recipe.id, 1)
    assert restarted.consume("owner-a", recipe.id, payload)[1] is False
    assert db.delete_diary("owner-a", entry.id)
    with pytest.raises(HTTPException) as deleted:
        restarted.consume("owner-a", recipe.id, payload)
    assert deleted.value.status_code == 409
    with psycopg.connect(db.url) as connection:
        receipt = connection.execute(
            "SELECT result_ids FROM custom_recipe_actions WHERE user_id='owner-a' AND id=%s",
            (payload.id,),
        ).fetchone()
        assert receipt[0] == [entry.id]  # no deleted recipe/diary contents retained
        connection.execute("DELETE FROM users WHERE id='owner-a'")
        assert connection.execute("SELECT count(*) FROM custom_recipe_actions").fetchone()[0] == 0


def test_real_diary_insert_and_receipt_rollback_together(real_actions, monkeypatch):
    db, recipes, store = real_actions
    recipe, _ = recipes.create("owner-a", RecipeCreate.model_validate(recipe_input()))
    payload = actions.RecipeConsumption.model_validate(consumption())

    def fail_receipt(*_args, **_kwargs):
        raise RuntimeError("Synthetic receipt write failure")

    original = store.save_receipt
    monkeypatch.setattr(store, "save_receipt", fail_receipt)
    with pytest.raises(RuntimeError):
        store.consume("owner-a", recipe.id, payload)
    assert db.list_diary("owner-a", datetime.min.replace(tzinfo=UTC)) == []
    monkeypatch.setattr(store, "save_receipt", original)
    assert store.consume("owner-a", recipe.id, payload)[1] is True
