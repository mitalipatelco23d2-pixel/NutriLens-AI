from uuid import uuid4

from fastapi.testclient import TestClient

from backend.auth import create_session_token, decode_session_claims, user_store
from backend.main import app

client = TestClient(app)


def _user_and_token(label: str) -> tuple[str, str]:
    suffix = uuid4().hex
    user = user_store.upsert_google_user(
        {
            "sub": f"session-{label}-{suffix}",
            "email": f"session-{label}-{suffix}@example.com",
            "email_verified": True,
            "name": f"Session {label}",
        }
    )
    token, _ = create_session_token(user)
    return user.id, token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_sessions_are_owner_scoped_and_an_owner_can_revoke_another_session() -> None:
    user_id, older_token = _user_and_token("Owner")
    user = user_store.get(user_id)
    assert user is not None
    current_token, _ = create_session_token(user)
    _, other_owner_token = _user_and_token("Other")
    other_session_id = decode_session_claims(other_owner_token)["jti"]

    response = client.get("/api/v1/auth/sessions", headers=_headers(current_token))
    assert response.status_code == 200
    sessions = response.json()
    assert len(sessions) == 2
    assert sum(item["current"] for item in sessions) == 1
    assert sessions[0]["current"] is True
    assert {item["id"] for item in sessions} == {
        decode_session_claims(older_token)["jti"],
        decode_session_claims(current_token)["jti"],
    }
    assert all(item["created_at"] and item["last_seen_at"] for item in sessions)

    denied = client.delete(
        f"/api/v1/auth/sessions/{other_session_id}", headers=_headers(current_token)
    )
    assert denied.status_code == 404
    assert client.get("/api/v1/auth/me", headers=_headers(other_owner_token)).status_code == 200

    older_id = decode_session_claims(older_token)["jti"]
    revoked = client.delete(f"/api/v1/auth/sessions/{older_id}", headers=_headers(current_token))
    assert revoked.status_code == 204
    assert client.get("/api/v1/auth/me", headers=_headers(older_token)).status_code == 401
    assert client.get("/api/v1/auth/me", headers=_headers(current_token)).status_code == 200


def test_owner_can_revoke_current_session() -> None:
    _, token = _user_and_token("Current")
    session_id = decode_session_claims(token)["jti"]

    response = client.delete(f"/api/v1/auth/sessions/{session_id}", headers=_headers(token))
    assert response.status_code == 204
    assert client.get("/api/v1/auth/me", headers=_headers(token)).status_code == 401
