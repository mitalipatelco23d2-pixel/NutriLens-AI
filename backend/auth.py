"""Canonical Google, email/password, session, and provider-neutral phone authentication."""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import RLock
from typing import Annotated, Any, Literal
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from pydantic import BaseModel, Field

from backend.email_delivery import (
    EmailDeliveryError,
    send_otp_email,
    send_password_reset_email,
    send_verification_email,
)
from backend.entitlements import (
    PlanCode,
    SpecialRole,
    SubscriptionStatus,
    resolve_entitlements,
)
from backend.settings import Settings, settings
from backend.storage_runtime import postgres_store

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
bearer = HTTPBearer(auto_error=False)

_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")
_LOCAL_JWT_PLACEHOLDER = "replace_before_non_local_use_at_least_32_bytes"
_MINIMUM_HMAC_SECRET_BYTES = 32
_password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=2,
    hash_len=32,
    salt_len=16,
)
_DUMMY_PASSWORD_HASH = _password_hasher.hash("NutriLens-dummy-password-only-for-timing")


@dataclass(frozen=True)
class User:
    id: str
    google_subject: str | None
    email: str
    name: str
    avatar_url: str | None
    terms_accepted_at: datetime | None = None
    privacy_accepted_at: datetime | None = None
    plan: PlanCode = PlanCode.FREE
    subscription_status: SubscriptionStatus = SubscriptionStatus.FREE
    roles: frozenset[SpecialRole] = frozenset()


def _record_from_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "google_subject": user.google_subject,
        "email": user.email,
        "display_name": user.name,
        "avatar_url": user.avatar_url,
        "terms_accepted_at": user.terms_accepted_at,
        "privacy_accepted_at": user.privacy_accepted_at,
        "plan_code": user.plan.value,
        "subscription_status": user.subscription_status.value,
        "roles": [role.value for role in user.roles],
    }


class UserStore:
    """Thread-safe development store behind the durable PostgreSQL repository boundary."""

    def __init__(self) -> None:
        self._by_id: dict[str, User] = {}
        self._by_google_subject: dict[str, str] = {}
        self._by_email: dict[str, str] = {}
        self._email_credentials: dict[str, dict[str, Any]] = {}
        self._action_tokens: dict[str, dict[str, Any]] = {}
        self._email_otp_challenges: dict[str, dict[str, Any]] = {}
        self._verified_phones: dict[str, str] = {}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._security_events: list[dict[str, Any]] = []
        self._lock = RLock()

    def upsert_google_user(self, claims: dict[str, Any]) -> User:
        if postgres_store is not None:
            return _user_from_record(postgres_store.upsert_google_user(claims))
        subject = str(claims["sub"])
        email = _normalize_email(str(claims["email"]))
        with self._lock:
            existing_id = self._by_google_subject.get(subject) or self._by_email.get(email)
            user_id = existing_id or str(uuid4())
            previous = self._by_id.get(user_id)
            user = User(
                id=user_id,
                google_subject=subject,
                email=email,
                # Once created, the NutriLens profile name is owner-controlled.
                # A later Google login must not silently overwrite that choice.
                name=previous.name if previous else str(claims.get("name") or email),
                avatar_url=str(claims["picture"]) if claims.get("picture") else None,
                terms_accepted_at=previous.terms_accepted_at if previous else None,
                privacy_accepted_at=previous.privacy_accepted_at if previous else None,
                plan=previous.plan if previous else PlanCode.FREE,
                subscription_status=(
                    previous.subscription_status if previous else SubscriptionStatus.FREE
                ),
                roles=previous.roles if previous else frozenset(),
            )
            self._by_id[user_id] = user
            self._by_google_subject[subject] = user_id
            self._by_email[email] = user_id
            return user

    def register_email_user(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
        legal_accepted: bool = False,
    ) -> dict[str, Any]:
        if postgres_store is not None:
            result = postgres_store.register_email_user(
                email=email,
                display_name=display_name,
                password_hash=password_hash,
                legal_accepted=legal_accepted,
            )
            return {**result, "user": _user_from_record(result["user"])}
        with self._lock:
            existing_id = self._by_email.get(email)
            user_id = existing_id or str(uuid4())
            user = self._by_id.get(user_id)
            created_user = user is None
            if user is None:
                user = User(
                    id=user_id,
                    google_subject=None,
                    email=email,
                    name=display_name,
                    avatar_url=None,
                )
                self._by_id[user_id] = user
                self._by_email[email] = user_id
            if (
                created_user
                and legal_accepted
                and (user.terms_accepted_at is None or user.privacy_accepted_at is None)
            ):
                accepted_at = datetime.now(UTC)
                user = replace(
                    user,
                    terms_accepted_at=user.terms_accepted_at or accepted_at,
                    privacy_accepted_at=user.privacy_accepted_at or accepted_at,
                )
                self._by_id[user_id] = user
            existing = self._email_credentials.get(email)
            if existing is None:
                identity_id = str(uuid4())
                self._email_credentials[email] = {
                    "identity_id": identity_id,
                    "user_id": user_id,
                    "password_hash": password_hash,
                    "verified_email": None,
                    "failed_attempts": 0,
                    "locked_until": None,
                }
            else:
                identity_id = str(existing["identity_id"])
            return {
                "user": user,
                "identity_id": identity_id,
                "credential_created": existing is None,
                "verified": bool(existing and existing.get("verified_email")),
            }

    def accept_legal(self, user_id: str) -> User | None:
        if postgres_store is not None:
            record = postgres_store.accept_user_legal(user_id)
            return _user_from_record(record) if record else None
        with self._lock:
            user = self._by_id.get(user_id)
            if user is None:
                return None
            accepted_at = datetime.now(UTC)
            updated = replace(
                user,
                terms_accepted_at=user.terms_accepted_at or accepted_at,
                privacy_accepted_at=user.privacy_accepted_at or accepted_at,
            )
            self._by_id[user_id] = updated
            return updated

    def identity_status(self, user_id: str) -> dict[str, bool]:
        if postgres_store is not None:
            return postgres_store.get_auth_identity_status(user_id)
        with self._lock:
            user = self._by_id.get(user_id)
            credential = self._email_credentials.get(user.email) if user else None
            phone_verified = any(uid == user_id for uid in self._verified_phones.values())
            return {
                "google_connected": bool(user and user.google_subject),
                "email_password_connected": credential is not None,
                "email_verified": bool(credential and credential.get("verified_email")),
                "phone_verified": phone_verified,
            }

    def link_phone_identity(
        self, user_id: str, *, phone_e164: str, provider_subject: str
    ) -> tuple[User | None, str]:
        if postgres_store is not None:
            record, outcome = postgres_store.link_phone_identity(
                user_id, phone_e164=phone_e164, provider_subject=provider_subject
            )
            return (_user_from_record(record) if record else None), outcome
        with self._lock:
            user = self._by_id.get(user_id)
            if user is None:
                return None, "USER_NOT_FOUND"
            existing_user = self._verified_phones.get(phone_e164)
            if existing_user is not None and existing_user != user_id:
                return None, "PHONE_ALREADY_LINKED"
            self._verified_phones[phone_e164] = user_id
            return user, "SUCCESS"

    def connect_google_identity(self, user_id: str, claims: dict[str, Any]) -> str:
        if postgres_store is not None:
            return postgres_store.connect_google_identity(user_id, claims)
        subject = str(claims["sub"])
        email = _normalize_email(str(claims["email"]))
        with self._lock:
            user = self._by_id.get(user_id)
            if user is None:
                return "NOT_FOUND"
            if user.email.casefold() != email:
                return "EMAIL_MISMATCH"
            attached_user = self._by_google_subject.get(subject)
            if attached_user is not None and attached_user != user_id:
                return "ALREADY_LINKED"
            if user.google_subject and user.google_subject != subject:
                return "DIFFERENT_GOOGLE_CONNECTED"
            updated = replace(
                user,
                google_subject=subject,
                avatar_url=(str(claims["picture"]) if claims.get("picture") else user.avatar_url),
            )
            self._by_id[user_id] = updated
            self._by_google_subject[subject] = user_id
            return "CONNECTED"

    def disconnect_google_identity(self, user_id: str) -> str:
        if postgres_store is not None:
            return postgres_store.disconnect_google_identity(user_id)
        with self._lock:
            user = self._by_id.get(user_id)
            if user is None:
                return "NOT_FOUND"
            if not user.google_subject:
                return "NOT_CONNECTED"
            credential = self._email_credentials.get(user.email)
            if credential is None or not credential.get("verified_email"):
                return "SOLE_LOGIN"
            self._by_google_subject.pop(user.google_subject, None)
            self._by_id[user_id] = replace(user, google_subject=None)
            return "DISCONNECTED"

    def get_email_credential(self, email: str) -> dict[str, Any] | None:
        if postgres_store is not None:
            return postgres_store.get_email_credential(email)
        with self._lock:
            credential = self._email_credentials.get(email)
            if credential is None:
                return None
            user = self._by_id.get(str(credential["user_id"]))
            if user is None:
                return None
            return {**_record_from_user(user), **credential}

    def mark_email_login_success(self, identity_id: str) -> None:
        if postgres_store is not None:
            postgres_store.mark_email_login_success(identity_id)
            return
        with self._lock:
            for credential in self._email_credentials.values():
                if credential["identity_id"] == identity_id:
                    credential["failed_attempts"] = 0
                    credential["locked_until"] = None
                    return

    def mark_email_login_failure(
        self, identity_id: str, *, maximum_attempts: int, locked_until: datetime
    ) -> None:
        if postgres_store is not None:
            postgres_store.mark_email_login_failure(
                identity_id, maximum_attempts=maximum_attempts, locked_until=locked_until
            )
            return
        with self._lock:
            for credential in self._email_credentials.values():
                if credential["identity_id"] != identity_id:
                    continue
                credential["failed_attempts"] = int(credential["failed_attempts"]) + 1
                if int(credential["failed_attempts"]) >= maximum_attempts:
                    credential["locked_until"] = locked_until
                return

    def create_auth_action_token(
        self,
        *,
        user_id: str,
        identity_id: str | None,
        purpose: str,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        if postgres_store is not None:
            postgres_store.create_auth_action_token(
                user_id=user_id,
                identity_id=identity_id,
                purpose=purpose,
                token_hash=token_hash,
                expires_at=expires_at,
            )
            return
        with self._lock:
            for record in self._action_tokens.values():
                if (
                    record["user_id"] == user_id
                    and record["purpose"] == purpose
                    and record["consumed_at"] is None
                ):
                    record["consumed_at"] = datetime.now(UTC)
            self._action_tokens[token_hash] = {
                "user_id": user_id,
                "identity_id": identity_id,
                "purpose": purpose,
                "expires_at": expires_at,
                "consumed_at": None,
            }

    def consume_auth_action_token(self, *, purpose: str, token_hash: str) -> dict[str, Any] | None:
        if postgres_store is not None:
            return postgres_store.consume_auth_action_token(purpose=purpose, token_hash=token_hash)
        with self._lock:
            record = self._action_tokens.get(token_hash)
            if (
                record is None
                or record["purpose"] != purpose
                or record["consumed_at"] is not None
                or record["expires_at"] <= datetime.now(UTC)
            ):
                return None
            record["consumed_at"] = datetime.now(UTC)
            return dict(record)

    def verify_email_identity(self, identity_id: str) -> User:
        if postgres_store is not None:
            return _user_from_record(postgres_store.verify_email_identity(identity_id))
        with self._lock:
            for email, credential in self._email_credentials.items():
                if credential["identity_id"] == identity_id:
                    credential["verified_email"] = email
                    user = self._by_id.get(str(credential["user_id"]))
                    if user is not None:
                        return user
        raise RuntimeError("Email identity no longer exists.")

    def update_password(self, identity_id: str, password_hash: str) -> None:
        if postgres_store is not None:
            postgres_store.update_password(identity_id, password_hash)
            return
        with self._lock:
            for credential in self._email_credentials.values():
                if credential["identity_id"] == identity_id:
                    credential.update(
                        password_hash=password_hash,
                        failed_attempts=0,
                        locked_until=None,
                    )
                    return

    def create_auth_session(
        self, *, session_id: str, user_id: str, expires_at: datetime, rotated_from: str | None
    ) -> None:
        if postgres_store is not None:
            postgres_store.create_auth_session(
                session_id=session_id,
                user_id=user_id,
                expires_at=expires_at,
                rotated_from=rotated_from,
            )
            return
        with self._lock:
            now = datetime.now(UTC)
            self._sessions[session_id] = {
                "user_id": user_id,
                "expires_at": expires_at,
                "revoked": False,
                "rotated_from": rotated_from,
                "created_at": now,
                "last_seen_at": now,
            }

    def auth_session_active(self, session_id: str, user_id: str) -> bool:
        if postgres_store is not None:
            return postgres_store.auth_session_active(session_id, user_id)
        with self._lock:
            record = self._sessions.get(session_id)
            active = bool(
                record
                and record["user_id"] == user_id
                and not record["revoked"]
                and record["expires_at"] > datetime.now(UTC)
            )
            if active and record is not None:
                record["last_seen_at"] = datetime.now(UTC)
            return active

    def revoke_auth_session(self, session_id: str) -> None:
        if postgres_store is not None:
            postgres_store.revoke_auth_session(session_id)
            return
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id]["revoked"] = True

    def revoke_user_sessions(self, user_id: str, *, except_session_id: str | None = None) -> None:
        if postgres_store is not None:
            postgres_store.revoke_user_sessions(user_id, except_session_id=except_session_id)
            return
        with self._lock:
            for session_id, record in self._sessions.items():
                if record["user_id"] == user_id and session_id != except_session_id:
                    record["revoked"] = True

    def list_active_sessions(self, user_id: str) -> list[dict[str, Any]]:
        if postgres_store is not None:
            return postgres_store.list_active_auth_sessions(user_id)
        now = datetime.now(UTC)
        with self._lock:
            return [
                {"id": session_id, **record}
                for session_id, record in self._sessions.items()
                if record["user_id"] == user_id
                and not record["revoked"]
                and record["expires_at"] > now
            ]

    def revoke_owned_session(self, user_id: str, session_id: str) -> bool:
        if postgres_store is not None:
            return postgres_store.revoke_owned_auth_session(user_id, session_id)
        with self._lock:
            record = self._sessions.get(session_id)
            if record is None or record["user_id"] != user_id or record["revoked"]:
                return False
            record["revoked"] = True
            return True

    def record_security_event(
        self, *, user_id: str | None, event_type: str, metadata: dict[str, Any] | None = None
    ) -> None:
        safe_metadata = {
            key: value
            for key, value in (metadata or {}).items()
            if key not in {"password", "token", "credential", "otp"}
        }
        if postgres_store is not None:
            postgres_store.record_auth_security_event(
                user_id=user_id, event_type=event_type, metadata=safe_metadata
            )
            return
        with self._lock:
            self._security_events.append(
                {"user_id": user_id, "event_type": event_type, "metadata": safe_metadata}
            )

    def get(self, user_id: str) -> User | None:
        if postgres_store is not None:
            record = postgres_store.get_user(user_id)
            return _user_from_record(record) if record else None
        return self._by_id.get(user_id)

    def update_display_name(self, user_id: str, display_name: str) -> User | None:
        if postgres_store is not None:
            record = postgres_store.update_user_display_name(user_id, display_name)
            return _user_from_record(record) if record else None
        with self._lock:
            user = self._by_id.get(user_id)
            if user is None:
                return None
            updated = replace(user, name=display_name)
            self._by_id[user_id] = updated
            return updated

    def delete(self, user_id: str) -> bool:
        if postgres_store is not None:
            return postgres_store.delete_user(user_id)
        with self._lock:
            user = self._by_id.pop(user_id, None)
            if user is None:
                return False
            if user.google_subject:
                self._by_google_subject.pop(user.google_subject, None)
            self._by_email.pop(user.email, None)
            self._email_credentials.pop(user.email, None)
            for session in self._sessions.values():
                if session["user_id"] == user_id:
                    session["revoked"] = True
            return True

    def create_email_otp_challenge(
        self,
        *,
        email: str,
        user_id: str,
        identity_id: str,
        otp_hash: str,
        lifetime_minutes: int = 10,
        cooldown_seconds: int = 60,
    ) -> dict[str, Any]:
        if postgres_store is not None:
            return postgres_store.create_email_otp_challenge(
                email=email,
                user_id=user_id,
                identity_id=identity_id,
                otp_hash=otp_hash,
                lifetime_minutes=lifetime_minutes,
                cooldown_seconds=cooldown_seconds,
            )
        now = datetime.now(UTC)
        with self._lock:
            challenge = {
                "id": str(uuid4()),
                "email": email.lower(),
                "user_id": user_id,
                "identity_id": identity_id,
                "otp_hash": otp_hash,
                "expires_at": now + timedelta(minutes=lifetime_minutes),
                "resend_after": now + timedelta(seconds=cooldown_seconds),
                "attempts": 0,
                "consumed_at": None,
                "created_at": now,
            }
            self._email_otp_challenges[email.lower()] = challenge
            return challenge

    def verify_email_otp(
        self, *, email: str, otp_hash: str, max_attempts: int = 5
    ) -> tuple[User | None, str]:
        if postgres_store is not None:
            record, status_code = postgres_store.verify_email_otp(
                email=email, otp_hash=otp_hash, max_attempts=max_attempts
            )
            return (_user_from_record(record) if record else None), status_code
        now = datetime.now(UTC)
        with self._lock:
            challenge = self._email_otp_challenges.get(email.lower())
            if challenge is None or challenge["consumed_at"] is not None:
                return None, "EXPIRED_OR_INVALID"
            if challenge["expires_at"] <= now:
                challenge["consumed_at"] = now
                return None, "EXPIRED_OR_INVALID"
            if challenge["attempts"] >= max_attempts:
                challenge["consumed_at"] = now
                return None, "TOO_MANY_ATTEMPTS"
            if challenge["otp_hash"] != otp_hash:
                challenge["attempts"] += 1
                if challenge["attempts"] >= max_attempts:
                    challenge["consumed_at"] = now
                    return None, "TOO_MANY_ATTEMPTS"
                return None, "WRONG_CODE"
            challenge["consumed_at"] = now
            cred = self._email_credentials.get(email.lower())
            if cred:
                cred["verified_email"] = email.lower()
            user = self._by_id.get(challenge["user_id"])
            if user:
                user = replace(user, terms_accepted_at=user.terms_accepted_at or now)
                self._by_id[user.id] = user
            return user, "SUCCESS"

    def check_email_otp_resend_cooldown(self, email: str) -> bool:
        if postgres_store is not None:
            return postgres_store.check_email_otp_resend_cooldown(email)
        now = datetime.now(UTC)
        with self._lock:
            challenge = self._email_otp_challenges.get(email.lower())
            return bool(
                challenge and challenge["consumed_at"] is None and challenge["resend_after"] > now
            )


class GoogleCredentialRequest(BaseModel):
    credential: str = Field(min_length=20, max_length=16_384)


class EmailSignupRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(min_length=2, max_length=100)
    accepted_terms: Literal[True]
    accepted_privacy: Literal[True]


class AddPasswordRequest(BaseModel):
    password: str = Field(min_length=12, max_length=128)


class EmailLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class ResetPasswordRequest(TokenRequest):
    password: str = Field(min_length=12, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class PhoneOtpRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=16)


class PhoneOtpVerifyRequest(PhoneOtpRequest):
    challenge_id: str = Field(default="", max_length=100)
    otp: str = Field(default="", max_length=10)
    firebase_id_token: str | None = Field(default=None, max_length=4096)


class PhoneVerificationProofRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=16)
    firebase_id_token: str = Field(min_length=20, max_length=4096)


class EmailOtpRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class EmailOtpVerifyRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    otp: str = Field(min_length=6, max_length=6)


class AuthenticatedUser(BaseModel):
    id: str
    has_google_identity: bool
    email: str
    name: str
    avatar_url: str | None
    plan: PlanCode
    subscription_status: SubscriptionStatus
    roles: set[SpecialRole]
    entitlements: dict[str, int | bool]


class SessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    user: AuthenticatedUser


class MessageResponse(BaseModel):
    message: str


class AuthCapabilities(BaseModel):
    google: str
    google_client_id: str | None = None
    email: str
    phone_otp: str
    demo_login: str = "NOT_AVAILABLE"


class AuthSessionSummary(BaseModel):
    id: str
    current: bool
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime


class AuthIdentityStatus(BaseModel):
    google_connected: bool
    email_password_connected: bool
    email_verified: bool
    phone_verified: bool = False
    terms_accepted: bool
    privacy_accepted: bool


user_store = UserStore()


def validate_security_settings(config: Settings) -> None:
    """Fail closed for unsafe non-development identity configuration."""

    if config.app_environment != "development" and (
        config.jwt_secret == _LOCAL_JWT_PLACEHOLDER
        or len(config.jwt_secret.encode("utf-8")) < _MINIMUM_HMAC_SECRET_BYTES
    ):
        raise RuntimeError(
            "JWT_SECRET must be replaced with at least 32 random bytes outside development."
        )
    if config.app_environment != "development" and config.jwt_algorithm != "HS256":
        raise RuntimeError("JWT_ALGORITHM must be HS256 outside development.")
    if config.app_environment != "development" and not config.google_server_client_id:
        raise RuntimeError(
            "GOOGLE_SERVER_CLIENT_ID (or GOOGLE_CLIENT_ID) is required outside development."
        )
    if config.app_environment != "development" and config.persistence_backend != "postgres":
        raise RuntimeError("PERSISTENCE_BACKEND=postgres is required outside development.")
    if config.app_environment != "development" and config.rate_limit_backend != "redis":
        raise RuntimeError("RATE_LIMIT_BACKEND=redis is required outside development.")
    if config.app_environment != "development" and (
        not config.cors_origins
        or "*" in config.cors_origins
        or any(not origin.startswith("https://") for origin in config.cors_origins)
    ):
        raise RuntimeError("CORS_ORIGINS must contain explicit HTTPS origins outside development.")
    if (
        config.app_environment != "development"
        and "sslmode=require" not in config.postgres_url.casefold()
    ):
        raise RuntimeError("POSTGRES_URL must require TLS outside development.")
    if config.app_environment != "development" and not config.redis_url.startswith("rediss://"):
        raise RuntimeError("REDIS_URL must use TLS outside development.")
    if config.email_auth_enabled and (
        config.email_provider != "resend" or not config.resend_api_key or not config.email_from
    ):
        raise RuntimeError(
            "Enabled email authentication requires EMAIL_PROVIDER=resend, EMAIL_FROM, "
            "and RESEND_API_KEY."
        )
    if (
        config.email_auth_enabled
        and config.app_environment != "development"
        and not config.public_web_url.startswith("https://")
    ):
        raise RuntimeError("PUBLIC_WEB_URL must use HTTPS outside development.")
    if config.phone_auth_enabled and config.phone_otp_provider == "none":
        raise RuntimeError("Enabled phone authentication requires a production OTP provider.")


def _user_from_record(record: dict[str, Any]) -> User:
    google_subject = record.get("google_subject")
    return User(
        id=str(record["id"]),
        google_subject=str(google_subject) if google_subject else None,
        email=str(record["email"]),
        name=str(record["display_name"]),
        avatar_url=str(record["avatar_url"]) if record.get("avatar_url") else None,
        terms_accepted_at=record.get("terms_accepted_at"),
        privacy_accepted_at=record.get("privacy_accepted_at"),
        plan=PlanCode(str(record["plan_code"])),
        subscription_status=SubscriptionStatus(str(record["subscription_status"])),
        roles=frozenset(SpecialRole(str(role)) for role in record.get("roles", [])),
    )


def _normalize_email(value: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) > 254 or not _EMAIL_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    return normalized


def _validate_password(password: str, *, email: str | None = None) -> None:
    checks = (
        len(password) >= 12,
        len(password) <= 128,
        any(character.islower() for character in password),
        any(character.isupper() for character in password),
        any(character.isdigit() for character in password),
        any(not character.isalnum() for character in password),
    )
    local_part = email.split("@", 1)[0] if email else ""
    if not all(checks) or (len(local_part) >= 4 and local_part in password.casefold()):
        raise HTTPException(
            status_code=422,
            detail=(
                "Use 12–128 characters with uppercase, lowercase, number, and symbol; "
                "do not include your email name."
            ),
        )


def _verify_password(password_hash: str, password: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _new_action_token(
    *, user_id: str, identity_id: str | None, purpose: str, lifetime_minutes: int
) -> str:
    token = secrets.token_urlsafe(32)
    user_store.create_auth_action_token(
        user_id=user_id,
        identity_id=identity_id,
        purpose=purpose,
        token_hash=sha256(token.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(minutes=lifetime_minutes),
    )
    return token


def create_session_token(
    user: User, config: Settings = settings, *, rotated_from: str | None = None
) -> tuple[str, int]:
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=config.jwt_access_token_minutes)
    session_id = uuid4().hex
    token = jwt.encode(
        {
            "sub": user.id,
            "jti": session_id,
            "iss": "nutrilens-x",
            "aud": "nutrilens-x-api",
            "iat": now,
            "exp": expires,
        },
        config.jwt_secret,
        algorithm=config.jwt_algorithm,
    )
    user_store.create_auth_session(
        session_id=session_id,
        user_id=user.id,
        expires_at=expires,
        rotated_from=rotated_from,
    )
    return token, int((expires - now).total_seconds())


def decode_session_claims(token: str, config: Settings = settings) -> dict[str, str]:
    try:
        payload = jwt.decode(
            token,
            config.jwt_secret,
            algorithms=[config.jwt_algorithm],
            audience="nutrilens-x-api",
            issuer="nutrilens-x",
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired session.",
            headers={
                "WWW-Authenticate": 'Bearer error="invalid_token"',
                "X-Auth-Error": "SESSION_EXPIRED",
            },
        ) from exc
    subject = payload.get("sub")
    session_id = payload.get("jti")
    if not isinstance(subject, str) or not subject or not isinstance(session_id, str):
        raise HTTPException(
            status_code=401,
            detail="Invalid session subject.",
            headers={
                "WWW-Authenticate": 'Bearer error="invalid_token"',
                "X-Auth-Error": "SESSION_EXPIRED",
            },
        )
    return {"sub": subject, "jti": session_id}


def decode_session_token(token: str, config: Settings = settings) -> str:
    return decode_session_claims(token, config)["sub"]


def _credentials_claims(
    credentials: HTTPAuthorizationCredentials | None,
) -> dict[str, str]:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=401,
            detail="Authentication required.",
            headers={
                "WWW-Authenticate": 'Bearer error="invalid_token"',
                "X-Auth-Error": "SESSION_EXPIRED",
            },
        )
    claims = decode_session_claims(credentials.credentials)
    if not user_store.auth_session_active(claims["jti"], claims["sub"]):
        raise HTTPException(
            status_code=401,
            detail="Session has been revoked or expired.",
            headers={
                "WWW-Authenticate": 'Bearer error="invalid_token"',
                "X-Auth-Error": "SESSION_EXPIRED",
            },
        )
    return claims


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    claims = _credentials_claims(credentials)
    user = user_store.get(claims["sub"])
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Session user no longer exists.",
            headers={
                "WWW-Authenticate": 'Bearer error="invalid_token"',
                "X-Auth-Error": "SESSION_EXPIRED",
            },
        )
    return user


def optional_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User | None:
    if credentials is None:
        if settings.app_environment == "development":
            return None
        raise HTTPException(status_code=401, detail="Authentication required.")
    return current_user(credentials)


def _public_user(user: User) -> AuthenticatedUser:
    effective = resolve_entitlements(user.plan, user.subscription_status, set(user.roles))
    return AuthenticatedUser(
        id=user.id,
        has_google_identity=user.google_subject is not None,
        email=user.email,
        name=user.name,
        avatar_url=user.avatar_url,
        plan=effective.plan,
        subscription_status=user.subscription_status,
        roles=set(user.roles),
        entitlements=effective.values,
    )


def _session_response(user: User, *, rotated_from: str | None = None) -> SessionResponse:
    token, expires_in = create_session_token(user, rotated_from=rotated_from)
    return SessionResponse(
        access_token=token,
        expires_in_seconds=expires_in,
        user=_public_user(user),
    )


def _email_auth_required() -> None:
    if not settings.email_auth_enabled:
        raise HTTPException(status_code=503, detail="Email authentication is not configured.")


def _verified_google_claims(credential: str) -> dict[str, Any]:
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="Google authentication is not configured.")
    try:
        claims = id_token.verify_oauth2_token(
            credential,
            GoogleRequest(),  # type: ignore[no-untyped-call]
            settings.google_client_id,
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=401, detail="Google credential verification failed."
        ) from exc
    if claims.get("iss") not in {"accounts.google.com", "https://accounts.google.com"}:
        raise HTTPException(status_code=401, detail="Unexpected Google token issuer.")
    if claims.get("email_verified") is not True:
        raise HTTPException(status_code=401, detail="A verified Google email is required.")
    if not claims.get("sub") or not claims.get("email"):
        raise HTTPException(status_code=401, detail="Google identity claims are incomplete.")
    return dict(claims)


@router.get("/capabilities", response_model=AuthCapabilities)
def auth_capabilities() -> AuthCapabilities:
    demo_status = (
        "READY"
        if (
            settings.app_environment in ("local_qa", "development", "test")
            and settings.college_demo_mode
        )
        else "NOT_AVAILABLE"
    )
    return AuthCapabilities(
        google="READY" if settings.google_client_id else "NOT_CONFIGURED",
        # OAuth client IDs identify the public browser application; they are
        # intentionally not secrets and must be supplied to Google Identity
        # Services in the browser at runtime.
        google_client_id=settings.google_client_id or None,
        email="READY" if settings.email_auth_enabled else "NOT_CONFIGURED",
        phone_otp="READY" if settings.phone_auth_enabled else "BLOCKED_EXTERNAL_COST",
        demo_login=demo_status,
    )


@router.post("/demo/login", response_model=SessionResponse)
def demo_login() -> SessionResponse:
    if settings.app_environment not in ("local_qa", "development", "test"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo login is strictly prohibited in non-local environments.",
        )
    if not settings.college_demo_mode:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="College demo mode is not enabled.",
        )
    demo_claims = {
        "sub": "demo-college-qa-user",
        "email": "demouser@college.local",
        "name": "Demo User",
        "picture": None,
    }
    user = user_store.upsert_google_user(demo_claims)
    user_store.record_security_event(user_id=user.id, event_type="college_demo_login_success")
    return _session_response(user)


@router.post("/google", response_model=SessionResponse)
def authenticate_google(payload: GoogleCredentialRequest) -> SessionResponse:
    claims = _verified_google_claims(payload.credential)
    try:
        user = user_store.upsert_google_user(claims)
    except ValueError as e:
        if str(e) == "EMAIL_EXISTS_REQUIRES_LINKING":
            raise HTTPException(
                status_code=409,
                detail=(
                    "An account with this email already exists. Please sign in with your email "
                    "and password, then link your Google account in Settings."
                ),
            ) from e
        raise
    user_store.record_security_event(user_id=user.id, event_type="google_login_success")
    return _session_response(user)


@router.post("/email/signup", response_model=MessageResponse, status_code=status.HTTP_202_ACCEPTED)
def email_signup(payload: EmailSignupRequest) -> MessageResponse:
    _email_auth_required()
    email = _normalize_email(payload.email)
    _validate_password(payload.password, email=email)
    result = user_store.register_email_user(
        email=email,
        display_name=payload.name.strip(),
        password_hash=_password_hasher.hash(payload.password),
        legal_accepted=True,
    )
    if not result["verified"]:
        otp = f"{secrets.randbelow(1_000_000):06d}"
        otp_hash = sha256(otp.encode()).hexdigest()
        user_store.create_email_otp_challenge(
            email=email,
            user_id=result["user"].id,
            identity_id=result["identity_id"],
            otp_hash=otp_hash,
        )
        token = _new_action_token(
            user_id=result["user"].id,
            identity_id=result["identity_id"],
            purpose="verify_email",
            lifetime_minutes=settings.email_verification_minutes,
        )
        try:
            send_verification_email(
                email=email,
                display_name=result["user"].name,
                token=token,
                otp=otp,
            )
        except EmailDeliveryError as exc:
            raise HTTPException(
                status_code=503,
                detail="Verification email delivery is temporarily unavailable.",
            ) from exc
    user_store.record_security_event(
        user_id=result["user"].id,
        event_type="email_signup_requested",
        metadata={"credential_created": bool(result["credential_created"])},
    )
    return MessageResponse(
        message="If the address can be registered, a verification email has been sent."
    )


@router.get("/identities", response_model=AuthIdentityStatus)
def get_auth_identities(user: Annotated[User, Depends(current_user)]) -> AuthIdentityStatus:
    identity = user_store.identity_status(user.id)
    return AuthIdentityStatus(
        **identity,
        terms_accepted=user.terms_accepted_at is not None,
        privacy_accepted=user.privacy_accepted_at is not None,
    )


@router.post("/identities/google/connect", response_model=AuthIdentityStatus)
@router.post("/google/link", response_model=AuthIdentityStatus)
def connect_google_identity(
    payload: GoogleCredentialRequest,
    user: Annotated[User, Depends(current_user)],
) -> AuthIdentityStatus:
    claims = _verified_google_claims(payload.credential)
    outcome = user_store.connect_google_identity(user.id, claims)
    errors = {
        "EMAIL_MISMATCH": (409, "Choose the Google account with the same verified email."),
        "ALREADY_LINKED": (409, "That Google identity is linked to another account."),
        "DIFFERENT_GOOGLE_CONNECTED": (409, "A different Google identity is already connected."),
        "NOT_FOUND": (404, "Account not found."),
    }
    if outcome in errors:
        code, detail = errors[outcome]
        raise HTTPException(status_code=code, detail=detail)
    user_store.record_security_event(user_id=user.id, event_type="google_identity_connected")
    return get_auth_identities(user_store.get(user.id) or user)


@router.delete("/identities/google", response_model=AuthIdentityStatus)
@router.post("/google/unlink", response_model=AuthIdentityStatus)
def disconnect_google_identity(
    user: Annotated[User, Depends(current_user)],
) -> AuthIdentityStatus:
    outcome = user_store.disconnect_google_identity(user.id)
    if outcome == "SOLE_LOGIN":
        raise HTTPException(
            status_code=409,
            detail="Add and verify an email/password login before disconnecting Google.",
        )
    if outcome in {"NOT_CONNECTED", "NOT_FOUND"}:
        raise HTTPException(status_code=404, detail="Connected Google identity not found.")
    user_store.record_security_event(user_id=user.id, event_type="google_identity_disconnected")
    return get_auth_identities(user_store.get(user.id) or user)


@router.post(
    "/identities/email/password",
    response_model=MessageResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def add_email_password_identity(
    payload: AddPasswordRequest,
    user: Annotated[User, Depends(current_user)],
) -> MessageResponse:
    _email_auth_required()
    _validate_password(payload.password, email=user.email)
    existing = user_store.get_email_credential(user.email)
    if existing is not None and existing.get("verified_email"):
        raise HTTPException(
            status_code=409,
            detail="Email/password is already connected. Use Change password instead.",
        )
    result = user_store.register_email_user(
        email=user.email,
        display_name=user.name,
        password_hash=_password_hasher.hash(payload.password),
        legal_accepted=True,
    )
    if not result["credential_created"]:
        user_store.update_password(
            str(result["identity_id"]), _password_hasher.hash(payload.password)
        )
    token = _new_action_token(
        user_id=user.id,
        identity_id=str(result["identity_id"]),
        purpose="verify_email",
        lifetime_minutes=settings.email_verification_minutes,
    )
    try:
        send_verification_email(email=user.email, display_name=user.name, token=token)
    except EmailDeliveryError as exc:
        raise HTTPException(
            status_code=503,
            detail="Verification email delivery is temporarily unavailable.",
        ) from exc
    user_store.record_security_event(user_id=user.id, event_type="email_identity_added")
    return MessageResponse(message="Check your inbox to verify the email/password login.")


@router.post("/email/verify", response_model=SessionResponse)
def verify_email(payload: TokenRequest) -> SessionResponse:
    _email_auth_required()
    record = user_store.consume_auth_action_token(
        purpose="verify_email", token_hash=sha256(payload.token.encode()).hexdigest()
    )
    if record is None or not record.get("identity_id"):
        raise HTTPException(status_code=400, detail="Verification link is invalid or expired.")
    user = user_store.verify_email_identity(str(record["identity_id"]))
    user_store.record_security_event(user_id=user.id, event_type="email_verified")
    return _session_response(user)


@router.post("/email/login", response_model=SessionResponse)
def email_login(payload: EmailLoginRequest) -> SessionResponse:
    _email_auth_required()
    email = _normalize_email(payload.email)
    record = user_store.get_email_credential(email)
    if record is None:
        _verify_password(_DUMMY_PASSWORD_HASH, payload.password)
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    locked_until = record.get("locked_until")
    if isinstance(locked_until, datetime) and locked_until > datetime.now(UTC):
        raise HTTPException(
            status_code=429,
            detail="Sign-in is temporarily locked. Try again later or reset your password.",
        )
    if not _verify_password(str(record["password_hash"]), payload.password):
        user_store.mark_email_login_failure(
            str(record["identity_id"]),
            maximum_attempts=settings.auth_max_password_attempts,
            locked_until=datetime.now(UTC) + timedelta(minutes=settings.auth_lock_minutes),
        )
        user_store.record_security_event(user_id=str(record["id"]), event_type="email_login_failed")
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    if not record.get("verified_email"):
        raise HTTPException(status_code=403, detail="Verify your email before signing in.")
    user_store.mark_email_login_success(str(record["identity_id"]))
    user = _user_from_record(record)
    user_store.record_security_event(user_id=user.id, event_type="email_login_success")
    return _session_response(user)


@router.post("/email/resend-verification", response_model=MessageResponse)
def resend_verification(payload: ForgotPasswordRequest) -> MessageResponse:
    _email_auth_required()
    email = _normalize_email(payload.email)
    record = user_store.get_email_credential(email)
    if record is not None and not record.get("verified_email"):
        token = _new_action_token(
            user_id=str(record["id"]),
            identity_id=str(record["identity_id"]),
            purpose="verify_email",
            lifetime_minutes=settings.email_verification_minutes,
        )
        try:
            send_verification_email(
                email=email, display_name=str(record["display_name"]), token=token
            )
        except EmailDeliveryError as exc:
            raise HTTPException(
                status_code=503,
                detail="Verification email delivery is temporarily unavailable.",
            ) from exc
    return MessageResponse(message="If verification is pending, a new email has been sent.")


@router.post("/password/forgot", response_model=MessageResponse)
def forgot_password(payload: ForgotPasswordRequest) -> MessageResponse:
    _email_auth_required()
    email = _normalize_email(payload.email)
    record = user_store.get_email_credential(email)
    if record is not None and record.get("verified_email"):
        token = _new_action_token(
            user_id=str(record["id"]),
            identity_id=str(record["identity_id"]),
            purpose="reset_password",
            lifetime_minutes=settings.password_reset_minutes,
        )
        try:
            send_password_reset_email(
                email=email, display_name=str(record["display_name"]), token=token
            )
        except EmailDeliveryError as exc:
            raise HTTPException(
                status_code=503,
                detail="Password reset email delivery is temporarily unavailable.",
            ) from exc
    return MessageResponse(message="If the account exists, a password reset email has been sent.")


@router.post("/password/reset", response_model=MessageResponse)
def reset_password(payload: ResetPasswordRequest) -> MessageResponse:
    _email_auth_required()
    _validate_password(payload.password)
    record = user_store.consume_auth_action_token(
        purpose="reset_password", token_hash=sha256(payload.token.encode()).hexdigest()
    )
    if record is None or not record.get("identity_id"):
        raise HTTPException(status_code=400, detail="Reset link is invalid or expired.")
    user_store.update_password(str(record["identity_id"]), _password_hasher.hash(payload.password))
    user_store.revoke_user_sessions(str(record["user_id"]))
    user_store.record_security_event(user_id=str(record["user_id"]), event_type="password_reset")
    return MessageResponse(message="Password updated. Sign in with your new password.")


@router.post("/password/change", response_model=SessionResponse)
def change_password(
    payload: ChangePasswordRequest,
    user: Annotated[User, Depends(current_user)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> SessionResponse:
    _email_auth_required()
    _validate_password(payload.new_password, email=user.email)
    record = user_store.get_email_credential(user.email)
    if record is None or not _verify_password(
        str(record["password_hash"]), payload.current_password
    ):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")
    claims = _credentials_claims(credentials)
    user_store.update_password(
        str(record["identity_id"]), _password_hasher.hash(payload.new_password)
    )
    user_store.revoke_user_sessions(user.id)
    user_store.record_security_event(user_id=user.id, event_type="password_changed")
    return _session_response(user, rotated_from=claims["jti"])


@router.post("/session/refresh", response_model=SessionResponse)
def refresh_session(
    user: Annotated[User, Depends(current_user)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> SessionResponse:
    claims = _credentials_claims(credentials)
    user_store.revoke_auth_session(claims["jti"])
    user_store.record_security_event(user_id=user.id, event_type="session_rotated")
    return _session_response(user, rotated_from=claims["jti"])


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def logout(
    user: Annotated[User, Depends(current_user)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Response:
    claims = _credentials_claims(credentials)
    user_store.revoke_auth_session(claims["jti"])
    user_store.record_security_event(user_id=user.id, event_type="session_logout")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=AuthenticatedUser)
def get_me(user: Annotated[User, Depends(current_user)]) -> AuthenticatedUser:
    return _public_user(user)


@router.get("/sessions", response_model=list[AuthSessionSummary])
def list_sessions(
    user: Annotated[User, Depends(current_user)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> list[AuthSessionSummary]:
    claims = _credentials_claims(credentials)
    return sorted(
        [
            AuthSessionSummary(
                id=str(record["id"]),
                current=str(record["id"]) == claims["jti"],
                created_at=record["created_at"],
                last_seen_at=record["last_seen_at"],
                expires_at=record["expires_at"],
            )
            for record in user_store.list_active_sessions(user.id)
        ],
        key=lambda item: (not item.current, -item.last_seen_at.timestamp()),
    )


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def revoke_session(
    session_id: str,
    user: Annotated[User, Depends(current_user)],
) -> Response:
    if not user_store.revoke_owned_session(user.id, session_id):
        raise HTTPException(status_code=404, detail="Active session not found.")
    user_store.record_security_event(user_id=user.id, event_type="session_revoked")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/email/otp/request", response_model=MessageResponse)
def request_email_otp(payload: EmailOtpRequest) -> MessageResponse:
    _email_auth_required()
    email = _normalize_email(payload.email)
    record = user_store.get_email_credential(email)
    if record is None:
        return MessageResponse(
            message="If the address can be registered, a verification code has been sent."
        )
    if record.get("verified_email"):
        return MessageResponse(message="Email is already verified. Sign in with your password.")
    if user_store.check_email_otp_resend_cooldown(email):
        raise HTTPException(
            status_code=429,
            detail="Please wait before requesting another verification code.",
        )
    otp = f"{secrets.randbelow(1_000_000):06d}"
    otp_hash = sha256(otp.encode()).hexdigest()
    user_store.create_email_otp_challenge(
        email=email,
        user_id=str(record["id"]),
        identity_id=str(record["identity_id"]),
        otp_hash=otp_hash,
    )
    try:
        send_otp_email(
            email=email,
            display_name=str(record.get("display_name") or email),
            otp=otp,
        )
    except EmailDeliveryError as exc:
        raise HTTPException(
            status_code=503,
            detail="Verification email delivery is temporarily unavailable.",
        ) from exc
    return MessageResponse(message="A new verification code has been sent to your email.")


@router.post("/email/otp/verify", response_model=SessionResponse)
def verify_email_otp(payload: EmailOtpVerifyRequest) -> SessionResponse:
    _email_auth_required()
    email = _normalize_email(payload.email)
    otp_clean = payload.otp.strip()
    if len(otp_clean) != 6 or not otp_clean.isdigit():
        raise HTTPException(status_code=422, detail="Enter a 6-digit verification code.")
    user, status_code = user_store.verify_email_otp(
        email=email, otp_hash=sha256(otp_clean.encode()).hexdigest()
    )
    if status_code == "WRONG_CODE":
        raise HTTPException(status_code=401, detail="Incorrect verification code.")
    if status_code == "TOO_MANY_ATTEMPTS":
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Please request a new verification code.",
        )
    if status_code in ("EXPIRED_OR_INVALID", "USER_NOT_FOUND") or user is None:
        raise HTTPException(
            status_code=400,
            detail="Verification code has expired or is invalid. Request a new code.",
        )
    user_store.record_security_event(user_id=user.id, event_type="email_otp_verified")
    return _session_response(user)


def _verified_firebase_phone_claims(credential: str, expected_phone: str) -> dict[str, Any]:
    project_id = (settings.firebase_project_id or "").strip()
    if not project_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firebase Phone Authentication is not configured on this server.",
        )
    try:
        claims = id_token.verify_firebase_token(
            credential,
            GoogleRequest(),  # type: ignore[no-untyped-call]
            audience=project_id,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=401, detail="Firebase phone token verification failed."
        ) from exc
    token_phone = claims.get("phone_number")
    if not token_phone:
        raise HTTPException(
            status_code=401, detail="Token does not contain a verified phone number."
        )
    if token_phone != expected_phone:
        raise HTTPException(
            status_code=400, detail="Token phone number does not match expected phone."
        )
    return dict(claims)


@router.post("/phone/request", response_model=MessageResponse)
def request_phone_otp(payload: PhoneOtpRequest) -> MessageResponse:
    if not _PHONE_PATTERN.fullmatch(payload.phone.strip()):
        raise HTTPException(status_code=422, detail="Use an E.164 mobile number with country code.")
    if not settings.phone_auth_enabled:
        raise HTTPException(
            status_code=503,
            detail="BLOCKED_EXTERNAL_COST: production SMS delivery is not enabled.",
        )
    raise HTTPException(status_code=503, detail="Configured OTP provider is unavailable.")


@router.post("/phone/verify", response_model=SessionResponse)
def verify_phone_otp(payload: PhoneOtpVerifyRequest) -> SessionResponse:
    phone = payload.phone.strip()
    if not _PHONE_PATTERN.fullmatch(phone):
        raise HTTPException(status_code=422, detail="Use an E.164 mobile number with country code.")
    if payload.firebase_id_token:
        claims = _verified_firebase_phone_claims(payload.firebase_id_token, phone)
        provider_sub = str(claims["sub"])
        # Find existing user by phone identity or create/link
        existing_user: User | None = None
        if postgres_store is not None:
            user_record = postgres_store.get_user_by_phone(
                provider_subject=provider_sub, phone_e164=phone
            )
            if user_record:
                existing_user = _user_from_record(user_record)
        else:
            uid = user_store._verified_phones.get(phone)
            if uid:
                existing_user = user_store.get(uid)
        if existing_user is None:
            raise HTTPException(
                status_code=404,
                detail="No account linked to this phone. Please sign in and link your phone.",
            )
        user_store.record_security_event(user_id=existing_user.id, event_type="phone_login_success")
        return _session_response(existing_user)
    if not settings.phone_auth_enabled:
        raise HTTPException(
            status_code=503,
            detail="BLOCKED_EXTERNAL_COST: production SMS delivery is not enabled.",
        )
    raise HTTPException(status_code=503, detail="Configured OTP provider is unavailable.")


@router.post("/identities/phone/connect", response_model=AuthIdentityStatus)
@router.post("/phone/link", response_model=AuthIdentityStatus)
def connect_phone_identity(
    payload: PhoneVerificationProofRequest,
    user: Annotated[User, Depends(current_user)],
) -> AuthIdentityStatus:
    phone = payload.phone.strip()
    if not _PHONE_PATTERN.fullmatch(phone):
        raise HTTPException(status_code=422, detail="Use an E.164 mobile number with country code.")
    claims = _verified_firebase_phone_claims(payload.firebase_id_token, phone)
    provider_sub = str(claims["sub"])
    updated_user, outcome = user_store.link_phone_identity(
        user.id, phone_e164=phone, provider_subject=provider_sub
    )
    if outcome == "PHONE_ALREADY_LINKED":
        raise HTTPException(
            status_code=409, detail="That phone number is already linked to another account."
        )
    if outcome != "SUCCESS" or updated_user is None:
        raise HTTPException(status_code=400, detail="Failed to link phone identity.")
    from backend.product_api import AccountProfileRecord, product_store

    existing_profile = product_store.get_account_profile(user.id, user.name)
    verified_profile = AccountProfileRecord(
        full_name=existing_profile.full_name,
        date_of_birth=existing_profile.date_of_birth,
        phone_number=phone,
        phone_state="VERIFIED",
        country_region=existing_profile.country_region,
        unit_system=existing_profile.unit_system,
        research_insights_consent=existing_profile.research_insights_consent,
        onboarding_completed_at=existing_profile.onboarding_completed_at,
    )
    product_store.put_account_profile(user.id, verified_profile)
    user_store.record_security_event(user_id=user.id, event_type="phone_identity_connected")
    return get_auth_identities(user_store.get(user.id) or user)
