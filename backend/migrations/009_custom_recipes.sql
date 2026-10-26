CREATE TABLE IF NOT EXISTS custom_recipes (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    id UUID NOT NULL,
    payload JSONB,
    request_sha256 CHAR(64) NOT NULL,
    version INTEGER NOT NULL CHECK (version >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, id)
);
-- NULL payload is a retry tombstone: content is gone, delayed POST cannot restore it.
CREATE INDEX IF NOT EXISTS custom_recipes_owner_updated_idx
    ON custom_recipes (user_id, updated_at DESC) WHERE payload IS NOT NULL;
