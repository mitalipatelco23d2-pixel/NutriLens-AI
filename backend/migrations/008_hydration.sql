CREATE TABLE IF NOT EXISTS hydration_targets (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    target_ml INTEGER NOT NULL CHECK (target_ml BETWEEN 100 AND 10000),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hydration_entries (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    id UUID NOT NULL,
    amount_ml INTEGER CHECK (amount_ml BETWEEN 1 AND 5000),
    consumed_at TIMESTAMPTZ,
    request_sha256 CHAR(64) NOT NULL,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, id),
    CHECK (
        (deleted_at IS NULL AND amount_ml IS NOT NULL AND consumed_at IS NOT NULL)
        OR (deleted_at IS NOT NULL AND amount_ml IS NULL AND consumed_at IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS hydration_entries_user_time_idx
    ON hydration_entries (user_id, consumed_at DESC) WHERE deleted_at IS NULL;
