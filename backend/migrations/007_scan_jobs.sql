CREATE TABLE IF NOT EXISTS scan_jobs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    idempotency_key CHAR(64) NOT NULL,
    input_kind TEXT NOT NULL,
    view_types TEXT[] NOT NULL,
    languages TEXT[] NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('QUEUED', 'PREPROCESSING', 'COMPLETE', 'FAILED', 'TIMED_OUT')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 2 CHECK (max_attempts >= 1),
    lease_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    result_scan_id TEXT REFERENCES scans(id) ON DELETE SET NULL,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS scan_jobs_dispatch_idx
    ON scan_jobs (status, created_at) WHERE status = 'QUEUED';
CREATE INDEX IF NOT EXISTS scan_jobs_owner_time_idx
    ON scan_jobs (user_id, created_at DESC);

-- Input bytes exist only while a job is queued or running. They are deleted
-- transactionally after terminal completion/failure and are never placed in Redis.
CREATE TABLE IF NOT EXISTS scan_job_images (
    job_id TEXT NOT NULL REFERENCES scan_jobs(id) ON DELETE CASCADE,
    position SMALLINT NOT NULL CHECK (position >= 0),
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    content BYTEA NOT NULL,
    PRIMARY KEY (job_id, position)
);
