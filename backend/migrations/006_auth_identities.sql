ALTER TABLE users ALTER COLUMN google_subject DROP NOT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;

UPDATE users
SET email_verified_at = COALESCE(email_verified_at, created_at)
WHERE google_subject IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS users_email_normalized_idx
    ON users (lower(email));

CREATE TABLE IF NOT EXISTS auth_identities (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    provider_subject TEXT NOT NULL,
    verified_email TEXT,
    verified_phone TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ,
    UNIQUE (provider, provider_subject)
);
CREATE INDEX IF NOT EXISTS auth_identities_user_idx ON auth_identities (user_id);
CREATE INDEX IF NOT EXISTS auth_identities_verified_email_idx
    ON auth_identities (lower(verified_email)) WHERE verified_email IS NOT NULL;
CREATE INDEX IF NOT EXISTS auth_identities_verified_phone_idx
    ON auth_identities (verified_phone) WHERE verified_phone IS NOT NULL;

INSERT INTO auth_identities (
    id, user_id, provider, provider_subject, verified_email, created_at, last_login_at
)
SELECT
    'google:' || google_subject,
    id,
    'google',
    google_subject,
    lower(email),
    created_at,
    updated_at
FROM users
WHERE google_subject IS NOT NULL
ON CONFLICT (provider, provider_subject) DO UPDATE SET
    user_id = EXCLUDED.user_id,
    verified_email = EXCLUDED.verified_email;

CREATE TABLE IF NOT EXISTS password_credentials (
    identity_id TEXT PRIMARY KEY REFERENCES auth_identities(id) ON DELETE CASCADE,
    password_hash TEXT NOT NULL,
    failed_attempts INTEGER NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
    locked_until TIMESTAMPTZ,
    password_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth_action_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    identity_id TEXT REFERENCES auth_identities(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL,
    token_hash CHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_action_tokens_lookup_idx
    ON auth_action_tokens (purpose, token_hash, expires_at);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    rotated_from TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_sessions_user_idx ON auth_sessions (user_id, expires_at DESC);

CREATE TABLE IF NOT EXISTS auth_security_events (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS auth_security_events_user_time_idx
    ON auth_security_events (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS phone_otp_challenges (
    id TEXT PRIMARY KEY,
    phone_e164 TEXT NOT NULL,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    otp_hash CHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    resend_after TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS phone_otp_challenges_phone_idx
    ON phone_otp_challenges (phone_e164, created_at DESC);
