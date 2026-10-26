from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.auth import create_session_token, user_store
from backend.main import app

client = TestClient(app)


def _owner(name: str = "Google Name") -> tuple[dict[str, str], str, str]:
    suffix = uuid4().hex
    subject = f"account-profile-{suffix}"
    email = f"profile-{suffix}@example.com"
    user = user_store.upsert_google_user(
        {
            "sub": subject,
            "email": email,
            "email_verified": True,
            "name": name,
        }
    )
    token, _ = create_session_token(user)
    return {"Authorization": f"Bearer {token}"}, subject, email


def test_account_profile_is_owner_scoped_masked_and_updates_display_name() -> None:
    owner, subject, email = _owner()
    other, _, _ = _owner("Other Person")

    initial = client.get("/api/v1/account/profile", headers=owner)
    assert initial.status_code == 200
    assert initial.json() == {
        "full_name": "Google Name",
        "date_of_birth": None,
        "masked_phone_number": None,
        "phone_state": "NOT_ADDED",
        "phone_verification_availability": "BLOCKED_EXTERNAL_COST",
        "country_region": None,
        "unit_system": "METRIC",
        "research_insights_consent": False,
        "onboarding_complete": False,
        "age_eligibility": "UNKNOWN",
        "minimum_account_age": 18,
        "legal_acceptance_complete": False,
    }

    saved = client.put(
        "/api/v1/account/profile",
        headers=owner,
        json={
            "full_name": "  Yash Owner  ",
            "date_of_birth": "1990-01-02",
            "phone_update": "SET",
            "phone_number": "+919876543210",
            "country_region": "in",
            "unit_system": "IMPERIAL",
            "research_insights_consent": True,
            "complete_onboarding": True,
            "accepted_terms": True,
            "accepted_privacy": True,
        },
    )
    assert saved.status_code == 200
    payload = saved.json()
    assert payload["full_name"] == "Yash Owner"
    assert payload["date_of_birth"] == "1990-01-02"
    assert payload["masked_phone_number"].startswith("+")
    assert payload["masked_phone_number"].endswith("3210")
    assert "987654" not in payload["masked_phone_number"]
    assert "phone_number" not in payload
    assert payload["phone_state"] == "UNVERIFIED"
    assert payload["phone_verification_availability"] == "BLOCKED_EXTERNAL_COST"
    assert payload["country_region"] == "IN"
    assert payload["unit_system"] == "IMPERIAL"
    assert payload["research_insights_consent"] is True
    assert payload["onboarding_complete"] is True
    assert payload["age_eligibility"] == "ELIGIBLE_18_PLUS"
    assert payload["legal_acceptance_complete"] is True

    assert client.get("/api/v1/auth/me", headers=owner).json()["name"] == "Yash Owner"
    assert client.get("/api/v1/account/profile", headers=other).json()["full_name"] == (
        "Other Person"
    )

    # The owner-selected name survives a later login from the same Google identity.
    logged_in_again = user_store.upsert_google_user(
        {
            "sub": subject,
            "email": email,
            "email_verified": True,
            "name": "Changed Google Name",
        }
    )
    assert logged_in_again.name == "Yash Owner"

    exported = client.get("/api/v1/account/export", headers=owner)
    assert exported.status_code == 200
    assert exported.json()["account_profile"]["phone_number"] == "+919876543210"
    assert exported.json()["account_profile"]["phone_state"] == "UNVERIFIED"


def test_account_profile_phone_state_is_server_controlled_and_removable() -> None:
    owner, _, _ = _owner()
    base = {
        "full_name": "Profile Owner",
        "date_of_birth": "1992-05-10",
        "country_region": "GB",
        "unit_system": "METRIC",
        "research_insights_consent": False,
    }
    assert (
        client.put(
            "/api/v1/account/profile",
            headers=owner,
            json={
                **base,
                "phone_update": "SET",
                "phone_number": "+447700900123",
                "complete_onboarding": True,
                "accepted_terms": True,
                "accepted_privacy": True,
            },
        ).status_code
        == 200
    )

    injected = client.put(
        "/api/v1/account/profile",
        headers=owner,
        json={**base, "phone_state": "VERIFIED"},
    )
    assert injected.status_code == 422

    kept = client.put(
        "/api/v1/account/profile",
        headers=owner,
        json={**base, "phone_update": "KEEP"},
    )
    assert kept.status_code == 200
    assert kept.json()["phone_state"] == "UNVERIFIED"
    assert kept.json()["onboarding_complete"] is True

    removed = client.put(
        "/api/v1/account/profile",
        headers=owner,
        json={**base, "phone_update": "REMOVE"},
    )
    assert removed.status_code == 200
    assert removed.json()["masked_phone_number"] is None
    assert removed.json()["phone_state"] == "NOT_ADDED"


def test_account_profile_rejects_invalid_dob_phone_and_incomplete_completion() -> None:
    owner, _, _ = _owner()
    base = {
        "full_name": "Profile Owner",
        "country_region": "IN",
        "unit_system": "METRIC",
        "research_insights_consent": False,
    }
    for body in (
        {**base, "date_of_birth": "2999-01-01"},
        {
            **base,
            "date_of_birth": "1990-01-01",
            "phone_update": "SET",
            "phone_number": "9876543210",
        },
        {**base, "complete_onboarding": True},
        {
            **base,
            "date_of_birth": "1990-01-01",
            "complete_onboarding": True,
        },
        {
            **base,
            "date_of_birth": f"{datetime.now(UTC).year - 17}-01-01",
            "complete_onboarding": True,
            "accepted_terms": True,
            "accepted_privacy": True,
        },
    ):
        response = client.put("/api/v1/account/profile", headers=owner, json=body)
        assert response.status_code == 422
