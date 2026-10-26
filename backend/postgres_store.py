"""Typed PostgreSQL persistence used in public mode."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ai.food_understanding.schemas import R3ScanResult


class ScanJobQuotaExceeded(RuntimeError):
    """Raised when a new durable scan job would exceed the monthly allowance."""


def _payment_transition_allowed(current: str, target: str, event_type: str) -> bool:
    if event_type.startswith("owner.subscription."):
        return True
    allowed = {
        "CREATED": {"CREATED", "AUTHENTICATING", "ACTIVE", "CANCELLED"},
        "AUTHENTICATING": {"AUTHENTICATING", "ACTIVE", "PAST_DUE", "CANCELLED"},
        "ACTIVE": {"ACTIVE", "PAST_DUE", "PAUSED", "CANCELLED"},
        "PAST_DUE": {"PAST_DUE", "ACTIVE", "PAUSED", "CANCELLED"},
        "PAUSED": {"PAUSED", "ACTIVE", "CANCELLED"},
        "CANCELLED": {"CANCELLED"},
        "EXPIRED": {"EXPIRED"},
        "FREE": {"FREE"},
    }
    return target in allowed.get(current, {current})


class PostgresStore:
    def __init__(self, url: str) -> None:
        self.url = url

    def migrate(self) -> None:
        with psycopg.connect(self.url) as connection:
            for migration in sorted(Path("backend/migrations").glob("*.sql")):
                connection.execute(migration.read_text(encoding="utf-8"))

    def upsert_google_user(self, claims: Mapping[str, Any]) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            subject = str(claims["sub"])
            email = str(claims["email"]).strip().casefold()
            display_name = str(claims.get("name") or claims["email"])
            avatar_url = str(claims["picture"]) if claims.get("picture") else None
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (email,))
            row = connection.execute(
                """
                SELECT users.* FROM auth_identities
                JOIN users ON users.id = auth_identities.user_id
                WHERE auth_identities.provider = 'google'
                  AND auth_identities.provider_subject = %s
                FOR UPDATE OF users
                """,
                (subject,),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT * FROM users WHERE lower(email) = %s FOR UPDATE", (email,)
                ).fetchone()
            if row is None:
                row = connection.execute(
                    """
                    INSERT INTO users (
                        id, google_subject, email, display_name, avatar_url, email_verified_at
                    ) VALUES (%s, %s, %s, %s, %s, now())
                    RETURNING *
                    """,
                    (str(uuid4()), subject, email, display_name, avatar_url),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    UPDATE users SET
                        google_subject = COALESCE(google_subject, %s),
                        email = %s,
                        avatar_url = COALESCE(%s, avatar_url),
                        email_verified_at = COALESCE(email_verified_at, now()),
                        updated_at = now()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (subject, email, avatar_url, str(row["id"])),
                ).fetchone()
            if row is None:
                raise RuntimeError("Google user upsert returned no record.")
            connection.execute(
                """
                INSERT INTO auth_identities (
                    id, user_id, provider, provider_subject, verified_email, last_login_at
                ) VALUES (%s, %s, 'google', %s, %s, now())
                ON CONFLICT (provider, provider_subject) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    verified_email = EXCLUDED.verified_email,
                    last_login_at = now()
                """,
                (str(uuid4()), str(row["id"]), subject, email),
            )
        if row is None:
            raise RuntimeError("User upsert returned no record.")
        return dict(row)

    def register_email_user(
        self,
        *,
        email: str,
        display_name: str,
        password_hash: str,
        legal_accepted: bool = False,
    ) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (email,))
            user = connection.execute(
                "SELECT * FROM users WHERE lower(email) = %s FOR UPDATE", (email,)
            ).fetchone()
            if user is None:
                user = connection.execute(
                    """
                    INSERT INTO users (
                        id, google_subject, email, display_name,
                        terms_accepted_at, privacy_accepted_at
                    )
                    VALUES (
                        %s, NULL, %s, %s,
                        CASE WHEN %s THEN now() END,
                        CASE WHEN %s THEN now() END
                    )
                    RETURNING *
                    """,
                    (str(uuid4()), email, display_name, legal_accepted, legal_accepted),
                ).fetchone()
            if user is None:
                raise RuntimeError("Email user insert returned no record.")
            identity = connection.execute(
                """
                SELECT * FROM auth_identities
                WHERE provider = 'email' AND provider_subject = %s
                FOR UPDATE
                """,
                (email,),
            ).fetchone()
            if identity is None:
                identity = connection.execute(
                    """
                    INSERT INTO auth_identities (id, user_id, provider, provider_subject)
                    VALUES (%s, %s, 'email', %s)
                    RETURNING *
                    """,
                    (str(uuid4()), str(user["id"]), email),
                ).fetchone()
            if identity is None:
                raise RuntimeError("Email identity insert returned no record.")
            existing_credential = connection.execute(
                "SELECT identity_id FROM password_credentials WHERE identity_id = %s",
                (str(identity["id"]),),
            ).fetchone()
            created = existing_credential is None
            if created:
                connection.execute(
                    """
                    INSERT INTO password_credentials (identity_id, password_hash)
                    VALUES (%s, %s)
                    """,
                    (str(identity["id"]), password_hash),
                )
            return {
                "user": dict(user),
                "identity_id": str(identity["id"]),
                "credential_created": created,
                "verified": identity.get("verified_email") is not None,
            }

    def accept_user_legal(self, user_id: str) -> dict[str, Any] | None:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE users SET
                    terms_accepted_at = COALESCE(terms_accepted_at, now()),
                    privacy_accepted_at = COALESCE(privacy_accepted_at, now()),
                    updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_auth_identity_status(self, user_id: str) -> dict[str, bool]:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT
                    EXISTS (
                        SELECT 1 FROM auth_identities
                        WHERE user_id = %s AND provider = 'google'
                    ) AS google_connected,
                    EXISTS (
                        SELECT 1 FROM auth_identities
                        JOIN password_credentials
                          ON password_credentials.identity_id = auth_identities.id
                        WHERE auth_identities.user_id = %s
                          AND auth_identities.provider = 'email'
                    ) AS email_password_connected,
                    EXISTS (
                        SELECT 1 FROM auth_identities
                        JOIN password_credentials
                          ON password_credentials.identity_id = auth_identities.id
                        WHERE auth_identities.user_id = %s
                          AND auth_identities.provider = 'email'
                          AND auth_identities.verified_email IS NOT NULL
                    ) AS email_verified,
                    EXISTS (
                        SELECT 1 FROM auth_identities
                        WHERE user_id = %s AND provider = 'phone'
                          AND verified_phone IS NOT NULL
                    ) AS phone_verified
                """,
                (user_id, user_id, user_id, user_id),
            ).fetchone()
        return {
            "google_connected": bool(row and row["google_connected"]),
            "email_password_connected": bool(row and row["email_password_connected"]),
            "email_verified": bool(row and row["email_verified"]),
            "phone_verified": bool(row and row["phone_verified"]),
        }

    def link_phone_identity(
        self, user_id: str, *, phone_e164: str, provider_subject: str
    ) -> tuple[dict[str, Any] | None, str]:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (phone_e164,))
            user = connection.execute(
                "SELECT * FROM users WHERE id = %s FOR UPDATE", (user_id,)
            ).fetchone()
            if user is None:
                return None, "USER_NOT_FOUND"
            existing = connection.execute(
                """
                SELECT user_id FROM auth_identities
                WHERE (provider = 'phone' AND provider_subject = %s)
                   OR (verified_phone = %s)
                FOR UPDATE
                """,
                (provider_subject, phone_e164),
            ).fetchone()
            if existing is not None and str(existing["user_id"]) != user_id:
                return None, "PHONE_ALREADY_LINKED"

            identity_id = str(uuid4())
            connection.execute(
                """
                INSERT INTO auth_identities (
                    id, user_id, provider, provider_subject, verified_phone, last_login_at
                ) VALUES (%s, %s, 'phone', %s, %s, now())
                ON CONFLICT (provider, provider_subject) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    verified_phone = EXCLUDED.verified_phone,
                    last_login_at = now()
                """,
                (identity_id, user_id, provider_subject, phone_e164),
            )
            # Update account profile phone state to VERIFIED
            prof_row = connection.execute(
                "SELECT payload FROM account_profiles WHERE user_id = %s FOR UPDATE", (user_id,)
            ).fetchone()
            if prof_row and prof_row.get("payload"):
                prof = dict(prof_row["payload"])
                prof["phone_number"] = phone_e164
                prof["phone_state"] = "VERIFIED"
                connection.execute(
                    """
                    UPDATE account_profiles
                    SET payload = %s, updated_at = now()
                    WHERE user_id = %s
                    """,
                    (Jsonb(prof), user_id),
                )
            else:
                default_prof = {
                    "full_name": str(user["display_name"]),
                    "date_of_birth": None,
                    "phone_number": phone_e164,
                    "phone_state": "VERIFIED",
                    "country_region": None,
                    "unit_system": "METRIC",
                    "research_insights_consent": False,
                    "onboarding_completed_at": None,
                }
                connection.execute(
                    """
                    INSERT INTO account_profiles (user_id, payload) VALUES (%s, %s)
                    ON CONFLICT (user_id)
                    DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                    """,
                    (user_id, Jsonb(default_prof)),
                )
            return dict(user), "SUCCESS"

    def get_user_by_phone(self, *, provider_subject: str, phone_e164: str) -> dict[str, Any] | None:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT users.* FROM auth_identities
                JOIN users ON users.id = auth_identities.user_id
                WHERE auth_identities.provider = 'phone'
                  AND (auth_identities.provider_subject = %s
                       OR auth_identities.verified_phone = %s)
                """,
                (provider_subject, phone_e164),
            ).fetchone()
        return dict(row) if row else None

    def connect_google_identity(self, user_id: str, claims: Mapping[str, Any]) -> str:
        subject = str(claims["sub"])
        email = str(claims["email"]).strip().casefold()
        avatar_url = str(claims["picture"]) if claims.get("picture") else None
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (subject,))
            user = connection.execute(
                "SELECT * FROM users WHERE id = %s FOR UPDATE", (user_id,)
            ).fetchone()
            if user is None:
                return "NOT_FOUND"
            if str(user["email"]).casefold() != email:
                return "EMAIL_MISMATCH"
            attached = connection.execute(
                """
                SELECT user_id FROM auth_identities
                WHERE provider = 'google' AND provider_subject = %s
                FOR UPDATE
                """,
                (subject,),
            ).fetchone()
            if attached is not None and str(attached["user_id"]) != user_id:
                return "ALREADY_LINKED"
            different = connection.execute(
                """
                SELECT id FROM auth_identities
                WHERE user_id = %s AND provider = 'google' AND provider_subject <> %s
                FOR UPDATE
                """,
                (user_id, subject),
            ).fetchone()
            if different is not None:
                return "DIFFERENT_GOOGLE_CONNECTED"
            connection.execute(
                """
                INSERT INTO auth_identities (
                    id, user_id, provider, provider_subject, verified_email, last_login_at
                ) VALUES (%s, %s, 'google', %s, %s, now())
                ON CONFLICT (provider, provider_subject) DO UPDATE SET
                    verified_email = EXCLUDED.verified_email,
                    last_login_at = now()
                """,
                (str(uuid4()), user_id, subject, email),
            )
            connection.execute(
                """
                UPDATE users SET
                    google_subject = %s,
                    avatar_url = COALESCE(%s, avatar_url),
                    email_verified_at = COALESCE(email_verified_at, now()),
                    updated_at = now()
                WHERE id = %s
                """,
                (subject, avatar_url, user_id),
            )
        return "CONNECTED"

    def disconnect_google_identity(self, user_id: str) -> str:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            user = connection.execute(
                "SELECT google_subject FROM users WHERE id = %s FOR UPDATE", (user_id,)
            ).fetchone()
            if user is None:
                return "NOT_FOUND"
            connected = connection.execute(
                """
                SELECT id FROM auth_identities
                WHERE user_id = %s AND provider = 'google'
                FOR UPDATE
                """,
                (user_id,),
            ).fetchone()
            if connected is None:
                return "NOT_CONNECTED"
            verified_password = connection.execute(
                """
                SELECT 1 FROM auth_identities
                JOIN password_credentials
                  ON password_credentials.identity_id = auth_identities.id
                WHERE auth_identities.user_id = %s
                  AND auth_identities.provider = 'email'
                  AND auth_identities.verified_email IS NOT NULL
                """,
                (user_id,),
            ).fetchone()
            if verified_password is None:
                return "SOLE_LOGIN"
            connection.execute(
                "DELETE FROM auth_identities WHERE user_id = %s AND provider = 'google'",
                (user_id,),
            )
            connection.execute(
                "UPDATE users SET google_subject = NULL, updated_at = now() WHERE id = %s",
                (user_id,),
            )
        return "DISCONNECTED"

    def get_email_credential(self, email: str) -> dict[str, Any] | None:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT
                    users.*,
                    auth_identities.id AS identity_id,
                    auth_identities.verified_email,
                    password_credentials.password_hash,
                    password_credentials.failed_attempts,
                    password_credentials.locked_until
                FROM auth_identities
                JOIN users ON users.id = auth_identities.user_id
                JOIN password_credentials
                    ON password_credentials.identity_id = auth_identities.id
                WHERE auth_identities.provider = 'email'
                  AND auth_identities.provider_subject = %s
                """,
                (email,),
            ).fetchone()
        return dict(row) if row else None

    def mark_email_login_success(self, identity_id: str) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                UPDATE password_credentials
                SET failed_attempts = 0, locked_until = NULL, updated_at = now()
                WHERE identity_id = %s
                """,
                (identity_id,),
            )
            connection.execute(
                "UPDATE auth_identities SET last_login_at = now() WHERE id = %s",
                (identity_id,),
            )

    def mark_email_login_failure(
        self, identity_id: str, *, maximum_attempts: int, locked_until: datetime
    ) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                UPDATE password_credentials SET
                    failed_attempts = failed_attempts + 1,
                    locked_until = CASE
                        WHEN failed_attempts + 1 >= %s THEN %s
                        ELSE locked_until
                    END,
                    updated_at = now()
                WHERE identity_id = %s
                """,
                (maximum_attempts, locked_until, identity_id),
            )

    def create_auth_action_token(
        self,
        *,
        user_id: str,
        identity_id: str | None,
        purpose: str,
        token_hash: str,
        expires_at: datetime,
    ) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                UPDATE auth_action_tokens SET consumed_at = now()
                WHERE user_id = %s AND purpose = %s AND consumed_at IS NULL
                """,
                (user_id, purpose),
            )
            connection.execute(
                """
                INSERT INTO auth_action_tokens (
                    id, user_id, identity_id, purpose, token_hash, expires_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (str(uuid4()), user_id, identity_id, purpose, token_hash, expires_at),
            )

    def consume_auth_action_token(self, *, purpose: str, token_hash: str) -> dict[str, Any] | None:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT * FROM auth_action_tokens
                WHERE purpose = %s AND token_hash = %s
                  AND consumed_at IS NULL AND expires_at > now()
                FOR UPDATE
                """,
                (purpose, token_hash),
            ).fetchone()
            if row is None:
                return None
            result = connection.execute(
                """
                UPDATE auth_action_tokens SET consumed_at = now()
                WHERE id = %s AND consumed_at IS NULL
                RETURNING *
                """,
                (str(row["id"]),),
            ).fetchone()
            return dict(result) if result else None

    def verify_email_identity(self, identity_id: str) -> dict[str, Any]:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            identity = connection.execute(
                """
                UPDATE auth_identities
                SET verified_email = provider_subject, last_login_at = now()
                WHERE id = %s AND provider = 'email'
                RETURNING user_id, verified_email
                """,
                (identity_id,),
            ).fetchone()
            if identity is None:
                raise RuntimeError("Email identity no longer exists.")
            row = connection.execute(
                """
                UPDATE users SET email_verified_at = COALESCE(email_verified_at, now())
                WHERE id = %s
                RETURNING *
                """,
                (str(identity["user_id"]),),
            ).fetchone()
        if row is None:
            raise RuntimeError("Verified email user no longer exists.")
        return dict(row)

    def update_password(self, identity_id: str, password_hash: str) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                UPDATE password_credentials SET
                    password_hash = %s,
                    failed_attempts = 0,
                    locked_until = NULL,
                    password_changed_at = now(),
                    updated_at = now()
                WHERE identity_id = %s
                """,
                (password_hash, identity_id),
            )

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
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            connection.execute(
                """
                UPDATE email_otp_challenges SET consumed_at = now()
                WHERE lower(email) = lower(%s) AND consumed_at IS NULL
                """,
                (email,),
            )
            row = connection.execute(
                """
                INSERT INTO email_otp_challenges (
                    id, email, user_id, identity_id, otp_hash, expires_at, resend_after
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    now() + (%s * interval '1 minute'),
                    now() + (%s * interval '1 second')
                )
                RETURNING *
                """,
                (
                    str(uuid4()),
                    email,
                    user_id,
                    identity_id,
                    otp_hash,
                    lifetime_minutes,
                    cooldown_seconds,
                ),
            ).fetchone()
            if row is None:
                raise RuntimeError("Failed to create email OTP challenge.")
            return dict(row)

    def verify_email_otp(
        self, *, email: str, otp_hash: str, max_attempts: int = 5
    ) -> tuple[dict[str, Any] | None, str]:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"email-otp:{email.lower()}",),
            )
            row = connection.execute(
                """
                SELECT * FROM email_otp_challenges
                WHERE lower(email) = lower(%s) AND consumed_at IS NULL
                ORDER BY created_at DESC LIMIT 1 FOR UPDATE
                """,
                (email,),
            ).fetchone()
            if row is None or row["expires_at"] <= datetime.now(UTC):
                if row is not None:
                    connection.execute(
                        "UPDATE email_otp_challenges SET consumed_at = now() WHERE id = %s",
                        (row["id"],),
                    )
                return None, "EXPIRED_OR_INVALID"
            if int(row["attempts"]) >= max_attempts:
                connection.execute(
                    "UPDATE email_otp_challenges SET consumed_at = now() WHERE id = %s",
                    (row["id"],),
                )
                return None, "TOO_MANY_ATTEMPTS"
            if row["otp_hash"] != otp_hash:
                new_attempts = int(row["attempts"]) + 1
                if new_attempts >= max_attempts:
                    connection.execute(
                        """
                        UPDATE email_otp_challenges
                        SET attempts = %s, consumed_at = now()
                        WHERE id = %s
                        """,
                        (new_attempts, row["id"]),
                    )
                    return None, "TOO_MANY_ATTEMPTS"
                connection.execute(
                    "UPDATE email_otp_challenges SET attempts = %s WHERE id = %s",
                    (new_attempts, row["id"]),
                )
                return None, "WRONG_CODE"

            connection.execute(
                "UPDATE email_otp_challenges SET consumed_at = now() WHERE id = %s",
                (row["id"],),
            )
            connection.execute(
                """
                UPDATE auth_identities
                SET verified_email = provider_subject, last_login_at = now()
                WHERE id = %s AND provider = 'email'
                """,
                (row["identity_id"],),
            )
            user_row = connection.execute(
                """
                UPDATE users SET email_verified_at = COALESCE(email_verified_at, now())
                WHERE id = %s
                RETURNING *
                """,
                (row["user_id"],),
            ).fetchone()
            if user_row is None:
                return None, "USER_NOT_FOUND"
            return dict(user_row), "SUCCESS"

    def check_email_otp_resend_cooldown(self, email: str) -> bool:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT resend_after FROM email_otp_challenges
                WHERE lower(email) = lower(%s)
                  AND consumed_at IS NULL
                  AND resend_after > now()
                ORDER BY created_at DESC LIMIT 1
                """,
                (email,),
            ).fetchone()
            return row is not None

    def create_auth_session(
        self, *, session_id: str, user_id: str, expires_at: datetime, rotated_from: str | None
    ) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                INSERT INTO auth_sessions (id, user_id, expires_at, rotated_from)
                VALUES (%s, %s, %s, %s)
                """,
                (session_id, user_id, expires_at, rotated_from),
            )

    def auth_session_active(self, session_id: str, user_id: str) -> bool:
        with psycopg.connect(self.url) as connection:
            row = connection.execute(
                """
                UPDATE auth_sessions SET last_seen_at = now()
                WHERE id = %s AND user_id = %s
                  AND revoked_at IS NULL AND expires_at > now()
                RETURNING id
                """,
                (session_id, user_id),
            ).fetchone()
        return row is not None

    def revoke_auth_session(self, session_id: str) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                "UPDATE auth_sessions SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL",
                (session_id,),
            )

    def revoke_user_sessions(self, user_id: str, *, except_session_id: str | None = None) -> None:
        with psycopg.connect(self.url) as connection:
            if except_session_id is None:
                connection.execute(
                    """
                    UPDATE auth_sessions SET revoked_at = now()
                    WHERE user_id = %s AND revoked_at IS NULL
                    """,
                    (user_id,),
                )
            else:
                connection.execute(
                    """
                    UPDATE auth_sessions SET revoked_at = now()
                    WHERE user_id = %s AND id <> %s AND revoked_at IS NULL
                    """,
                    (user_id, except_session_id),
                )

    def list_active_auth_sessions(self, user_id: str) -> list[dict[str, Any]]:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, last_seen_at, expires_at
                FROM auth_sessions
                WHERE user_id = %s AND revoked_at IS NULL AND expires_at > now()
                ORDER BY last_seen_at DESC, id
                """,
                (user_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def revoke_owned_auth_session(self, user_id: str, session_id: str) -> bool:
        with psycopg.connect(self.url) as connection:
            result = connection.execute(
                """
                UPDATE auth_sessions SET revoked_at = now()
                WHERE id = %s AND user_id = %s AND revoked_at IS NULL
                  AND expires_at > now()
                """,
                (session_id, user_id),
            )
        return result.rowcount == 1

    def record_auth_security_event(
        self, *, user_id: str | None, event_type: str, metadata: Mapping[str, Any] | None = None
    ) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                INSERT INTO auth_security_events (id, user_id, event_type, metadata)
                VALUES (%s, %s, %s, %s)
                """,
                (str(uuid4()), user_id, event_type, Jsonb(dict(metadata or {}))),
            )

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute("SELECT * FROM users WHERE id = %s", (user_id,)).fetchone()
        return dict(row) if row else None

    def update_user_display_name(self, user_id: str, display_name: str) -> dict[str, Any] | None:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE users SET display_name = %s, updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (display_name, user_id),
            ).fetchone()
        return dict(row) if row else None

    def delete_user(self, user_id: str) -> bool:
        with psycopg.connect(self.url) as connection:
            result = connection.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return result.rowcount == 1

    def get_profile(self, user_id: str) -> dict[str, Any] | None:
        return self._json_one("SELECT payload FROM health_profiles WHERE user_id = %s", user_id)

    def put_profile(self, user_id: str, payload: dict[str, Any]) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                INSERT INTO health_profiles (user_id, payload) VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                """,
                (user_id, Jsonb(payload)),
            )

    def get_account_profile(self, user_id: str) -> dict[str, Any] | None:
        return self._json_one("SELECT payload FROM account_profiles WHERE user_id = %s", user_id)

    def put_account_profile(self, user_id: str, payload: dict[str, Any]) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                INSERT INTO account_profiles (user_id, payload) VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                """,
                (user_id, Jsonb(payload)),
            )

    def list_household_profiles(self, user_id: str) -> list[dict[str, Any]]:
        return self._json_many(
            """
            SELECT payload FROM household_profiles
            WHERE user_id = %s ORDER BY created_at, id
            """,
            (user_id,),
        )

    def add_household_profile(
        self,
        user_id: str,
        profile_id: str,
        payload: dict[str, Any],
        *,
        limit: int,
    ) -> bool:
        with psycopg.connect(self.url) as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (user_id,))
            result = connection.execute(
                """
                INSERT INTO household_profiles (id, user_id, payload)
                SELECT %s, %s, %s
                WHERE (SELECT COUNT(*) FROM household_profiles WHERE user_id = %s) < %s
                """,
                (profile_id, user_id, Jsonb(payload), user_id, limit),
            )
        return result.rowcount == 1

    def update_household_profile(
        self, user_id: str, profile_id: str, payload: dict[str, Any]
    ) -> bool:
        with psycopg.connect(self.url) as connection:
            result = connection.execute(
                """
                UPDATE household_profiles SET payload = %s, updated_at = now()
                WHERE id = %s AND user_id = %s
                """,
                (Jsonb(payload), profile_id, user_id),
            )
        return result.rowcount == 1

    def delete_household_profile(self, user_id: str, profile_id: str) -> bool:
        return self._delete("household_profiles", user_id, profile_id)

    def put_scan(self, user_id: str, scan_id: str, payload: dict[str, Any]) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                INSERT INTO scans (id, user_id, payload) VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                """,
                (scan_id, user_id, Jsonb(payload)),
            )

    def get_scan(self, scan_id: str) -> dict[str, Any] | None:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT user_id, payload FROM scans WHERE id = %s", (scan_id,)
            ).fetchone()
        if row is None:
            return None
        return {"user_id": str(row["user_id"]), "payload": dict(row["payload"])}

    def list_scans(self, user_id: str) -> list[dict[str, Any]]:
        return self._json_many(
            "SELECT payload FROM scans WHERE user_id = %s ORDER BY created_at DESC", (user_id,)
        )

    def delete_scan(self, user_id: str, scan_id: str) -> bool:
        return self._delete("scans", user_id, scan_id)

    def create_scan_job(
        self,
        *,
        user_id: str,
        idempotency_key: str,
        input_kind: str,
        view_types: list[str],
        languages: list[str],
        images: list[tuple[str, str, bytes]],
        period_start: date,
        monthly_limit: int,
        completed_result: R3ScanResult | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically deduplicate, reserve usage, and persist bounded input artifacts."""
        if completed_result is not None:
            provenance = completed_result.client_evidence_provenance
            if (
                images
                or completed_result.input_kind.value != input_kind
                or len(view_types) != 1
                or len(completed_result.input_metadata) != 1
                or provenance is None
                or completed_result.input_metadata[0].sha256 != provenance.source_image_sha256
                or completed_result.models
                or any(ocr.attempts for ocr in completed_result.ocr_results.values())
                or completed_result.status != "COMPLETED_WITH_WARNINGS"
                or completed_result.nutrition.basis == "UNKNOWN"
                or len(completed_result.nutrition.table_rows) < 4
            ):
                raise ValueError(
                    "Inline completion requires a source-bound client structured result."
                )
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"scan-job:{user_id}:{idempotency_key}",),
            )
            key_to_use = idempotency_key
            attempt_index = 1
            max_attempts = 5
            while attempt_index <= max_attempts:
                existing = connection.execute(
                    "SELECT * FROM scan_jobs WHERE user_id = %s AND idempotency_key = %s",
                    (user_id, key_to_use),
                ).fetchone()
                if existing is None:
                    break
                if existing["status"] in ("COMPLETE", "QUEUED", "PREPROCESSING"):
                    return self._scan_job_record(existing), False
                attempt_index += 1
                key_to_use = sha256(f"{idempotency_key}:retry:{attempt_index}".encode()).hexdigest()
            else:
                if existing is not None:
                    return self._scan_job_record(existing), False

            if monthly_limit <= 0:
                raise ScanJobQuotaExceeded("Monthly scan allowance reached.")
            usage = connection.execute(
                """
                INSERT INTO scan_usage (user_id, period_start, request_count)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, period_start) DO UPDATE
                SET request_count = scan_usage.request_count + 1
                WHERE scan_usage.request_count < %s
                RETURNING request_count
                """,
                (user_id, period_start, monthly_limit),
            ).fetchone()
            if usage is None:
                raise ScanJobQuotaExceeded("Monthly scan allowance reached.")
            if completed_result is not None:
                # Same owner-scoped dedup/quota transaction; the dispatcher never
                # observes QUEUED and no source-image row is written at any time.
                connection.execute(
                    "INSERT INTO scans (id, user_id, payload) VALUES (%s, %s, %s)",
                    (
                        completed_result.scan_id,
                        user_id,
                        Jsonb(completed_result.model_dump(mode="json")),
                    ),
                )
                row = connection.execute(
                    """
                    INSERT INTO scan_jobs (
                        id, user_id, idempotency_key, input_kind, view_types, languages,
                        status, result_scan_id, started_at, completed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, 'COMPLETE', %s, now(), now())
                    RETURNING *
                    """,
                    (
                        f"job-{uuid4().hex}",
                        user_id,
                        key_to_use,
                        input_kind,
                        view_types,
                        languages,
                        completed_result.scan_id,
                    ),
                ).fetchone()
                if row is None:
                    raise RuntimeError("Completed scan job insert returned no row.")
                return self._scan_job_record(row), True
            job_id = f"job-{uuid4().hex}"
            row = connection.execute(
                """
                INSERT INTO scan_jobs (
                    id, user_id, idempotency_key, input_kind, view_types, languages, status
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'QUEUED')
                RETURNING *
                """,
                (job_id, user_id, key_to_use, input_kind, view_types, languages),
            ).fetchone()
            if row is None:
                raise RuntimeError("Scan job insert returned no row.")
            for position, (filename, mime_type, content) in enumerate(images):
                connection.execute(
                    """
                    INSERT INTO scan_job_images (job_id, position, filename, mime_type, content)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (job_id, position, filename, mime_type, content),
                )
            return self._scan_job_record(row), True

    def get_scan_job(self, user_id: str, job_id: str) -> dict[str, Any] | None:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT * FROM scan_jobs WHERE id = %s AND user_id = %s", (job_id, user_id)
            ).fetchone()
        return self._scan_job_record(row) if row is not None else None

    def claim_scan_jobs(self, limit: int) -> list[dict[str, Any]]:
        """Claim queued or expired jobs exactly once per lease token."""
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                WITH candidates AS (
                    SELECT id FROM scan_jobs
                    WHERE status = 'QUEUED'
                       OR (status = 'PREPROCESSING' AND lease_expires_at < now())
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                )
                UPDATE scan_jobs AS job
                SET status = 'PREPROCESSING',
                    attempts = attempts + 1,
                    lease_token = md5(random()::text || clock_timestamp()::text || job.id),
                    lease_expires_at = now() + interval '4 minutes',
                    started_at = COALESCE(started_at, now()),
                    updated_at = now()
                FROM candidates
                WHERE job.id = candidates.id
                RETURNING job.*
                """,
                (limit,),
            ).fetchall()
            claimed: list[dict[str, Any]] = []
            for row in rows:
                images = connection.execute(
                    """
                    SELECT filename, mime_type, content FROM scan_job_images
                    WHERE job_id = %s ORDER BY position
                    """,
                    (str(row["id"]),),
                ).fetchall()
                record = self._scan_job_record(row)
                record["images"] = [
                    (str(image["filename"]), str(image["mime_type"]), bytes(image["content"]))
                    for image in images
                ]
                claimed.append(record)
            return claimed

    def complete_scan_job(
        self, *, user_id: str, job_id: str, lease_token: str, result: dict[str, Any]
    ) -> bool:
        scan_id = str(result["scan_id"])
        with psycopg.connect(self.url) as connection:
            owned_lease = connection.execute(
                """
                SELECT 1 FROM scan_jobs
                WHERE id = %s AND user_id = %s AND lease_token = %s
                FOR UPDATE
                """,
                (job_id, user_id, lease_token),
            ).fetchone()
            if owned_lease is None:
                return False
            connection.execute(
                """
                INSERT INTO scans (id, user_id, payload) VALUES (%s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()
                """,
                (scan_id, user_id, Jsonb(result)),
            )
            updated = connection.execute(
                """
                UPDATE scan_jobs
                SET status = 'COMPLETE', result_scan_id = %s, lease_token = NULL,
                    lease_expires_at = NULL, completed_at = now(), updated_at = now(),
                    error_code = NULL, error_message = NULL
                WHERE id = %s AND user_id = %s AND lease_token = %s
                """,
                (scan_id, job_id, user_id, lease_token),
            )
            if updated.rowcount != 1:
                raise RuntimeError("Claimed scan job lease changed while completing the job.")
            connection.execute("DELETE FROM scan_job_images WHERE job_id = %s", (job_id,))
        return True

    def fail_scan_job(
        self,
        *,
        user_id: str,
        job_id: str,
        lease_token: str,
        error_code: str,
        error_message: str,
        retryable: bool,
        period_start: date,
    ) -> bool:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT attempts, max_attempts FROM scan_jobs
                WHERE id = %s AND user_id = %s AND lease_token = %s FOR UPDATE
                """,
                (job_id, user_id, lease_token),
            ).fetchone()
            if row is None:
                return False
            should_retry = retryable and int(row["attempts"]) < int(row["max_attempts"])
            state = (
                "QUEUED"
                if should_retry
                else ("TIMED_OUT" if error_code == "TIMED_OUT" else "FAILED")
            )
            connection.execute(
                """
                UPDATE scan_jobs SET status = %s, lease_token = NULL, lease_expires_at = NULL,
                    error_code = %s, error_message = %s,
                    completed_at = CASE WHEN %s THEN NULL ELSE now() END, updated_at = now()
                WHERE id = %s
                """,
                (state, error_code, error_message, should_retry, job_id),
            )
            if not should_retry:
                connection.execute("DELETE FROM scan_job_images WHERE job_id = %s", (job_id,))
                connection.execute(
                    """
                    UPDATE scan_usage SET request_count = GREATEST(request_count - 1, 0)
                    WHERE user_id = %s AND period_start = %s
                    """,
                    (user_id, period_start),
                )
        return True

    @staticmethod
    def _scan_job_record(row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "job_id": str(row["id"]),
            "user_id": str(row["user_id"]),
            "input_kind": str(row["input_kind"]),
            "view_types": list(row["view_types"]),
            "languages": list(row["languages"]),
            "status": str(row["status"]),
            "attempts": int(row["attempts"]),
            "result_scan_id": str(row["result_scan_id"]) if row["result_scan_id"] else None,
            "error_code": str(row["error_code"]) if row["error_code"] else None,
            "error_message": str(row["error_message"]) if row["error_message"] else None,
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "lease_token": str(row["lease_token"]) if row["lease_token"] else None,
        }

    def list_diary(self, user_id: str, cutoff: datetime) -> list[dict[str, Any]]:
        return self._json_many(
            """
            SELECT payload FROM diary_entries
            WHERE user_id = %s AND eaten_at >= %s
            ORDER BY eaten_at DESC
            """,
            (user_id, cutoff),
        )

    def add_diary(
        self, user_id: str, entry_id: str, eaten_at: datetime, payload: dict[str, Any]
    ) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                INSERT INTO diary_entries (id, user_id, eaten_at, payload)
                VALUES (%s, %s, %s, %s)
                """,
                (entry_id, user_id, eaten_at, Jsonb(payload)),
            )

    def delete_diary(self, user_id: str, entry_id: str) -> bool:
        return self._delete("diary_entries", user_id, entry_id)

    def update_diary(
        self,
        user_id: str,
        entry_id: str,
        eaten_at: datetime,
        payload: dict[str, Any],
    ) -> bool:
        with psycopg.connect(self.url) as connection:
            result = connection.execute(
                """
                UPDATE diary_entries
                SET eaten_at = %s, payload = %s, updated_at = now()
                WHERE id = %s AND user_id = %s
                """,
                (eaten_at, Jsonb(payload), entry_id, user_id),
            )
            return result.rowcount > 0

    def list_pantry(self, user_id: str) -> list[dict[str, Any]]:
        return self._json_many(
            "SELECT payload FROM pantry_items WHERE user_id = %s ORDER BY created_at", (user_id,)
        )

    def add_pantry(self, user_id: str, item_id: str, payload: dict[str, Any]) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                "INSERT INTO pantry_items (id, user_id, payload) VALUES (%s, %s, %s)",
                (item_id, user_id, Jsonb(payload)),
            )

    def update_pantry(self, user_id: str, item_id: str, payload: dict[str, Any]) -> bool:
        with psycopg.connect(self.url) as connection:
            result = connection.execute(
                """
                UPDATE pantry_items SET payload = %s, updated_at = now()
                WHERE id = %s AND user_id = %s
                """,
                (Jsonb(payload), item_id, user_id),
            )
            return result.rowcount > 0

    def delete_pantry(self, user_id: str, item_id: str) -> bool:
        return self._delete("pantry_items", user_id, item_id)

    def list_shopping_list(self, user_id: str) -> list[dict[str, Any]]:
        return self._json_many(
            """
            SELECT payload FROM shopping_list_items
            WHERE user_id = %s ORDER BY created_at, id
            """,
            (user_id,),
        )

    def add_shopping_list_item(self, user_id: str, item_id: str, payload: dict[str, Any]) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                "INSERT INTO shopping_list_items (id, user_id, payload) VALUES (%s, %s, %s)",
                (item_id, user_id, Jsonb(payload)),
            )

    def update_shopping_list_item(
        self, user_id: str, item_id: str, payload: dict[str, Any]
    ) -> bool:
        with psycopg.connect(self.url) as connection:
            result = connection.execute(
                """
                UPDATE shopping_list_items SET payload = %s, updated_at = now()
                WHERE id = %s AND user_id = %s
                """,
                (Jsonb(payload), item_id, user_id),
            )
        return result.rowcount > 0

    def delete_shopping_list_item(self, user_id: str, item_id: str) -> bool:
        return self._delete("shopping_list_items", user_id, item_id)

    def delete_generated_shopping_item(self, user_id: str, pantry_item_id: str) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                DELETE FROM shopping_list_items
                WHERE user_id = %s
                  AND payload->>'source' = 'LOW_STOCK'
                  AND payload->>'pantry_item_id' = %s
                """,
                (user_id, pantry_item_id),
            )

    def upsert_favorite(self, user_id: str, scan_id: str, payload: dict[str, Any]) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                INSERT INTO favorites (user_id, scan_id, payload)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, scan_id) DO UPDATE SET
                    payload = EXCLUDED.payload
                """,
                (user_id, scan_id, Jsonb(payload)),
            )

    def list_favorites(self, user_id: str) -> list[dict[str, Any]]:
        return self._json_many(
            "SELECT payload FROM favorites WHERE user_id = %s ORDER BY created_at DESC",
            (user_id,),
        )

    def delete_favorite(self, user_id: str, scan_id: str) -> bool:
        with psycopg.connect(self.url) as connection:
            result = connection.execute(
                "DELETE FROM favorites WHERE user_id = %s AND scan_id = %s",
                (user_id, scan_id),
            )
        return result.rowcount == 1

    def upsert_notification(self, user_id: str, notification: dict[str, Any]) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                INSERT INTO notifications
                    (id, user_id, kind, title, body, action_href, read_at, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    body = EXCLUDED.body,
                    action_href = EXCLUDED.action_href,
                    updated_at = now()
                WHERE notifications.user_id = EXCLUDED.user_id
                """,
                (
                    notification["id"],
                    user_id,
                    notification["kind"],
                    notification["title"],
                    notification["body"],
                    notification.get("action_href"),
                    notification.get("read_at"),
                    notification["created_at"],
                ),
            )

    def list_notifications(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT id, kind, title, body, action_href, read_at, created_at
                FROM notifications
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_notification_read(self, user_id: str, notification_id: str) -> bool:
        with psycopg.connect(self.url) as connection:
            result = connection.execute(
                """
                UPDATE notifications SET read_at = COALESCE(read_at, now()), updated_at = now()
                WHERE id = %s AND user_id = %s
                """,
                (notification_id, user_id),
            )
        return result.rowcount == 1

    def mark_all_notifications_read(self, user_id: str) -> int:
        with psycopg.connect(self.url) as connection:
            result = connection.execute(
                """
                UPDATE notifications SET read_at = now(), updated_at = now()
                WHERE user_id = %s AND read_at IS NULL
                """,
                (user_id,),
            )
        return result.rowcount

    def delete_notification(self, user_id: str, notification_id: str) -> bool:
        with psycopg.connect(self.url) as connection:
            result = connection.execute(
                "DELETE FROM notifications WHERE id = %s AND user_id = %s",
                (notification_id, user_id),
            )
        return result.rowcount == 1

    def read_assistant_usage(self, user_id: str, usage_date: date) -> int:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT request_count FROM assistant_usage WHERE user_id = %s AND usage_date = %s",
                (user_id, usage_date),
            ).fetchone()
            return int(row["request_count"]) if row else 0

    def reserve_assistant_usage(self, user_id: str, usage_date: date, limit: int) -> int | None:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                INSERT INTO assistant_usage (user_id, usage_date, request_count)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, usage_date) DO UPDATE
                SET request_count = assistant_usage.request_count + 1
                WHERE assistant_usage.request_count < %s
                RETURNING request_count
                """,
                (user_id, usage_date, limit),
            ).fetchone()
        return int(row["request_count"]) if row else None

    def release_assistant_usage(self, user_id: str, usage_date: date) -> int:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                UPDATE assistant_usage
                SET request_count = GREATEST(request_count - 1, 0)
                WHERE user_id = %s AND usage_date = %s
                RETURNING request_count
                """,
                (user_id, usage_date),
            ).fetchone()
        return int(row["request_count"]) if row else 0

    def increment_assistant_usage(self, user_id: str, usage_date: date, limit: int) -> int | None:
        return self.reserve_assistant_usage(user_id, usage_date, limit)

    def increment_scan_usage(self, user_id: str, period_start: date, limit: int) -> int | None:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                INSERT INTO scan_usage (user_id, period_start, request_count)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, period_start) DO UPDATE
                SET request_count = scan_usage.request_count + 1
                WHERE scan_usage.request_count < %s
                RETURNING request_count
                """,
                (user_id, period_start, limit),
            ).fetchone()
        return int(row["request_count"]) if row else None

    def decrement_scan_usage(self, user_id: str, period_start: date) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                UPDATE scan_usage
                SET request_count = GREATEST(request_count - 1, 0)
                WHERE user_id = %s AND period_start = %s
                """,
                (user_id, period_start),
            )

    def research_counts(self) -> tuple[int, int]:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT count(DISTINCT diary_entries.user_id) AS users,
                       count(*) AS entries
                FROM diary_entries
                JOIN account_profiles
                  ON account_profiles.user_id = diary_entries.user_id
                WHERE COALESCE(
                    (account_profiles.payload->>'research_insights_consent')::boolean,
                    false
                )
                """
            ).fetchone()
        return (int(row["users"]), int(row["entries"])) if row else (0, 0)

    def research_nutrition_summary(self) -> tuple[int, int, dict[str, float | None]]:
        fields = (
            "calories",
            "protein_g",
            "carbs_g",
            "fat_g",
            "sugar_g",
            "sodium_mg",
            "fiber_g",
            "vitamin_a_mcg",
            "vitamin_c_mg",
            "vitamin_d_mcg",
            "calcium_mg",
            "iron_mg",
            "potassium_mg",
            "zinc_mg",
        )
        expressions = ", ".join(
            f"CASE WHEN COUNT(*) = 0 THEN 0 "
            f"WHEN COUNT(diary_entries.payload->'nutrients'->>'{field}') < COUNT(*) "
            "THEN NULL ELSE "
            f"SUM((diary_entries.payload->'nutrients'->>'{field}')::double precision) "
            f"END AS {field}"
            for field in fields
        )
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                f"""
                SELECT COUNT(DISTINCT diary_entries.user_id) AS user_count,
                       COUNT(*) AS entry_count,
                       {expressions}
                FROM diary_entries
                JOIN account_profiles
                  ON account_profiles.user_id = diary_entries.user_id
                WHERE COALESCE(
                    (account_profiles.payload->>'research_insights_consent')::boolean,
                    false
                )
                """  # noqa: S608 - field names come only from the fixed internal tuple above.
            ).fetchone()
        if row is None:
            return 0, 0, {field: 0.0 for field in fields}
        return (
            int(row["user_count"]),
            int(row["entry_count"]),
            {field: float(row[field]) if row[field] is not None else None for field in fields},
        )

    def add_subscription(self, record: Mapping[str, str]) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                INSERT INTO subscriptions
                    (provider_subscription_id, user_id, plan_code, billing_interval, status)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (provider_subscription_id) DO NOTHING
                """,
                (
                    record["provider_subscription_id"],
                    record["user_id"],
                    record["plan"],
                    record["interval"],
                    record["status"],
                ),
            )

    def get_subscription(self, provider_id: str) -> dict[str, Any] | None:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                "SELECT * FROM subscriptions WHERE provider_subscription_id = %s", (provider_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_current_subscription(self, user_id: str) -> dict[str, Any] | None:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(
                """
                SELECT * FROM subscriptions
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_payments(self, user_id: str, limit: int = 25) -> list[dict[str, Any]]:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            rows = connection.execute(
                """
                SELECT provider_payment_id, amount_paise, currency, status, created_at
                FROM payments WHERE user_id = %s
                ORDER BY created_at DESC LIMIT %s
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_payment(
        self,
        *,
        provider_payment_id: str,
        provider_subscription_id: str,
        amount_paise: int | None,
        currency: str,
        status: str,
    ) -> None:
        with psycopg.connect(self.url) as connection:
            connection.execute(
                """
                INSERT INTO payments (
                    provider_payment_id, user_id, provider_subscription_id,
                    amount_paise, currency, status
                )
                SELECT %s, user_id, provider_subscription_id, %s, %s, %s
                FROM subscriptions WHERE provider_subscription_id = %s
                ON CONFLICT (provider_payment_id) DO UPDATE SET
                    amount_paise = COALESCE(EXCLUDED.amount_paise, payments.amount_paise),
                    currency = EXCLUDED.currency,
                    status = EXCLUDED.status,
                    updated_at = now()
                """,
                (
                    provider_payment_id,
                    amount_paise,
                    currency,
                    status,
                    provider_subscription_id,
                ),
            )

    def apply_payment_event(
        self,
        *,
        event_id: str,
        event_type: str,
        provider_subscription_id: str,
        status: str,
        payload_sha256: str,
        current_period_end: datetime | None = None,
        provider_created_at: datetime | None = None,
    ) -> bool:
        with psycopg.connect(self.url) as connection:
            current = connection.execute(
                """
                SELECT status, last_provider_event_at FROM subscriptions
                WHERE provider_subscription_id = %s FOR UPDATE
                """,
                (provider_subscription_id,),
            ).fetchone()
            event = connection.execute(
                """
                INSERT INTO payment_events
                    (event_id, event_type, provider_subscription_id, payload_sha256)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING event_id
                """,
                (event_id, event_type, provider_subscription_id, payload_sha256),
            ).fetchone()
            if event is None:
                return False
            if (
                current is not None
                and provider_created_at is not None
                and current[1] is not None
                and provider_created_at <= current[1]
            ):
                return False
            if current is not None and not _payment_transition_allowed(
                str(current[0]), status, event_type
            ):
                return False
            connection.execute(
                """
                UPDATE subscriptions SET status = %s,
                    current_period_end = COALESCE(%s, current_period_end),
                    last_provider_event_at = COALESCE(%s, last_provider_event_at),
                    updated_at = now()
                WHERE provider_subscription_id = %s
                """,
                (status, current_period_end, provider_created_at, provider_subscription_id),
            )
            if status == "ACTIVE":
                connection.execute(
                    """
                    UPDATE users SET
                        plan_code = subscriptions.plan_code,
                        subscription_status = 'ACTIVE', updated_at = now()
                    FROM subscriptions
                    WHERE users.id = subscriptions.user_id
                      AND subscriptions.provider_subscription_id = %s
                    """,
                    (provider_subscription_id,),
                )
            elif status in {"PAST_DUE", "PAUSED", "CANCELLED", "EXPIRED"}:
                connection.execute(
                    """
                    UPDATE users SET subscription_status = %s, updated_at = now()
                    FROM subscriptions
                    WHERE users.id = subscriptions.user_id
                      AND subscriptions.provider_subscription_id = %s
                    """,
                    (status, provider_subscription_id),
                )
        return True

    def _delete(self, table: str, user_id: str, item_id: str) -> bool:
        if table not in {
            "diary_entries",
            "household_profiles",
            "pantry_items",
            "scans",
            "shopping_list_items",
        }:
            raise ValueError("Unsupported delete table.")
        with psycopg.connect(self.url) as connection:
            result = connection.execute(
                f"DELETE FROM {table} WHERE id = %s AND user_id = %s",  # noqa: S608
                (item_id, user_id),
            )
        return result.rowcount == 1

    def _json_one(self, sql: str, value: str) -> dict[str, Any] | None:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            row = connection.execute(sql, (value,)).fetchone()
        return dict(row["payload"]) if row else None

    def _json_many(self, sql: str, values: tuple[object, ...]) -> list[dict[str, Any]]:
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            rows = connection.execute(sql, values).fetchall()
        return [dict(row["payload"]) for row in rows]
