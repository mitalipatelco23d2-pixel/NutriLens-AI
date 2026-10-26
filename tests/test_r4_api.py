from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_r4_api_returns_governed_unknown_states_and_provenance() -> None:
    response = client.post(
        "/api/v1/ingredient-intelligence/analyze",
        json={"raw_text": "Ingredients: definitely unknown"},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["nova"]["classification_method"] == "UNKNOWN"
    assert result["complexity"]["unresolved_count"] == 1
    assert result["confidence"]["state"] == "LOW"
    assert result["confidence"]["method"] == "DETERMINISTIC_TAXONOMY"


def test_r4_api_parses_compounds_and_detects_taxonomy_signals() -> None:
    response = client.post(
        "/api/v1/ingredient-intelligence/analyze",
        json={"raw_text": ("Ingredients: chocolate (sucrose, cocoa butter), salt, maltodextrin")},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["complexity"]["compound_ingredient_count"] == 2
    assert result["hidden_sugars"]["signals"][0]["ingredient_text"] == "sucrose"
    assert result["sodium_sources"]["signals"][0]["ingredient_text"] == "salt"
    assert result["nova"]["group_number"] == 4
