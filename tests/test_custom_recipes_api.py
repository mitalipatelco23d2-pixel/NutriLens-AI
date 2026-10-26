import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo
from pydantic import ValidationError

from backend import custom_recipes_api, product_api
from backend.auth import create_session_token, user_store
from backend.custom_recipes_api import CustomRecipeStore, RecipeConflict, RecipeCreate, RecipeUpdate
from backend.main import app
from backend.postgres_store import PostgresStore

ROOT = "/api/v1/recipes/custom"


@pytest.fixture
def store(monkeypatch):
    memory = CustomRecipeStore()
    monkeypatch.setattr(custom_recipes_api, "custom_recipe_store", memory)
    monkeypatch.setattr(product_api, "custom_recipe_store", memory)
    return memory


def owner():
    subject = f"recipe-{uuid4().hex}"
    user = user_store.upsert_google_user(
        {"sub": subject, "email": f"{subject}@example.invalid", "email_verified": True}
    )
    token, _ = create_session_token(user)
    return user, {"Authorization": f"Bearer {token}"}


def recipe_payload():
    return {
        "id": str(uuid4()),
        "name": "Saved recipe fixture",
        "servings": 2,
        "ingredients": [
            {
                "name": "Ingredient A",
                "quantity": 200,
                "unit": "g",
                "nutrients": {"calories": 80, "protein_g": 3, "sugar_g": 0},
                "source_label": "Entered label values for 200 g",
            },
            {
                "name": "Ingredient B",
                "quantity": 30,
                "unit": "ml",
                "nutrients": {"calories": 20, "sugar_g": 0},
            },
        ],
    }


def update_payload(payload, version=1, **changes):
    return {key: value for key, value in payload.items() if key != "id"} | {
        "expected_version": version,
        **changes,
    }


def test_recipe_crud_unknown_nutrition_export_and_no_automatic_consumption(store):
    user, headers = owner()
    client = TestClient(app)
    before_diary = client.get("/api/v1/diary", headers=headers).json()
    payload = recipe_payload()
    response = client.post(ROOT, headers=headers, json=payload)
    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    recipe = response.json()
    assert recipe["source"] == "USER_ENTERED" and "user_id" not in recipe
    assert recipe["version"] == 1
    assert recipe["per_serving"]["calories"] == 50  # listed quantities already have totals
    assert recipe["total_nutrients"]["protein_g"] is None  # ingredient B is unknown
    assert recipe["per_serving"]["sugar_g"] == 0  # explicitly supplied zero is known
    assert recipe["per_serving"]["sodium_mg"] is None
    path = f"{ROOT}/{payload['id']}"
    assert client.get(path, headers=headers).json() == recipe
    assert client.get(ROOT, headers=headers).json() == [recipe]
    edited = client.put(path, headers=headers, json=update_payload(payload, servings=4))
    assert edited.status_code == 200 and edited.json()["version"] == 2
    assert edited.json()["per_serving"]["calories"] == 25
    assert edited.json()["created_at"] == recipe["created_at"]
    assert client.get("/api/v1/diary", headers=headers).json() == before_diary
    exported = client.get("/api/v1/account/export", headers=headers).json()
    assert exported["custom_recipes"] == [edited.json()]
    assert client.delete(path, headers=headers, params={"expected_version": 2}).status_code == 204
    assert client.get(path, headers=headers).status_code == 404
    assert client.get(ROOT, headers=headers).json() == []
    assert store.export_user(user.id) == []
    assert client.post(ROOT, headers=headers, json=payload).status_code == 409


def test_idempotency_version_conflicts_and_owner_isolation(store):
    _, first = owner()
    _, second = owner()
    client = TestClient(app)
    payload = recipe_payload()
    initial = client.post(ROOT, headers=first, json=payload)
    retry = client.post(ROOT, headers=first, json=payload)
    assert retry.status_code == 200 and retry.json() == initial.json()
    assert client.post(ROOT, headers=first, json=payload | {"name": "Changed"}).status_code == 409
    path = f"{ROOT}/{payload['id']}"
    assert client.get(path, headers=second).status_code == 404
    assert client.get(ROOT, headers=second).json() == []
    assert client.put(path, headers=second, json=update_payload(payload)).status_code == 404
    assert client.delete(path, headers=second, params={"expected_version": 1}).status_code == 404
    assert (
        client.put(path, headers=first, json=update_payload(payload, name="Version 2")).status_code
        == 200
    )
    assert client.put(path, headers=first, json=update_payload(payload)).status_code == 409
    assert client.delete(path, headers=first, params={"expected_version": 1}).status_code == 409
    assert client.post(ROOT, headers=first, json=payload).json()["version"] == 2
    assert client.get(path, headers=first).json()["name"] == "Version 2"
    # A retry identifier is scoped to the canonical owner, not shared globally.
    assert client.post(ROOT, headers=second, json=payload).status_code == 201
    assert client.get(path, headers=second).json()["version"] == 1


def test_account_deletion_removes_recipe_and_retry_identities(store):
    user, headers = owner()
    client = TestClient(app)
    payload = recipe_payload()
    client.post(ROOT, headers=headers, json=payload)
    client.delete(f"{ROOT}/{payload['id']}", headers=headers, params={"expected_version": 1})
    client.post(ROOT, headers=headers, json=recipe_payload())
    assert (
        client.request(
            "DELETE", "/api/v1/account", headers=headers, json={"confirmation": "DELETE"}
        ).status_code
        == 204
    )
    assert not any(key[0] == user.id for key in store.records)
    assert client.get(ROOT, headers=headers).status_code == 401


@pytest.mark.parametrize("servings", [0, -1, 1001, True, "2", 1e-320])
def test_invalid_yields_rejected(store, servings):
    _, headers = owner()
    assert (
        TestClient(app)
        .post(ROOT, headers=headers, json=recipe_payload() | {"servings": servings})
        .status_code
        == 422
    )


@pytest.mark.parametrize("nutrient", [-1, True, "50", 1_000_001, float("inf"), float("nan")])
def test_invalid_nutrients_rejected(nutrient):
    payload = recipe_payload()
    payload["ingredients"][0]["nutrients"]["calories"] = nutrient
    with pytest.raises(ValidationError):
        RecipeCreate.model_validate(payload)


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "   "},
        {"ingredients": []},
        {"ingredients": [{"name": "Water", "quantity": True, "unit": "ml"}]},
        {"ingredients": [{"name": "Water", "quantity": 1, "unit": " "}]},
        {"ingredients": [{"name": "Water", "quantity": 1, "unit": "ml", "source_label": " "}]},
        {"source": "SCIENTIFICALLY_VALIDATED"},
    ],
)
def test_bounded_fields_no_arbitrary_provenance(changes):
    with pytest.raises(ValidationError):
        RecipeCreate.model_validate(recipe_payload() | changes)


def test_unauthenticated_access_and_bounded_pagination(store):
    client = TestClient(app)
    path = f"{ROOT}/{uuid4()}"
    for method, url, body in [
        ("GET", ROOT, None),
        ("GET", path, None),
        ("POST", ROOT, recipe_payload()),
        ("PUT", path, update_payload(recipe_payload())),
        ("DELETE", path + "?expected_version=1", None),
    ]:
        assert client.request(method, url, json=body).status_code == 401
    _, headers = owner()
    for params in [{"limit": 201}, {"limit": 0}, {"offset": -1}]:
        assert client.get(ROOT, headers=headers, params=params).status_code == 422
    for _ in range(3):
        client.post(ROOT, headers=headers, json=recipe_payload())
    first = client.get(ROOT, headers=headers, params={"limit": 2}).json()
    second = client.get(ROOT, headers=headers, params={"limit": 2, "offset": 2}).json()
    assert len(first) == 2 and len(second) == 1
    assert len({r["id"] for r in first + second}) == 3


@pytest.fixture
def real_store():
    url = os.environ.get("NUTRILENS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Explicit isolated test PostgreSQL URL required.")
    schema = f"recipes_test_{uuid4().hex}"
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    test_url = make_conninfo(url, options=f"-c search_path={schema}")
    try:
        with psycopg.connect(test_url) as connection:
            connection.execute("CREATE TABLE users (id text PRIMARY KEY)")
            connection.execute(Path("backend/migrations/009_custom_recipes.sql").read_text())
            connection.execute("INSERT INTO users VALUES ('recipe-owner-a'), ('recipe-owner-b')")
        yield CustomRecipeStore(PostgresStore(test_url))
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_real_database_concurrency_restart_isolation_versions_and_cascade(real_store):
    payload = RecipeCreate.model_validate(recipe_payload())
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: real_store.create("recipe-owner-a", payload), range(4)))
    assert sum(created for _, created in outcomes) == 1
    restarted = CustomRecipeStore(real_store.db)
    assert len(restarted.list_recipes("recipe-owner-a")) == 1
    assert restarted.list_recipes("recipe-owner-b") == []
    assert restarted.get("recipe-owner-b", payload.id) is None
    changed = RecipeUpdate.model_validate(update_payload(payload.model_dump(), name="Updated"))
    assert restarted.replace("recipe-owner-b", payload.id, changed) is None

    def edit(_):
        try:
            return restarted.replace("recipe-owner-a", payload.id, changed)
        except RecipeConflict:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        edits = list(pool.map(edit, range(4)))
    assert sum(item is not None for item in edits) == 1
    assert CustomRecipeStore(real_store.db).get("recipe-owner-a", payload.id).version == 2
    with pytest.raises(RecipeConflict):
        restarted.delete("recipe-owner-a", payload.id, 1)
    assert restarted.delete("recipe-owner-a", payload.id, 2)
    with pytest.raises(RecipeConflict):
        restarted.create("recipe-owner-a", payload)
    assert restarted.create("recipe-owner-b", payload)[1]
    with psycopg.connect(real_store.db.url) as connection:
        connection.execute("DELETE FROM users WHERE id = 'recipe-owner-a'")
        assert (
            connection.execute(
                "SELECT count(*) FROM custom_recipes WHERE user_id = 'recipe-owner-a'"
            ).fetchone()[0]
            == 0
        )
    assert len(restarted.list_recipes("recipe-owner-b")) == 1
