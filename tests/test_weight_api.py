import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from backend import product_api, weight_api
from backend.auth import create_session_token, user_store
from backend.main import app
from backend.postgres_store import PostgresStore
from backend.weight_api import WeightConflict, WeightCreate, WeightStore, WeightUpdate


@pytest.fixture
def store(monkeypatch):
    memory = WeightStore()
    monkeypatch.setattr(weight_api, "weight_store", memory)
    monkeypatch.setattr(product_api, "weight_store", memory)
    return memory


def owner():
    subject = f"weight-{uuid4().hex}"
    user = user_store.upsert_google_user(
        {"sub": subject, "email": f"{subject}@example.com", "email_verified": True}
    )
    token, _ = create_session_token(user)
    return user, {"Authorization": f"Bearer {token}"}


def addition(weight=70.0, at="2026-01-15T10:00:00Z"):
    return {"id": str(uuid4()), "weight_kg": weight, "recorded_at": at}


def test_weight_tracking_requires_enablement_and_reports_descriptive_change(store):
    user, headers = owner()
    client = TestClient(app)
    empty = client.get("/api/v1/weight", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["state"] == "DISABLED"
    assert empty.json()["entries"] == []
    assert "ideal weight" in empty.json()["limitation"]
    assert (
        client.post("/api/v1/weight/entries", headers=headers, json=addition()).status_code == 409
    )

    configured = client.put(
        "/api/v1/weight/settings",
        headers=headers,
        json={"target_weight_kg": 68.5},
    )
    assert configured.json() == {"state": "ACTIVE", "target_weight_kg": 68.5}
    first = addition(70.0, "2026-01-14T10:00:00Z")
    second = addition(69.25, "2026-01-15T10:00:00Z")
    assert client.post("/api/v1/weight/entries", headers=headers, json=first).status_code == 201
    created = client.post("/api/v1/weight/entries", headers=headers, json=second)
    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    assert "user_id" not in created.json()

    summary = client.get("/api/v1/weight", headers=headers).json()
    assert summary["latest_weight_kg"] == 69.25
    assert summary["change_from_first_kg"] == -0.75
    assert summary["difference_from_target_kg"] == 0.75
    assert [entry["id"] for entry in summary["entries"]] == [second["id"], first["id"]]

    exported = client.get("/api/v1/account/export", headers=headers).json()["weight"]
    assert exported["state"] == "ACTIVE"
    assert len(exported["entries"]) == 2

    entry_path = f"/api/v1/weight/entries/{second['id']}"
    updated = client.put(
        entry_path,
        headers=headers,
        json={"weight_kg": 69.0, "recorded_at": second["recorded_at"]},
    )
    assert updated.status_code == 200
    assert updated.json()["weight_kg"] == 69.0
    assert client.delete(entry_path, headers=headers).status_code == 204
    assert client.delete(entry_path, headers=headers).status_code == 404

    assert client.delete("/api/v1/weight/settings", headers=headers).status_code == 204
    assert store.export_user(user.id) == {
        "state": "DISABLED",
        "target_weight_kg": None,
        "entries": [],
    }


def test_weight_retry_identity_owner_isolation_and_account_deletion(store):
    user, first_owner = owner()
    _, other_owner = owner()
    client = TestClient(app)
    for headers in (first_owner, other_owner):
        assert (
            client.put(
                "/api/v1/weight/settings", headers=headers, json={"target_weight_kg": None}
            ).status_code
            == 200
        )
    payload = addition()
    first = client.post("/api/v1/weight/entries", headers=first_owner, json=payload)
    retry = client.post("/api/v1/weight/entries", headers=first_owner, json=payload)
    assert first.status_code == 201 and retry.status_code == 200
    assert first.json() == retry.json()
    assert (
        client.post(
            "/api/v1/weight/entries",
            headers=first_owner,
            json={**payload, "weight_kg": 71.0},
        ).status_code
        == 409
    )

    entry_path = f"/api/v1/weight/entries/{payload['id']}"
    changed = {"weight_kg": 71.0, "recorded_at": payload["recorded_at"]}
    assert client.get("/api/v1/weight", headers=other_owner).json()["entries"] == []
    assert client.put(entry_path, headers=other_owner, json=changed).status_code == 404
    assert client.delete(entry_path, headers=other_owner).status_code == 404
    assert (
        client.post("/api/v1/weight/entries", headers=other_owner, json=payload).status_code == 201
    )

    assert (
        client.request(
            "DELETE", "/api/v1/account", headers=first_owner, json={"confirmation": "DELETE"}
        ).status_code
        == 204
    )
    assert store.export_user(user.id)["state"] == "DISABLED"
    assert client.get("/api/v1/weight", headers=first_owner).status_code == 401
    assert len(client.get("/api/v1/weight", headers=other_owner).json()["entries"]) == 1


@pytest.mark.parametrize("weight", [0, 19.99, 500.01, True, "70"])
def test_weight_values_are_numeric_and_bounded(store, weight):
    _, headers = owner()
    client = TestClient(app)
    client.put("/api/v1/weight/settings", headers=headers, json={"target_weight_kg": None})
    assert (
        client.post(
            "/api/v1/weight/entries", headers=headers, json=addition(weight=weight)
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "at", ["2026-01-15T10:00:00", "2099-01-01T00:00:00Z", "1999-01-01T00:00:00Z"]
)
def test_weight_time_must_be_aware_and_bounded(store, at):
    _, headers = owner()
    client = TestClient(app)
    client.put("/api/v1/weight/settings", headers=headers, json={"target_weight_kg": None})
    assert (
        client.post("/api/v1/weight/entries", headers=headers, json=addition(at=at)).status_code
        == 422
    )


def test_unauthenticated_weight_requests_are_denied(store):
    client = TestClient(app)
    for method, path, body in (
        ("GET", "/api/v1/weight", None),
        ("PUT", "/api/v1/weight/settings", {"target_weight_kg": None}),
        ("DELETE", "/api/v1/weight/settings", None),
        ("POST", "/api/v1/weight/entries", addition()),
    ):
        assert client.request(method, path, json=body).status_code == 401


@pytest.fixture
def real_store():
    url = os.environ.get("NUTRILENS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set NUTRILENS_TEST_POSTGRES_URL explicitly for isolated real-DB tests.")
    schema = f"weight_test_{uuid4().hex}"
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    test_url = make_conninfo(url, options=f"-c search_path={schema}")
    try:
        with psycopg.connect(test_url) as connection:
            connection.execute("CREATE TABLE users (id text PRIMARY KEY)")
            connection.execute(Path("backend/migrations/013_weight_tracking.sql").read_text())
            connection.execute("INSERT INTO users VALUES ('owner-a'), ('owner-b')")
        yield WeightStore(PostgresStore(test_url))
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_real_database_weight_concurrency_persistence_and_cascade(real_store):
    real_store.enable("owner-a", 68.5)
    payload = WeightCreate.model_validate(addition())
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: real_store.create("owner-a", payload), range(4)))
    assert sum(created for _, created in outcomes) == 1
    restarted = WeightStore(real_store.db)
    assert restarted.settings("owner-a").target_weight_kg == 68.5
    assert len(restarted.entries("owner-a")) == 1
    assert restarted.entries("owner-b") == []
    assert not restarted.delete("owner-b", payload.id)
    assert (
        restarted.replace(
            "owner-b",
            payload.id,
            WeightUpdate(weight_kg=71.0, recorded_at=payload.recorded_at),
        )
        is None
    )
    assert restarted.delete("owner-a", payload.id)
    with pytest.raises(WeightConflict):
        restarted.create("owner-a", payload)
    with psycopg.connect(real_store.db.url) as connection:
        connection.execute("DELETE FROM users WHERE id = 'owner-a'")
        assert (
            connection.execute(
                "SELECT count(*) FROM weight_entries WHERE user_id = 'owner-a'"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM weight_settings WHERE user_id = 'owner-a'"
            ).fetchone()[0]
            == 0
        )
