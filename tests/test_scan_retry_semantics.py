"""Unit tests for scan retry semantics and immutable provenance in PostgresStore."""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Any

import pytest

from backend.postgres_store import PostgresStore, ScanJobQuotaExceeded


class FakePostgresDb:
    """In-memory state and SQL dispatcher mimicking PostgreSQL tables for scan jobs."""

    def __init__(self) -> None:
        self.scan_jobs: dict[str, dict[str, Any]] = {}
        self.scan_usage: dict[tuple[str, date], int] = {}
        self.scans: dict[str, dict[str, Any]] = {}
        self.scan_job_images: list[dict[str, Any]] = []
        self.locks_held: list[str] = []

    def connect(self, _url: str, row_factory: Any = None):
        return FakeConnection(self)


class FakeCursor:
    def __init__(self, db: FakePostgresDb) -> None:
        self.db = db
        self._result: Any = None

    def fetchone(self) -> dict[str, Any] | None:
        if isinstance(self._result, list):
            return self._result[0] if self._result else None
        return self._result

    def fetchall(self) -> list[dict[str, Any]]:
        if isinstance(self._result, list):
            return self._result
        return [self._result] if self._result else []


class FakeConnection:
    def __init__(self, db: FakePostgresDb) -> None:
        self.db = db

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        return None

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> FakeCursor:
        cursor = FakeCursor(self.db)
        normalized = " ".join(query.strip().split())

        if "pg_advisory_xact_lock" in normalized:
            lock_key = params[0]
            self.db.locks_held.append(lock_key)
            cursor._result = None
            return cursor

        if normalized.startswith(
            "SELECT * FROM scan_jobs WHERE user_id = %s AND idempotency_key = %s"
        ):
            user_id, key = params
            match = next(
                (
                    j
                    for j in self.db.scan_jobs.values()
                    if j["user_id"] == user_id and j["idempotency_key"] == key
                ),
                None,
            )
            cursor._result = match
            return cursor

        if normalized.startswith("SELECT * FROM scan_jobs WHERE id = %s AND user_id = %s"):
            job_id, user_id = params
            job = self.db.scan_jobs.get(job_id)
            cursor._result = job if (job and job["user_id"] == user_id) else None
            return cursor

        if "INSERT INTO scan_usage" in normalized:
            user_id, period_start, monthly_limit = params[0], params[1], params[2]
            key = (user_id, period_start)
            current = self.db.scan_usage.get(key, 0)
            if current >= monthly_limit:
                cursor._result = None
                return cursor
            self.db.scan_usage[key] = current + 1
            cursor._result = {"request_count": self.db.scan_usage[key]}
            return cursor

        if normalized.startswith(
            "INSERT INTO scan_jobs ( id, user_id, idempotency_key, input_kind, view_types"
        ):
            job_id, user_id, key, input_kind, view_types, languages = params
            job = {
                "id": job_id,
                "user_id": user_id,
                "idempotency_key": key,
                "input_kind": input_kind,
                "view_types": view_types,
                "languages": languages,
                "status": "QUEUED",
                "result_scan_id": None,
                "lease_token": None,
                "lease_expires_at": None,
                "attempts": 0,
                "max_attempts": 3,
                "error_code": None,
                "error_message": None,
                "created_at": datetime.now(UTC),
                "started_at": None,
                "completed_at": None,
                "updated_at": datetime.now(UTC),
            }
            self.db.scan_jobs[job_id] = job
            cursor._result = job
            return cursor

        if normalized.startswith("INSERT INTO scan_job_images"):
            job_id, pos, fname, mime, content = params
            self.db.scan_job_images.append(
                {
                    "job_id": job_id,
                    "position": pos,
                    "filename": fname,
                    "mime_type": mime,
                    "content": content,
                }
            )
            cursor._result = None
            return cursor

        if "SELECT attempts, max_attempts FROM scan_jobs" in normalized:
            job_id, user_id, lease_token = params
            job = self.db.scan_jobs.get(job_id)
            if job and job["user_id"] == user_id and job.get("lease_token") == lease_token:
                cursor._result = {
                    "attempts": job["attempts"],
                    "max_attempts": job["max_attempts"],
                }
            else:
                cursor._result = None
            return cursor

        if normalized.startswith("UPDATE scan_jobs SET status = %s"):
            # fail_scan_job update
            state, error_code, error_message, should_retry, job_id = params
            if job_id in self.db.scan_jobs:
                self.db.scan_jobs[job_id]["status"] = state
                self.db.scan_jobs[job_id]["error_code"] = error_code
                self.db.scan_jobs[job_id]["error_message"] = error_message
                self.db.scan_jobs[job_id]["lease_token"] = None
                self.db.scan_jobs[job_id]["lease_expires_at"] = None
                if not should_retry:
                    self.db.scan_jobs[job_id]["completed_at"] = datetime.now(UTC)
            cursor._result = None
            return cursor

        if "DELETE FROM scan_job_images WHERE job_id = %s" in normalized:
            job_id = params[0]
            self.db.scan_job_images = [
                img for img in self.db.scan_job_images if img["job_id"] != job_id
            ]
            cursor._result = None
            return cursor

        if "UPDATE scan_usage SET request_count = GREATEST(request_count - 1, 0)" in normalized:
            user_id, period_start = params
            key = (user_id, period_start)
            if key in self.db.scan_usage:
                self.db.scan_usage[key] = max(self.db.scan_usage[key] - 1, 0)
            cursor._result = None
            return cursor

        cursor._result = None
        return cursor


@pytest.fixture
def fake_db(monkeypatch: pytest.MonkeyPatch) -> FakePostgresDb:
    import psycopg

    db = FakePostgresDb()
    monkeypatch.setattr(psycopg, "connect", db.connect)
    return db


def test_scan_retry_preserves_failed_job_and_creates_new_attempt(fake_db: FakePostgresDb) -> None:
    store = PostgresStore("postgresql://mock")
    period = date(2026, 10, 1)

    # 1. Create original job
    job1, created1 = store.create_scan_job(
        user_id="user-1",
        idempotency_key="raw-client-key-123",
        input_kind="IMAGE",
        view_types=["GENERAL"],
        languages=["en"],
        images=[("label.jpg", "image/jpeg", b"bytes")],
        period_start=period,
        monthly_limit=10,
    )
    assert created1 is True
    assert job1["status"] == "QUEUED"
    assert fake_db.scan_jobs[job1["job_id"]]["idempotency_key"] == "raw-client-key-123"
    assert fake_db.scan_usage[("user-1", period)] == 1

    # Simulate worker claiming and failing the job terminally
    original_id = job1["job_id"]
    fake_db.scan_jobs[original_id]["lease_token"] = "lease-abc"
    fake_db.scan_jobs[original_id]["attempts"] = 3  # reached max
    failed = store.fail_scan_job(
        user_id="user-1",
        job_id=original_id,
        lease_token="lease-abc",
        error_code="OCR_FAILED",
        error_message="Image unreadable",
        retryable=False,
        period_start=period,
    )
    assert failed is True
    assert fake_db.scan_jobs[original_id]["status"] == "FAILED"
    # Quota was refunded on terminal failure
    assert fake_db.scan_usage[("user-1", period)] == 0

    # 2. Client retries with the EXACT SAME idempotency_key
    job2, created2 = store.create_scan_job(
        user_id="user-1",
        idempotency_key="raw-client-key-123",
        input_kind="IMAGE",
        view_types=["GENERAL"],
        languages=["en"],
        images=[("label.jpg", "image/jpeg", b"bytes")],
        period_start=period,
        monthly_limit=10,
    )
    assert created2 is True
    assert job2["job_id"] != original_id

    # Expected derived retry key for attempt 2
    expected_retry_key = hashlib.sha256(b"raw-client-key-123:retry:2").hexdigest()
    assert fake_db.scan_jobs[job2["job_id"]]["idempotency_key"] == expected_retry_key
    assert job2["status"] == "QUEUED"

    # IMMUTABILITY CHECK: The original failed job MUST still exist!
    assert original_id in fake_db.scan_jobs
    assert fake_db.scan_jobs[original_id]["status"] == "FAILED"
    assert fake_db.scan_jobs[original_id]["idempotency_key"] == "raw-client-key-123"

    # Quota charged exactly once for the new attempt
    assert fake_db.scan_usage[("user-1", period)] == 1


def test_scan_retry_preserves_timed_out_job(fake_db: FakePostgresDb) -> None:
    store = PostgresStore("postgresql://mock")
    period = date(2026, 10, 1)

    # 1. Create original job
    job1, created1 = store.create_scan_job(
        user_id="user-1",
        idempotency_key="timeout-key",
        input_kind="IMAGE",
        view_types=["GENERAL"],
        languages=["en"],
        images=[("label.jpg", "image/jpeg", b"bytes")],
        period_start=period,
        monthly_limit=10,
    )
    assert created1 is True

    # Simulate timeout
    job_id = job1["job_id"]
    fake_db.scan_jobs[job_id]["lease_token"] = "lease-xyz"
    fake_db.scan_jobs[job_id]["attempts"] = 3
    store.fail_scan_job(
        user_id="user-1",
        job_id=job_id,
        lease_token="lease-xyz",
        error_code="TIMED_OUT",
        error_message="Worker timeout",
        retryable=False,
        period_start=period,
    )
    assert fake_db.scan_jobs[job_id]["status"] == "TIMED_OUT"

    # 2. Retry
    job2, created2 = store.create_scan_job(
        user_id="user-1",
        idempotency_key="timeout-key",
        input_kind="IMAGE",
        view_types=["GENERAL"],
        languages=["en"],
        images=[("label.jpg", "image/jpeg", b"bytes")],
        period_start=period,
        monthly_limit=10,
    )
    assert created2 is True
    assert job2["job_id"] != job_id
    assert fake_db.scan_jobs[job_id]["status"] == "TIMED_OUT"


def test_duplicate_while_queued_or_processing_returns_same_job(fake_db: FakePostgresDb) -> None:
    store = PostgresStore("postgresql://mock")
    period = date(2026, 10, 1)

    job1, created1 = store.create_scan_job(
        user_id="user-1",
        idempotency_key="active-key",
        input_kind="IMAGE",
        view_types=["GENERAL"],
        languages=["en"],
        images=[("label.jpg", "image/jpeg", b"bytes")],
        period_start=period,
        monthly_limit=10,
    )
    assert created1 is True
    assert fake_db.scan_usage[("user-1", period)] == 1

    # Second call while still QUEUED
    job2, created2 = store.create_scan_job(
        user_id="user-1",
        idempotency_key="active-key",
        input_kind="IMAGE",
        view_types=["GENERAL"],
        languages=["en"],
        images=[("label.jpg", "image/jpeg", b"bytes")],
        period_start=period,
        monthly_limit=10,
    )
    assert created2 is False
    assert job2["job_id"] == job1["job_id"]
    assert fake_db.scan_usage[("user-1", period)] == 1  # 0 additional quota charged

    # Update to PREPROCESSING
    fake_db.scan_jobs[job1["job_id"]]["status"] = "PREPROCESSING"

    # Third call while PREPROCESSING
    job3, created3 = store.create_scan_job(
        user_id="user-1",
        idempotency_key="active-key",
        input_kind="IMAGE",
        view_types=["GENERAL"],
        languages=["en"],
        images=[("label.jpg", "image/jpeg", b"bytes")],
        period_start=period,
        monthly_limit=10,
    )
    assert created3 is False
    assert job3["job_id"] == job1["job_id"]
    assert fake_db.scan_usage[("user-1", period)] == 1


def test_duplicate_when_complete_returns_existing_job(fake_db: FakePostgresDb) -> None:
    store = PostgresStore("postgresql://mock")
    period = date(2026, 10, 1)

    job1, created1 = store.create_scan_job(
        user_id="user-1",
        idempotency_key="complete-key",
        input_kind="IMAGE",
        view_types=["GENERAL"],
        languages=["en"],
        images=[("label.jpg", "image/jpeg", b"bytes")],
        period_start=period,
        monthly_limit=10,
    )
    assert created1 is True

    fake_db.scan_jobs[job1["job_id"]]["status"] = "COMPLETE"
    fake_db.scan_jobs[job1["job_id"]]["result_scan_id"] = "scan-result-abc"

    job2, created2 = store.create_scan_job(
        user_id="user-1",
        idempotency_key="complete-key",
        input_kind="IMAGE",
        view_types=["GENERAL"],
        languages=["en"],
        images=[("label.jpg", "image/jpeg", b"bytes")],
        period_start=period,
        monthly_limit=10,
    )
    assert created2 is False
    assert job2["job_id"] == job1["job_id"]
    assert job2["status"] == "COMPLETE"
    assert fake_db.scan_usage[("user-1", period)] == 1


def test_cross_user_isolation(fake_db: FakePostgresDb) -> None:
    store = PostgresStore("postgresql://mock")
    period = date(2026, 10, 1)

    # User A creates a job
    job_a, _ = store.create_scan_job(
        user_id="user-A",
        idempotency_key="shared-key-string",
        input_kind="IMAGE",
        view_types=["GENERAL"],
        languages=["en"],
        images=[("label.jpg", "image/jpeg", b"bytes")],
        period_start=period,
        monthly_limit=10,
    )

    # User B creates with same idempotency key string
    job_b, created_b = store.create_scan_job(
        user_id="user-B",
        idempotency_key="shared-key-string",
        input_kind="IMAGE",
        view_types=["GENERAL"],
        languages=["en"],
        images=[("label.jpg", "image/jpeg", b"bytes")],
        period_start=period,
        monthly_limit=10,
    )

    assert created_b is True
    assert job_b["job_id"] != job_a["job_id"]
    assert job_b["user_id"] == "user-B"
    assert fake_db.scan_usage[("user-A", period)] == 1
    assert fake_db.scan_usage[("user-B", period)] == 1


def test_quota_exhausted_rejects_retry(fake_db: FakePostgresDb) -> None:
    store = PostgresStore("postgresql://mock")
    period = date(2026, 10, 1)

    # User with monthly limit of 1
    job1, _ = store.create_scan_job(
        user_id="user-quota",
        idempotency_key="quota-key",
        input_kind="IMAGE",
        view_types=["GENERAL"],
        languages=["en"],
        images=[("label.jpg", "image/jpeg", b"bytes")],
        period_start=period,
        monthly_limit=1,
    )
    # Mark job as failed, but manually simulate another usage took the quota
    fake_db.scan_jobs[job1["job_id"]]["status"] = "FAILED"
    fake_db.scan_usage[("user-quota", period)] = 1  # already at limit

    with pytest.raises(ScanJobQuotaExceeded):
        store.create_scan_job(
            user_id="user-quota",
            idempotency_key="quota-key",
            input_kind="IMAGE",
            view_types=["GENERAL"],
            languages=["en"],
            images=[("label.jpg", "image/jpeg", b"bytes")],
            period_start=period,
            monthly_limit=1,
        )
