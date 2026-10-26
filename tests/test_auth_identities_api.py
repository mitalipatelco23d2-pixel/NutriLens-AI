from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import backend.auth as auth_module
from backend.auth import User, create_session_token, user_store
from backend.main import app
from backend.settings import settings

client = TestClient(app)


def _google_owner() -> tuple[dict[str, str], User]:
    suffix = uuid4().hex
    user = user_store.upsert_google_user(
        {
            "sub": f"google-identity-{suffix}",
            "email": f"identity-{suffix}@example.test",
            "email_verified": True,
            "name": "Identity Owner",
        }
    )
    token, _ = create_session_token(user)
    return {"Authorization": f"Bearer {token}"}, user


def test_email_signup_requires_terms_and_privacy_acceptance(monkeypatch) -> None:
    monkeypatch.setattr(
        auth_module,
        "settings",
        replace(
            settings,
            email_auth_enabled=True,
            email_provider="resend",
            email_from="NutriLens X <no-reply@example.test>",
            resend_api_key="test-key",
        ),
    )
    body = {
        "name": "Legal Owner",
        "email": f"legal-{uuid4().hex}@example.test",
        "password": "Strong-password-42!",
    }
    assert client.post("/api/v1/auth/email/signup", json=body).status_code == 422
    assert (
        client.post(
            "/api/v1/auth/email/signup",
            json={**body, "accepted_terms": True, "accepted_privacy": False},
        ).status_code
        == 422
    )


def test_google_disconnect_refuses_to_remove_sole_login() -> None:
    headers, _ = _google_owner()
    status = client.get("/api/v1/auth/identities", headers=headers)
    assert status.status_code == 200
    assert status.json()["google_connected"] is True
    assert status.json()["email_password_connected"] is False

    blocked = client.delete("/api/v1/auth/identities/google", headers=headers)
    assert blocked.status_code == 409
    assert "Add and verify" in blocked.json()["detail"]
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200


def test_google_can_disconnect_after_verified_password_login_exists() -> None:
    headers, user = _google_owner()
    result = user_store.register_email_user(
        email=user.email,
        display_name=user.name,
        password_hash=auth_module._password_hasher.hash("Strong-password-42!"),
        legal_accepted=True,
    )
    user_store.verify_email_identity(str(result["identity_id"]))

    disconnected = client.delete("/api/v1/auth/identities/google", headers=headers)
    assert disconnected.status_code == 200
    assert disconnected.json()["google_connected"] is False
    assert disconnected.json()["email_verified"] is True
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200


def test_connect_google_requires_same_email_and_unattached_subject(monkeypatch) -> None:
    first_headers, first = _google_owner()
    second_headers, second = _google_owner()
    first_subject = first.google_subject
    assert first_subject

    monkeypatch.setattr(
        auth_module,
        "_verified_google_claims",
        lambda _credential: {
            "sub": first_subject,
            "email": second.email,
            "email_verified": True,
        },
    )
    conflict = client.post(
        "/api/v1/auth/identities/google/connect",
        headers=second_headers,
        json={"credential": "x" * 20},
    )
    assert conflict.status_code == 409
    assert "another account" in conflict.json()["detail"]

    monkeypatch.setattr(
        auth_module,
        "_verified_google_claims",
        lambda _credential: {
            "sub": f"new-{uuid4().hex}",
            "email": "different@example.test",
            "email_verified": True,
        },
    )
    mismatch = client.post(
        "/api/v1/auth/identities/google/connect",
        headers=second_headers,
        json={"credential": "y" * 20},
    )
    assert mismatch.status_code == 409
    assert "same verified email" in mismatch.json()["detail"]
    assert client.get("/api/v1/auth/me", headers=first_headers).status_code == 200


def test_google_link_and_unlink_alias_endpoints(monkeypatch) -> None:
    headers, user = _google_owner()

    # Unlink blocked when Google is the sole login method
    unlink_blocked = client.post("/api/v1/auth/google/unlink", headers=headers)
    assert unlink_blocked.status_code == 409
    assert "Add and verify" in unlink_blocked.json()["detail"]

    # Register email/password login and verify it
    result = user_store.register_email_user(
        email=user.email,
        display_name=user.name,
        password_hash=auth_module._password_hasher.hash("Strong-password-42!"),
        legal_accepted=True,
    )
    user_store.verify_email_identity(str(result["identity_id"]))

    # Unlink succeeds when password exists
    unlinked = client.post("/api/v1/auth/google/unlink", headers=headers)
    assert unlinked.status_code == 200
    assert unlinked.json()["google_connected"] is False

    # Link back via /google/link
    monkeypatch.setattr(
        auth_module,
        "_verified_google_claims",
        lambda _cred: {
            "sub": user.google_subject,
            "email": user.email,
            "email_verified": True,
        },
    )
    linked = client.post(
        "/api/v1/auth/google/link",
        headers=headers,
        json={"credential": "valid-cred-token-1234"},
    )
    assert linked.status_code == 200
    assert linked.json()["google_connected"] is True


def test_phone_linking_and_canonical_account_identity(monkeypatch) -> None:
    headers, user = _google_owner()
    phone = "+919876543210"

    # Initially phone is not verified
    status = client.get("/api/v1/auth/identities", headers=headers)
    assert status.status_code == 200
    assert status.json()["phone_verified"] is False

    # Mock verified Firebase phone proof
    monkeypatch.setattr(
        auth_module,
        "_verified_firebase_phone_claims",
        lambda _cred, _phone: {"sub": f"firebase-{_phone}", "phone_number": _phone},
    )

    # Connect phone to account
    res = client.post(
        "/api/v1/auth/phone/link",
        headers=headers,
        json={"phone": phone, "firebase_id_token": "valid-firebase-proof-1234"},
    )
    assert res.status_code == 200
    assert res.json()["phone_verified"] is True

    # Profile reflects verified phone state
    profile = client.get("/api/v1/account/profile", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["phone_state"] == "VERIFIED"
    assert profile.json()["masked_phone_number"].endswith("3210")

    # Another user cannot claim the same phone
    other_headers, _ = _google_owner()
    conflict = client.post(
        "/api/v1/auth/phone/link",
        headers=other_headers,
        json={"phone": phone, "firebase_id_token": "valid-firebase-proof-1234"},
    )
    assert conflict.status_code == 409
    assert "already linked" in conflict.json()["detail"]

    # Phone can be used to log in
    login = client.post(
        "/api/v1/auth/phone/verify",
        json={"phone": phone, "firebase_id_token": "valid-firebase-proof-1234"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["id"] == user.id
    assert login.json()["user"]["email"] == user.email


@pytest.mark.parametrize("env", ["development", "local_qa", "test"])
def test_firebase_phone_fails_closed_when_project_id_missing_across_environments(
    monkeypatch, env: str
) -> None:
    headers, _ = _google_owner()
    phone = "+919876543210"

    # Set missing FIREBASE_PROJECT_ID across dev, local_qa, test and with college_demo_mode=True
    monkeypatch.setattr(
        auth_module,
        "settings",
        replace(
            settings,
            firebase_project_id="",
            app_environment=env,
            college_demo_mode=True,
        ),
    )

    # 1. /phone/link fails closed with 503
    res_link = client.post(
        "/api/v1/auth/phone/link",
        headers=headers,
        json={"phone": phone, "firebase_id_token": "arbitrary-unsigned-proof-token"},
    )
    assert res_link.status_code == 503
    assert "not configured" in res_link.json()["detail"]

    # 2. unauthenticated /phone/verify fails closed with 503
    res_verify = client.post(
        "/api/v1/auth/phone/verify",
        json={"phone": phone, "firebase_id_token": "arbitrary-unsigned-proof-token"},
    )
    assert res_verify.status_code == 503
    assert "not configured" in res_verify.json()["detail"]

    # 3. Canonical account phone remains unverified
    status = client.get("/api/v1/auth/identities", headers=headers)
    assert status.status_code == 200
    assert status.json()["phone_verified"] is False


def test_firebase_phone_forged_token_rejected_when_configured(monkeypatch) -> None:
    headers, _ = _google_owner()
    phone = "+919876543210"

    # Set configured project ID
    monkeypatch.setattr(
        auth_module,
        "settings",
        replace(
            settings,
            firebase_project_id="nutrilens-x-production",
            app_environment="development",
            college_demo_mode=True,
        ),
    )

    # Forged/malformed token must be rejected with 401
    res = client.post(
        "/api/v1/auth/phone/link",
        headers=headers,
        json={"phone": phone, "firebase_id_token": "forged.header.signature"},
    )
    assert res.status_code == 401
    assert "verification failed" in res.json()["detail"]


def test_client_cannot_directly_flip_phone_state_to_verified(monkeypatch) -> None:
    headers, _ = _google_owner()

    # 1. Attempting to directly inject phone_state via profile update is rejected (extra="forbid")
    rejected = client.put(
        "/api/v1/account/profile",
        headers=headers,
        json={
            "full_name": "Test User",
            "phone_update": "SET",
            "phone_number": "+919876543210",
            "phone_state": "VERIFIED",
            "date_of_birth": "1995-05-15",
            "country_region": "IN",
            "unit_system": "METRIC",
            "research_insights_consent": True,
        },
    )
    assert rejected.status_code == 422

    # 2. Legitimate profile update sets phone_state to UNVERIFIED, never VERIFIED
    update = client.put(
        "/api/v1/account/profile",
        headers=headers,
        json={
            "full_name": "Test User",
            "phone_update": "SET",
            "phone_number": "+919876543210",
            "date_of_birth": "1995-05-15",
            "country_region": "IN",
            "unit_system": "METRIC",
            "research_insights_consent": True,
        },
    )
    assert update.status_code == 200
    profile = client.get("/api/v1/account/profile", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["phone_state"] == "UNVERIFIED"
