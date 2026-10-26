"""Comprehensive tests for 6-digit email OTP signup and verification flows."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import HTTPException

import backend.auth as auth_module
from backend.auth import (
    EmailOtpRequest,
    EmailOtpVerifyRequest,
    EmailSignupRequest,
    email_signup,
    request_email_otp,
    user_store,
    verify_email_otp,
)
from backend.settings import settings


def _enable_email(monkeypatch: pytest.MonkeyPatch) -> None:
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
    monkeypatch.setattr(auth_module, "send_otp_email", lambda **_: None)


def test_email_signup_generates_otp_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_email(monkeypatch)
    email = f"otp-signup-{uuid4().hex}@example.test"
    monkeypatch.setattr(
        auth_module.secrets,
        "randbelow",
        lambda limit: 123456 if limit == 1_000_000 else 0,
    )
    response = email_signup(
        EmailSignupRequest(
            email=email,
            password="StrongPassword-1234!",
            name="OTP Tester",
            accepted_terms=True,
            accepted_privacy=True,
        )
    )
    assert response.message

    # Correct OTP verification succeeds
    session = verify_email_otp(EmailOtpVerifyRequest(email=email, otp="123456"))
    assert session.user.email == email
    assert session.access_token


def test_wrong_otp_and_attempt_bounding(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_email(monkeypatch)
    email = f"wrong-otp-{uuid4().hex}@example.test"
    monkeypatch.setattr(auth_module.secrets, "randbelow", lambda _: 654321)
    email_signup(
        EmailSignupRequest(
            email=email,
            password="StrongPassword-1234!",
            name="Wrong Code Tester",
            accepted_terms=True,
            accepted_privacy=True,
        )
    )

    # 4 wrong attempts raise 401
    for _ in range(4):
        with pytest.raises(HTTPException) as exc_info:
            verify_email_otp(EmailOtpVerifyRequest(email=email, otp="000000"))
        assert exc_info.value.status_code == 401
        assert "Incorrect" in exc_info.value.detail

    # 5th wrong attempt exhausts budget
    with pytest.raises(HTTPException) as exc_info:
        verify_email_otp(EmailOtpVerifyRequest(email=email, otp="000000"))
    assert exc_info.value.status_code == 429
    assert "Too many failed attempts" in exc_info.value.detail

    # Subsequent attempt with correct code is also locked out
    with pytest.raises(HTTPException) as exc_info:
        verify_email_otp(EmailOtpVerifyRequest(email=email, otp="654321"))
    assert exc_info.value.status_code in (400, 429)


def test_otp_single_use_rejection(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_email(monkeypatch)
    email = f"single-use-{uuid4().hex}@example.test"
    monkeypatch.setattr(auth_module.secrets, "randbelow", lambda _: 112233)
    email_signup(
        EmailSignupRequest(
            email=email,
            password="StrongPassword-1234!",
            name="Single Use",
            accepted_terms=True,
            accepted_privacy=True,
        )
    )

    # First verification succeeds
    session = verify_email_otp(EmailOtpVerifyRequest(email=email, otp="112233"))
    assert session.user.email == email

    # Re-use of same OTP fails
    with pytest.raises(HTTPException) as exc_info:
        verify_email_otp(EmailOtpVerifyRequest(email=email, otp="112233"))
    assert exc_info.value.status_code == 400


def test_resend_cooldown_and_old_otp_invalidation(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_email(monkeypatch)
    email = f"resend-{uuid4().hex}@example.test"
    otps = iter([111111, 222222])
    monkeypatch.setattr(auth_module.secrets, "randbelow", lambda _: next(otps))

    email_signup(
        EmailSignupRequest(
            email=email,
            password="StrongPassword-1234!",
            name="Resend Tester",
            accepted_terms=True,
            accepted_privacy=True,
        )
    )

    # Immediate resend is blocked by cooldown
    with pytest.raises(HTTPException) as exc_info:
        request_email_otp(EmailOtpRequest(email=email))
    assert exc_info.value.status_code == 429
    assert "wait before requesting" in exc_info.value.detail

    # Advance cooldown
    if auth_module.postgres_store is None:
        user_store._email_otp_challenges[email]["resend_after"] = user_store._email_otp_challenges[
            email
        ]["created_at"]

    # Resend succeeds
    res = request_email_otp(EmailOtpRequest(email=email))
    assert "sent" in res.message

    # Old code 111111 is now invalid
    with pytest.raises(HTTPException):
        verify_email_otp(EmailOtpVerifyRequest(email=email, otp="111111"))

    # New code 222222 succeeds
    session = verify_email_otp(EmailOtpVerifyRequest(email=email, otp="222222"))
    assert session.user.email == email


def test_unknown_email_prevents_enumeration(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_email(monkeypatch)
    res = request_email_otp(EmailOtpRequest(email="nonexistent@example.test"))
    assert "verification code has been sent" in res.message
