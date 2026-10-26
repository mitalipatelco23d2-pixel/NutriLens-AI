-- A receipt and its effects commit together. Keep only identifiers, never a second
-- copy of deleted diary/recipe content. Owner deletion removes retry identities.
CREATE TABLE IF NOT EXISTS custom_recipe_actions (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    id UUID NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('DIARY', 'SHOPPING')),
    request_sha256 CHAR(64) NOT NULL,
    result_ids JSONB NOT NULL,
    generated_count INTEGER NOT NULL CHECK (generated_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, id)
);
