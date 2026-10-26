CREATE TABLE IF NOT EXISTS email_otp_challenges (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    identity_id TEXT NOT NULL REFERENCES auth_identities(id) ON DELETE CASCADE,
    otp_hash CHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    resend_after TIMESTAMPTZ NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS email_otp_challenges_email_idx
    ON email_otp_challenges (lower(email), created_at DESC);
