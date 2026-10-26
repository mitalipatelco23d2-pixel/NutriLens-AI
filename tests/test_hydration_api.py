import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from backend import hydration_api, product_api
from backend.auth import create_session_token, user_store
from backend.hydration_api import (
    HydrationConflict,
    HydrationCreate,
    HydrationStore,
    HydrationUpdate,
)
from backend.main import app
from backend.postgres_store import PostgresStore


@pytest.fixture
def store(monkeypatch):
    memory = HydrationStore()
    monkeypatch.setattr(hydration_api, "hydration_store", memory)
    monkeypatch.setattr(product_api, "hydration_store", memory)
    return memory


def owner():
    subject = f"water-{uuid4().hex}"
    user = user_store.upsert_google_user(
        {"sub": subject, "email": f"{subject}@example.com", "email_verified": True}
    )
    token, _ = create_session_token(user)
    return user, {"Authorization": f"Bearer {token}"}


def addition(amount=250, at="2026-01-15T10:00:00Z"):
    return {"id": str(uuid4()), "amount_ml": amount, "consumed_at": at}


def day(client, headers, selected="2026-01-15", **params):
    return client.get("/api/v1/hydration", headers=headers, params={"day": selected, **params})


def test_hydration_target_crud_history_export_and_account_deletion(store):
    user, headers = owner()
    client = TestClient(app)
    empty = day(client, headers).json()
    assert empty["target_ml"] is empty["remaining_ml"] is None
    assert empty["total_ml"] == 0 and empty["entries"] == []
    assert client.put(
        "/api/v1/hydration/target", headers=headers, json={"target_ml": 2000}
    ).json() == {"target_ml": 2000}
    payload = addition()
    created = client.post("/api/v1/hydration/entries", headers=headers, json=payload)
    assert created.status_code == 201
    assert created.json()["source"] == "USER_ENTERED"
    assert "user_id" not in created.json()
    assert created.headers["cache-control"] == "no-store"
    assert day(client, headers).json()["remaining_ml"] == 1750
    entry_path = f"/api/v1/hydration/entries/{payload['id']}"
    updated = client.put(
        entry_path,
        headers=headers,
        json={"amount_ml": 400, "consumed_at": "2026-01-14T12:00:00Z"},
    )
    assert updated.status_code == 200
    assert day(client, headers).json()["total_ml"] == 0
    assert day(client, headers, "2026-01-14").json()["total_ml"] == 400
    exported = client.get("/api/v1/account/export", headers=headers).json()["hydration"]
    assert exported == {"target_ml": 2000, "entries": [updated.json()]}
    assert client.delete(entry_path, headers=headers).status_code == 204
    assert store.entries(user.id) == []
    assert client.delete(entry_path, headers=headers).status_code == 404
    assert (
        client.post("/api/v1/hydration/entries", headers=headers, json=payload).status_code == 409
    )
    assert (
        client.put(
            "/api/v1/hydration/target", headers=headers, json={"target_ml": None}
        ).status_code
        == 200
    )
    assert day(client, headers).json()["target_ml"] is None
    client.post("/api/v1/hydration/entries", headers=headers, json=addition())
    assert (
        client.request(
            "DELETE", "/api/v1/account", headers=headers, json={"confirmation": "DELETE"}
        ).status_code
        == 204
    )
    assert store.export_user(user.id) == {"target_ml": None, "entries": []}
    assert all(key[0] != user.id for key in store._records)
    assert day(client, headers).status_code == 401


def test_duplicate_different_payload_and_owner_isolation(store):
    _, first = owner()
    _, second = owner()
    client = TestClient(app)
    payload = addition()
    first_result = client.post("/api/v1/hydration/entries", headers=first, json=payload)
    duplicate = client.post("/api/v1/hydration/entries", headers=first, json=payload)
    assert first_result.status_code == 201 and duplicate.status_code == 200
    assert first_result.json() == duplicate.json()
    assert day(client, first).json()["total_ml"] == 250
    assert (
        client.post(
            "/api/v1/hydration/entries", headers=first, json={**payload, "amount_ml": 500}
        ).status_code
        == 409
    )
    entry_path = f"/api/v1/hydration/entries/{payload['id']}"
    changed = {"amount_ml": 500, "consumed_at": payload["consumed_at"]}
    assert day(client, second).json()["entries"] == []
    assert client.put(entry_path, headers=second, json=changed).status_code == 404
    assert client.delete(entry_path, headers=second).status_code == 404
    assert client.put(entry_path, headers=first, json=changed).status_code == 200
    assert (
        client.post("/api/v1/hydration/entries", headers=first, json=payload).json()["amount_ml"]
        == 500
    )
    # Same UUID on another account has an independent retry namespace.
    assert client.post("/api/v1/hydration/entries", headers=second, json=payload).status_code == 201
    assert day(client, first).json()["total_ml"] == 500
    assert day(client, second).json()["total_ml"] == 250


@pytest.mark.parametrize(
    "offset, at, expected_day",
    [
        (330, "2026-01-14T18:30:00Z", "2026-01-15"),
        (-480, "2026-01-16T07:59:59Z", "2026-01-15"),
    ],
)
def test_daily_totals_use_client_local_day(store, offset, at, expected_day):
    _, headers = owner()
    client = TestClient(app)
    client.post("/api/v1/hydration/entries", headers=headers, json=addition(at=at))
    response = day(client, headers, expected_day, timezone_offset_minutes=offset)
    assert response.status_code == 200 and response.json()["total_ml"] == 250
    assert (
        day(client, headers, "2026-01-14", timezone_offset_minutes=offset).json()["total_ml"] == 0
    )


def test_dst_day_uses_next_midnight_offset_and_excludes_end_boundary(store):
    _, headers = owner()
    client = TestClient(app)
    for at in ["2026-03-08T04:59:59Z", "2026-03-08T05:00:00Z", "2026-03-09T04:00:00Z"]:
        client.post("/api/v1/hydration/entries", headers=headers, json=addition(at=at))
    response = day(
        client,
        headers,
        "2026-03-08",
        timezone_offset_minutes=-300,
        next_day_timezone_offset_minutes=-240,
    )
    assert response.json()["total_ml"] == 250
    assert (
        day(
            client,
            headers,
            "2026-03-08",
            timezone_offset_minutes=-300,
            next_day_timezone_offset_minutes=840,
        ).status_code
        == 422
    )


@pytest.mark.parametrize("amount", [0, -1, 5001, 1.5, True, "250"])
def test_rejects_invalid_or_coerced_amounts(store, amount):
    _, headers = owner()
    assert (
        TestClient(app)
        .post("/api/v1/hydration/entries", headers=headers, json=addition(amount))
        .status_code
        == 422
    )


@pytest.mark.parametrize(
    "payload", [{}, {"target_ml": 0}, {"target_ml": True}, {"target_ml": 10001}]
)
def test_target_must_be_explicit_and_bounded(store, payload):
    _, headers = owner()
    assert (
        TestClient(app).put("/api/v1/hydration/target", headers=headers, json=payload).status_code
        == 422
    )


@pytest.mark.parametrize(
    "at", ["2026-01-15T10:00:00", "2099-01-01T00:00:00Z", "1999-01-01T00:00:00Z"]
)
def test_rejects_naive_future_and_out_of_range_times(store, at):
    _, headers = owner()
    assert (
        TestClient(app)
        .post("/api/v1/hydration/entries", headers=headers, json=addition(at=at))
        .status_code
        == 422
    )


def test_unauthenticated_hydration_requests_denied(store):
    client = TestClient(app)
    for method, path, body in [
        ("GET", "/api/v1/hydration", None),
        ("PUT", "/api/v1/hydration/target", {"target_ml": 2000}),
        ("POST", "/api/v1/hydration/entries", addition()),
        ("DELETE", f"/api/v1/hydration/entries/{uuid4()}", None),
    ]:
        assert client.request(method, path, json=body).status_code == 401


@pytest.fixture
def real_store():
    url = os.environ.get("NUTRILENS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Set NUTRILENS_TEST_POSTGRES_URL explicitly for isolated real-DB tests.")
    schema = f"hydration_test_{uuid4().hex}"
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    test_url = make_conninfo(url, options=f"-c search_path={schema}")
    try:
        with psycopg.connect(test_url) as connection:
            connection.execute("CREATE TABLE users (id text PRIMARY KEY)")
            connection.execute(Path("backend/migrations/008_hydration.sql").read_text())
            connection.execute("INSERT INTO users VALUES ('owner-a'), ('owner-b')")
        yield HydrationStore(PostgresStore(test_url))
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_real_database_concurrency_persistence_isolation_and_deletion(real_store):
    payload = HydrationCreate.model_validate(addition())
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: real_store.create("owner-a", payload), range(4)))
    assert sum(created for _, created in outcomes) == 1
    restarted = HydrationStore(real_store.db)
    assert len(restarted.entries("owner-a")) == 1
    assert restarted.entries("owner-b") == []
    assert not restarted.delete("owner-b", payload.id)
    assert (
        restarted.replace(
            "owner-b", payload.id, HydrationUpdate(amount_ml=500, consumed_at=payload.consumed_at)
        )
        is None
    )
    restarted.save_target("owner-a", 2000)
    assert HydrationStore(real_store.db).target("owner-a") == 2000
    assert restarted.target("owner-b") is None
    assert (
        len(
            restarted.entries(
                "owner-a", datetime(2026, 1, 15, tzinfo=UTC), datetime(2026, 1, 16, tzinfo=UTC)
            )
        )
        == 1
    )
    assert restarted.delete("owner-a", payload.id)
    with pytest.raises(HydrationConflict):
        restarted.create("owner-a", payload)
    assert restarted.create("owner-b", payload)[1]
    # Existing canonical account deletion removes target, log and retry tombstone.
    with psycopg.connect(real_store.db.url) as connection:
        connection.execute("DELETE FROM users WHERE id = 'owner-a'")
        assert (
            connection.execute(
                "SELECT count(*) FROM hydration_entries WHERE user_id = 'owner-a'"
            ).fetchone()[0]
            == 0
        )
    assert restarted.target("owner-a") is None
    assert len(restarted.entries("owner-b")) == 1


def test_hydration_analytics_day_week_month_year_and_custom(store):
    user, headers = owner()
    client = TestClient(app)

    # Set target
    client.put("/api/v1/hydration/target", headers=headers, json={"target_ml": 2000})

    # Add entries for multiple days
    # Day 1: 2026-01-10 (1500 ml - below target)
    client.post(
        "/api/v1/hydration/entries",
        headers=headers,
        json=addition(1500, "2026-01-10T10:00:00Z"),
    )
    # Day 2: 2026-01-11 (2500 ml in 2 entries - above target)
    client.post(
        "/api/v1/hydration/entries",
        headers=headers,
        json=addition(1000, "2026-01-11T09:00:00Z"),
    )
    client.post(
        "/api/v1/hydration/entries",
        headers=headers,
        json=addition(1500, "2026-01-11T15:00:00Z"),
    )

    # Test DAY period
    day_res = client.get(
        "/api/v1/hydration/analytics",
        headers=headers,
        params={"period": "DAY", "day": "2026-01-11"},
    )
    assert day_res.status_code == 200
    day_data = day_res.json()
    assert day_data["period"] == "DAY"
    assert day_data["total_ml"] == 2500
    assert day_data["daily_average_ml"] == 2500
    assert day_data["target_ml"] == 2000
    assert day_data["days_target_met"] == 1
    assert day_data["total_days"] == 1
    assert day_data["attainment_rate_pct"] == 100.0
    assert len(day_data["buckets"]) == 12  # 12 2-hour buckets

    # Test WEEK period ending on 2026-01-11
    week_res = client.get(
        "/api/v1/hydration/analytics",
        headers=headers,
        params={"period": "WEEK", "day": "2026-01-11"},
    )
    assert week_res.status_code == 200
    week_data = week_res.json()
    assert week_data["period"] == "WEEK"
    assert week_data["total_ml"] == 4000  # 1500 + 2500
    assert week_data["total_days"] == 7
    assert week_data["daily_average_ml"] == round(4000 / 7)
    assert week_data["days_target_met"] == 1  # only 2026-01-11 met >= 2000
    assert len(week_data["buckets"]) == 7

    # Test MONTH period
    month_res = client.get(
        "/api/v1/hydration/analytics",
        headers=headers,
        params={"period": "MONTH", "day": "2026-01-11"},
    )
    assert month_res.status_code == 200
    month_data = month_res.json()
    assert month_data["period"] == "MONTH"
    assert month_data["total_days"] == 30
    assert len(month_data["buckets"]) == 30
    assert month_data["total_ml"] == 4000

    # Test YEAR period
    year_res = client.get(
        "/api/v1/hydration/analytics",
        headers=headers,
        params={"period": "YEAR", "day": "2026-01-11"},
    )
    assert year_res.status_code == 200
    year_data = year_res.json()
    assert year_data["period"] == "YEAR"
    assert year_data["total_ml"] == 4000

    # Test CUSTOM period
    custom_res = client.get(
        "/api/v1/hydration/analytics",
        headers=headers,
        params={
            "period": "CUSTOM",
            "start_date": "2026-01-10",
            "end_date": "2026-01-11",
        },
    )
    assert custom_res.status_code == 200
    custom_data = custom_res.json()
    assert custom_data["period"] == "CUSTOM"
    assert custom_data["total_days"] == 2
    assert custom_data["total_ml"] == 4000
    assert custom_data["daily_average_ml"] == 2000
    assert custom_data["days_target_met"] == 1
    assert custom_data["attainment_rate_pct"] == 50.0
    assert len(custom_data["buckets"]) == 2
