from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

import backend.auth as auth_module
from backend.auth import (
    EmailLoginRequest,
    EmailSignupRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    TokenRequest,
    User,
    create_session_token,
    decode_session_token,
    email_login,
    email_signup,
    forgot_password,
    reset_password,
    user_store,
    validate_security_settings,
    verify_email,
)
from backend.settings import settings


def test_session_round_trip_and_wrong_secret_rejection() -> None:
    config = replace(settings, jwt_secret="test-secret-that-is-not-used-in-production")
    user = User(
        id="user-1",
        google_subject="google-1",
        email="person@example.com",
        name="Person",
        avatar_url=None,
    )
    token, expires_in = create_session_token(user, config)

    assert expires_in == config.jwt_access_token_minutes * 60
    assert decode_session_token(token, config) == "user-1"
    with pytest.raises(HTTPException):
        decode_session_token(
            token, replace(config, jwt_secret="a-different-test-secret-with-32-bytes")
        )


def test_auth_capabilities_exposes_the_public_google_client_id(monkeypatch) -> None:
    client_id = "test-client.apps.googleusercontent.com"
    monkeypatch.setattr(
        auth_module,
        "settings",
        replace(settings, google_client_id=client_id),
    )

    capabilities = auth_module.auth_capabilities()

    assert capabilities.google == "READY"
    assert capabilities.google_client_id == client_id


def test_production_rejects_placeholder_session_secret() -> None:
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        validate_security_settings(replace(settings, app_environment="production"))


def test_production_rejects_short_secret_and_unapproved_algorithm() -> None:
    base = replace(
        settings,
        app_environment="production",
        google_client_id="test-client.apps.googleusercontent.com",
        persistence_backend="postgres",
        rate_limit_backend="redis",
    )
    with pytest.raises(RuntimeError, match="at least 32 random bytes"):
        validate_security_settings(replace(base, jwt_secret="too-short"))
    with pytest.raises(RuntimeError, match="JWT_ALGORITHM must be HS256"):
        validate_security_settings(
            replace(
                base,
                jwt_secret="a-secure-test-secret-with-at-least-32-bytes",
                jwt_algorithm="HS512",
            )
        )


def test_production_requires_durable_identity_persistence() -> None:
    config = replace(
        settings,
        app_environment="production",
        jwt_secret="production-shaped-test-secret-at-least-32-bytes",
        google_client_id="test-client.apps.googleusercontent.com",
        persistence_backend="memory",
    )
    with pytest.raises(RuntimeError, match="PERSISTENCE_BACKEND=postgres"):
        validate_security_settings(config)


def test_production_requires_distributed_rate_limiting() -> None:
    config = replace(
        settings,
        app_environment="production",
        jwt_secret="production-shaped-test-secret-at-least-32-bytes",
        google_client_id="test-client.apps.googleusercontent.com",
        persistence_backend="postgres",
        rate_limit_backend="memory",
    )
    with pytest.raises(RuntimeError, match="RATE_LIMIT_BACKEND=redis"):
        validate_security_settings(config)


def test_production_requires_explicit_cors_and_encrypted_datastores() -> None:
    base = replace(
        settings,
        app_environment="production",
        jwt_secret="production-shaped-test-secret-at-least-32-bytes",
        google_client_id="test-client.apps.googleusercontent.com",
        persistence_backend="postgres",
        rate_limit_backend="redis",
        cors_origins=("https://nutrilens.tech",),
        postgres_url="postgresql://user:secret@db.invalid/app?sslmode=require",
        redis_url="rediss://user:secret@cache.invalid:6380/0",
    )
    validate_security_settings(base)
    with pytest.raises(RuntimeError, match="explicit HTTPS origins"):
        validate_security_settings(replace(base, cors_origins=("*",)))
    with pytest.raises(RuntimeError, match="POSTGRES_URL must require TLS"):
        validate_security_settings(replace(base, postgres_url="postgresql://db.invalid/app"))
    with pytest.raises(RuntimeError, match="REDIS_URL must use TLS"):
        validate_security_settings(replace(base, redis_url="redis://cache.invalid/0"))


def _enable_test_email(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        auth_module,
        "settings",
        replace(
            settings,
            email_auth_enabled=True,
            email_provider="resend",
            email_from="NutriLens X <no-reply@example.test>",
            resend_api_key="test-only-key",
        ),
    )
    monkeypatch.setattr(auth_module, "send_verification_email", lambda **_: None)
    monkeypatch.setattr(auth_module, "send_password_reset_email", lambda **_: None)


def test_email_signup_verification_login_and_duplicate_prevention(monkeypatch) -> None:
    _enable_test_email(monkeypatch)
    email = f"person-{uuid4().hex}@example.test"
    verification_token = f"verify-{uuid4().hex}"
    monkeypatch.setattr(auth_module.secrets, "token_urlsafe", lambda _: verification_token)

    response = email_signup(
        EmailSignupRequest(
            email=email,
            password="Strong-password-42!",
            name="Email Person",
            accepted_terms=True,
            accepted_privacy=True,
        )
    )
    assert "verification email" in response.message
    with pytest.raises(HTTPException, match="Verify your email"):
        email_login(EmailLoginRequest(email=email, password="Strong-password-42!"))

    verified = verify_email(TokenRequest(token=verification_token))
    assert verified.user.email == email
    logged_in = email_login(EmailLoginRequest(email=email, password="Strong-password-42!"))
    assert logged_in.user.id == verified.user.id

    duplicate = email_signup(
        EmailSignupRequest(
            email=email,
            password="Different-password-42!",
            name="Duplicate Attempt",
            accepted_terms=True,
            accepted_privacy=True,
        )
    )
    assert "verification email" in duplicate.message
    still_original = email_login(EmailLoginRequest(email=email, password="Strong-password-42!"))
    assert still_original.user.id == verified.user.id


def test_verified_google_email_links_to_email_identity(monkeypatch) -> None:
    _enable_test_email(monkeypatch)
    email = f"linked-{uuid4().hex}@example.test"
    google_user = user_store.upsert_google_user(
        {
            "sub": f"google-{uuid4().hex}",
            "email": email,
            "email_verified": True,
            "name": "Linked Person",
        }
    )
    verification_token = f"verify-{uuid4().hex}"
    monkeypatch.setattr(auth_module.secrets, "token_urlsafe", lambda _: verification_token)
    email_signup(
        EmailSignupRequest(
            email=email,
            password="Linked-password-42!",
            name="Linked Person",
            accepted_terms=True,
            accepted_privacy=True,
        )
    )
    verified = verify_email(TokenRequest(token=verification_token))
    assert verified.user.id == google_user.id


def test_password_reset_is_one_time_and_revokes_existing_session(monkeypatch) -> None:
    _enable_test_email(monkeypatch)
    email = f"reset-{uuid4().hex}@example.test"
    verification_token = f"verify-{uuid4().hex}"
    reset_token = f"reset-{uuid4().hex}"
    issued_tokens = iter((verification_token, reset_token))
    monkeypatch.setattr(auth_module.secrets, "token_urlsafe", lambda _: next(issued_tokens))
    email_signup(
        EmailSignupRequest(
            email=email,
            password="Before-reset-42!",
            name="Reset Person",
            accepted_terms=True,
            accepted_privacy=True,
        )
    )
    session = verify_email(TokenRequest(token=verification_token))
    forgot_password(ForgotPasswordRequest(email=email))
    reset_password(ResetPasswordRequest(token=reset_token, password="After-reset-84!"))

    with pytest.raises(HTTPException, match="Invalid email or password"):
        email_login(EmailLoginRequest(email=email, password="Before-reset-42!"))
    replacement = email_login(EmailLoginRequest(email=email, password="After-reset-84!"))
    assert replacement.user.id == session.user.id
    claims = auth_module.decode_session_claims(session.access_token)
    assert not user_store.auth_session_active(claims["jti"], claims["sub"])

    with pytest.raises(HTTPException, match="invalid or expired"):
        reset_password(ResetPasswordRequest(token=reset_token, password="Another-reset-99!"))


def test_logout_revokes_server_session() -> None:
    user = user_store.upsert_google_user(
        {
            "sub": f"logout-{uuid4().hex}",
            "email": f"logout-{uuid4().hex}@example.test",
            "email_verified": True,
        }
    )
    token, _ = create_session_token(user)
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    auth_module.logout(user=user, credentials=credentials)
    claims = auth_module.decode_session_claims(token)
    assert not user_store.auth_session_active(claims["jti"], claims["sub"])
