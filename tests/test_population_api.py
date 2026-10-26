import gzip
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend.auth import create_session_token, user_store
from backend.main import app

client = TestClient(app)


def _headers() -> dict[str, str]:
    user = user_store.upsert_google_user(
        {
            "sub": "population-user",
            "email": "population@example.com",
            "email_verified": True,
            "name": "Population Researcher",
        }
    )
    token, _ = create_session_token(user)
    return {"Authorization": f"Bearer {token}"}


def _bundle() -> dict[str, Any]:
    with gzip.open(
        Path("data/runtime/faostat-country-indicators-v0.1.0.json.gz"),
        "rt",
        encoding="utf-8",
    ) as stream:
        payload: dict[str, Any] = json.load(stream)
    return payload


def test_runtime_bundle_has_governed_provenance_and_expected_coverage() -> None:
    payload = _bundle()
    assert payload["schema_version"] == "0.1.0"
    assert payload["source"]["license"].startswith("CC BY 4.0")
    assert payload["source"]["raw_csv_sha256"]
    assert len({record["m49_code"] for record in payload["records"]}) >= 150
    assert max(record["year"] for record in payload["records"]) == 2023
    assert any(record["m49_code"] == "356" for record in payload["records"])


def test_population_endpoints_require_authentication() -> None:
    assert client.get("/api/v1/population/countries").status_code == 401
    assert (
        client.post(
            "/api/v1/population/compare",
            json={"m49_codes": ["356", "840"], "year": 2023},
        ).status_code
        == 401
    )


def test_country_comparison_preserves_values_flags_and_limitations() -> None:
    headers = _headers()
    catalog = client.get("/api/v1/population/countries", headers=headers)
    assert catalog.status_code == 200
    assert catalog.json()["latest_year"] == 2023
    assert any(country["m49_code"] == "356" for country in catalog.json()["countries"])

    response = client.post(
        "/api/v1/population/compare",
        headers=headers,
        json={"m49_codes": ["356", "840"], "year": 2023},
    )
    assert response.status_code == 200
    payload = response.json()
    expected = {
        record["m49_code"]: record
        for record in _bundle()["records"]
        if record["year"] == 2023 and record["m49_code"] in {"356", "840"}
    }
    assert payload["records"] == [expected["356"], expected["840"]]
    assert "not measured individual intake" in payload["limitations"][0]
    assert "rank" in payload["limitations"][2]
    assert "rank" not in payload["records"][0]
    assert payload["source"]["citation"].startswith("FAO. 2025.")


def test_country_comparison_rejects_duplicate_and_unknown_selections() -> None:
    headers = _headers()
    duplicate = client.post(
        "/api/v1/population/compare",
        headers=headers,
        json={"m49_codes": ["356", "356"]},
    )
    assert duplicate.status_code == 422
    unknown = client.post(
        "/api/v1/population/compare",
        headers=headers,
        json={"m49_codes": ["356", "999"], "year": 2023},
    )
    assert unknown.status_code == 404


def test_country_trend_returns_bounded_source_points_without_forecast() -> None:
    response = client.post(
        "/api/v1/population/trends",
        headers=_headers(),
        json={
            "m49_codes": ["356", "840"],
            "indicator": "protein_supply_g_per_capita_day",
            "first_year": 2020,
            "latest_year": 2023,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["unit"] == "g/capita/day"
    assert [point["year"] for point in payload["series"][0]["points"]] == [
        2020,
        2021,
        2022,
        2023,
    ]
    assert all(
        "quality_flag" in point for series in payload["series"] for point in series["points"]
    )
    assert "forecast" not in payload
    assert "does not estimate a trend" in payload["limitations"][-1]


def test_country_trend_rejects_invalid_ranges_and_duplicates() -> None:
    headers = _headers()
    invalid_range = client.post(
        "/api/v1/population/trends",
        headers=headers,
        json={
            "m49_codes": ["356"],
            "indicator": "fat_supply_g_per_capita_day",
            "first_year": 2023,
            "latest_year": 2020,
        },
    )
    assert invalid_range.status_code == 422
    duplicate = client.post(
        "/api/v1/population/trends",
        headers=headers,
        json={
            "m49_codes": ["356", "356"],
            "indicator": "food_supply_kcal_per_capita_day",
        },
    )
    assert duplicate.status_code == 422
