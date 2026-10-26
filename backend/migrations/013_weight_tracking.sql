CREATE TABLE IF NOT EXISTS weight_settings (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    target_weight_kg NUMERIC(5, 2) CHECK (target_weight_kg BETWEEN 20 AND 500),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS weight_entries (
    user_id TEXT NOT NULL REFERENCES weight_settings(user_id) ON DELETE CASCADE,
    id UUID NOT NULL,
    weight_kg NUMERIC(5, 2) CHECK (weight_kg BETWEEN 20 AND 500),
    recorded_at TIMESTAMPTZ,
    request_sha256 CHAR(64) NOT NULL,
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, id),
    CHECK (
        (deleted_at IS NULL AND weight_kg IS NOT NULL AND recorded_at IS NOT NULL)
        OR (deleted_at IS NOT NULL AND weight_kg IS NULL AND recorded_at IS NULL)
    )
);
CREATE INDEX IF NOT EXISTS weight_entries_user_time_idx
    ON weight_entries (user_id, recorded_at DESC) WHERE deleted_at IS NULL;
