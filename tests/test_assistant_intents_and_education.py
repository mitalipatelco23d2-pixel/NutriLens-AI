"""Tests for deterministic intent routing, atomic quota reservation, and nutrition education."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import product_api
from backend.auth import User, current_user
from backend.product_api import _detect_assistant_intent, product_store


@pytest.fixture
def owner() -> User:
    return User("edu-owner", None, "edu@example.test", "Edu Owner", None)


@pytest.fixture
def api(owner: User) -> TestClient:
    product_store.clear_user(owner.id)
    # Reset any assistant usage
    for key in list(product_store.assistant_usage.keys()):
        if key[0] == owner.id:
            del product_store.assistant_usage[key]
    app = FastAPI()
    app.include_router(product_api.router)
    app.dependency_overrides[current_user] = lambda: owner
    return TestClient(app)


def test_detect_assistant_intent_deterministic_routing() -> None:
    # 1. OUT_OF_SCOPE
    assert _detect_assistant_intent("What disease will protein cure?") == "OUT_OF_SCOPE"
    assert _detect_assistant_intent("Can this diagnose diabetes?") == "OUT_OF_SCOPE"
    assert _detect_assistant_intent("Prescribe medicine for high cholesterol") == "OUT_OF_SCOPE"

    # 2. CURRENT_SCAN_ALLERGEN
    assert _detect_assistant_intent("Does this contain milk?", scan=None) == "CURRENT_SCAN_ALLERGEN"
    assert (
        _detect_assistant_intent("Is this scan free from peanuts?", scan=None)
        == "CURRENT_SCAN_ALLERGEN"
    )
    assert (
        _detect_assistant_intent("Is this safe for nut allergy?", scan=None)
        == "CURRENT_SCAN_ALLERGEN"
    )

    # 3. CURRENT_SCAN_INGREDIENT
    assert (
        _detect_assistant_intent("What are the ingredients in this?", scan=None)
        == "CURRENT_SCAN_INGREDIENT"
    )
    assert (
        _detect_assistant_intent("Does this package have additives?", scan=None)
        == "CURRENT_SCAN_INGREDIENT"
    )

    # 4. CURRENT_SCAN_NUTRITION
    assert (
        _detect_assistant_intent("How much protein is in this milk?", scan=None)
        == "CURRENT_SCAN_NUTRITION"
    )
    assert _detect_assistant_intent("Explain this scan", scan=None) == "CURRENT_SCAN_NUTRITION"

    # 5. COMPARE_FOODS
    assert _detect_assistant_intent("Compare these two foods") == "COMPARE_FOODS"
    assert (
        _detect_assistant_intent("Which has more protein between milk and yogurt?")
        == "COMPARE_FOODS"
    )

    # 6. DIARY_CONTEXT
    assert _detect_assistant_intent("What did I eat today?") == "DIARY_CONTEXT"
    assert _detect_assistant_intent("Check my diary intake today") == "DIARY_CONTEXT"

    # 7. PANTRY_CONTEXT
    assert _detect_assistant_intent("What can I cook with my pantry?") == "PANTRY_CONTEXT"
    assert _detect_assistant_intent("What ingredients do I have in my pantry?") == "PANTRY_CONTEXT"

    # 8. USER_GOAL_CONTEXT
    assert _detect_assistant_intent("What is my nutrition goal?") == "USER_GOAL_CONTEXT"
    assert _detect_assistant_intent("Am I on track with my daily goal?") == "USER_GOAL_CONTEXT"

    # 9. GENERAL_NUTRITION_EDUCATION
    assert _detect_assistant_intent("What does protein do?") == "GENERAL_NUTRITION_EDUCATION"
    assert _detect_assistant_intent("why is protein needed") == "GENERAL_NUTRITION_EDUCATION"
    assert (
        _detect_assistant_intent("How should I read a nutrition label?")
        == "GENERAL_NUTRITION_EDUCATION"
    )
    assert _detect_assistant_intent("What does per serving mean?") == "GENERAL_NUTRITION_EDUCATION"
    assert _detect_assistant_intent("What is added sugar?") == "GENERAL_NUTRITION_EDUCATION"


def test_five_exact_owner_queries_return_governed_answers(api: TestClient) -> None:
    queries_and_keywords = [
        ("why is protein needed", "Protein", "NIH"),
        ("What does protein do?", "Protein", "NIH"),
        ("How should I read a nutrition label?", "serving size", "FDA"),
        ("What does per serving mean?", "Serving size", "FDA"),
        ("What is added sugar?", "Added sugars", "FDA"),
    ]

    for question, expected_keyword, expected_authority in queries_and_keywords:
        resp = api.post("/api/v1/assistant/messages", json={"message": question})
        assert resp.status_code == 200, f"Query '{question}' failed with {resp.text}"
        data = resp.json()
        assert expected_keyword.lower() in data["answer"].lower()
        assert any(expected_authority.lower() in c["authority"].lower() for c in data["citations"])
        assert data["remaining_today"] >= 0


def test_out_of_scope_releases_quota(api: TestClient, owner: User) -> None:
    today = datetime.now(UTC).date()
    initial_used = product_store.read_assistant_usage(owner.id, today)

    resp = api.post(
        "/api/v1/assistant/messages", json={"message": "What medicine will cure diabetes?"}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["generation_mode"] == "CLINICAL_BOUNDARY_SAFEGUARD"
    assert "not clinical diagnoses" in data["answer"]

    # Quota released
    final_used = product_store.read_assistant_usage(owner.id, today)
    assert final_used == initial_used


def test_diary_and_pantry_context_intents(api: TestClient, owner: User) -> None:
    # Empty diary
    resp_diary = api.post("/api/v1/assistant/messages", json={"message": "What did I eat today?"})
    assert resp_diary.status_code == 200
    assert "haven't logged any foods" in resp_diary.json()["answer"]

    # Empty pantry
    resp_pantry = api.post(
        "/api/v1/assistant/messages", json={"message": "What can I cook with my pantry?"}
    )
    assert resp_pantry.status_code == 200
    assert "pantry is currently empty" in resp_pantry.json()["answer"]

    # Add item to pantry
    api.post("/api/v1/pantry", json={"name": "Oats", "quantity": 100, "unit": "g"})
    resp_pantry2 = api.post(
        "/api/v1/assistant/messages", json={"message": "What can I cook with my pantry?"}
    )
    assert resp_pantry2.status_code == 200
    assert "Oats" in resp_pantry2.json()["answer"]


def test_technical_failure_safely_releases_quota(api: TestClient, owner: User) -> None:
    today = datetime.now(UTC).date()
    initial_used = product_store.read_assistant_usage(owner.id, today)

    with (
        patch(
            "backend.product_api.retrieve_health_effects",
            side_effect=RuntimeError("Simulated DB Crash"),
        ),
        pytest.raises(RuntimeError),
    ):
        api.post("/api/v1/assistant/messages", json={"message": "What does protein do?"})

    # Quota must be refunded after exception
    final_used = product_store.read_assistant_usage(owner.id, today)
    assert final_used == initial_used
