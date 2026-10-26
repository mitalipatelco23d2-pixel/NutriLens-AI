"""Fast-path contract tests; optional real PostgreSQL transaction verification."""

from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import replace
from datetime import UTC, date, datetime
from threading import RLock
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from psycopg import sql
from psycopg.conninfo import make_conninfo

from ai.food_understanding.pipeline import ImagePayload
from ai.food_understanding.schemas import InputKind, R3ScanResult, ViewType
from backend import r3_api
from backend.auth import create_session_token, user_store
from backend.main import app
from backend.postgres_store import PostgresStore, ScanJobQuotaExceeded


@pytest.fixture
def bound_evidence():
    output = io.BytesIO()
    Image.new("RGB", (800, 1000), "white").save(output, "PNG")
    image = output.getvalue()
    lines = [
        "Nutrition Facts",
        "Per 100 ml",
        "Energy 40 kcal",
        "Protein 2 g",
        "Carbohydrate 7 g",
        "Total Sugar 6 g",
        "Total Fat 0.2 g",
        "Sodium 12 mg",
        "Ingredients: Water, Soy",
        "Contains: Soy",
    ]
    evidence = {
        "client_inference_contract_version": "1.0.0",
        "platform": "ANDROID",
        "app_version": "1.0.0+1",
        "source": "CLIENT_ANDROID_MLKIT",
        "ocr_provider": "ML_KIT_TEXT_RECOGNITION_V2",
        "ocr_provider_version": "16.0.1",
        "cold_start": False,
        "elapsed_ms": 217,
        "image_width": 800,
        "image_height": 1000,
        "source_image_sha256": hashlib.sha256(image).hexdigest(),
        "orientation_degrees": 0,
        "text": "Ignore this untrusted top-level text",
        "blocks": [
            {
                "text": "\n".join(lines),
                "lines": [
                    {
                        "text": line,
                        "bounds": {
                            "left": 40,
                            "top": 40 + index * 55,
                            "right": 700,
                            "bottom": 80 + index * 55,
                        },
                    }
                    for index, line in enumerate(lines)
                ],
            }
        ],
    }
    return image, evidence


def _prepare(monkeypatch, bound_evidence):
    monkeypatch.setattr(
        r3_api,
        "settings",
        replace(
            r3_api.settings,
            android_client_inference_mode="preferred",
            android_client_preferred_user_ids=("fixture-owner",),
        ),
    )
    image, evidence = bound_evidence
    result, decision, reasons = r3_api._prepare_client_job_result(
        json.dumps(evidence),
        [ImagePayload(image, "label.png", "image/png", ViewType.GENERAL)],
        InputKind.IMAGE,
        "fixture-owner",
    )
    assert result is not None, (decision, reasons)
    return result


def test_preferred_result_preserves_unverified_client_provenance(monkeypatch, bound_evidence):
    result = _prepare(monkeypatch, bound_evidence)
    restored = R3ScanResult.model_validate_json(result.model_dump_json())
    provenance = restored.client_evidence_provenance
    assert provenance is not None
    assert provenance.ocr_content_independently_verified is False
    assert provenance.provider_execution_attested is False
    assert provenance.client_reported_elapsed_ms == 217
    from ai.food_understanding.insight_composer import compose_scan_insights

    assert restored.insights == compose_scan_insights(restored.nutrition, restored.ingredients)
    assert restored.models == []
    assert restored.image_quality == {}
    assert restored.images_retained is False
    assert restored.confidence_summary.numeric_score is None
    assert restored.nutrition.basis == "PER_100_ML"
    assert len(restored.nutrition.table_rows) >= 4
    assert restored.ingredients.allergen_text == "Contains: Soy"
    assert all(region.method.value == "OCR_LAYOUT" for region in restored.regions)
    assert all(
        ocr.selected_engine == "CLIENT_ANDROID_MLKIT"
        and not ocr.attempts
        and ocr.confidence is None
        for ocr in restored.ocr_results.values()
    )
    assert restored.timings.ocr_ms == restored.timings.detection_ms == 0
    assert "Ignore this" not in restored.model_dump_json()


def test_fast_result_explicit_allergen_reaches_real_r4(monkeypatch, bound_evidence):
    from backend.r4_api import get_r4_service

    _, evidence = bound_evidence
    evidence["blocks"][0]["lines"][-2]["text"] = "Ingredients: Water, Rice"
    result = _prepare(monkeypatch, bound_evidence)
    analysis = get_r4_service().analyze(result.ingredients, result.nutrition)
    explicit = [
        item.allergen
        for item in analysis.allergens
        if item.allergen.matched and item.allergen.match_method == "EXPLICIT_STATEMENT"
    ]
    assert explicit
    assert any(item.evidence_text == "Contains: Soy" for item in explicit)
    assert all(item.evidence_source == "PACKAGE_ALLERGEN_STATEMENT_OCR" for item in explicit)


def test_global_preferred_does_not_enable_unlisted_owner(monkeypatch, bound_evidence):
    result = _prepare(monkeypatch, bound_evidence)
    assert result is not None
    image, evidence = bound_evidence
    result, decision, reasons = r3_api._prepare_client_job_result(
        json.dumps(evidence),
        [ImagePayload(image, "label.png", "image/png", ViewType.GENERAL)],
        InputKind.IMAGE,
        "not-allowlisted",
    )
    assert result is None
    assert decision == "SERVER_FALLBACK_REQUIRED"
    assert reasons == ["OWNER_NOT_IN_PREFERRED_ROLLOUT"]
    headers = _headers("unlisted-capabilities-owner")
    response = TestClient(app).get("/api/v1/scan/client-inference/capabilities", headers=headers)
    assert response.json()["android_mode"] == "shadow"
    assert response.json()["server_fallback_required"] is True
    monkeypatch.setattr(
        r3_api,
        "settings",
        replace(
            r3_api.settings,
            android_client_preferred_user_ids=(_test_user("unlisted-capabilities-owner").id,),
        ),
    )
    response = TestClient(app).get("/api/v1/scan/client-inference/capabilities", headers=headers)
    assert response.json()["android_mode"] == "preferred"
    assert response.json()["evidence_use"] == "SERVER_PARSED_CLIENT_EVIDENCE"
    assert response.json()["server_fallback_required"] is False
    assert response.json()["rejected_evidence_requires_server_fallback"] is True


@pytest.mark.parametrize(
    "statement",
    [
        "May contain: Soy",
        "Contains no milk",
        "Free from milk",
        "Milk-free",
        "Does not contain peanuts",
        "Allergen: No milk",
        "Without milk",
    ],
)
def test_qualified_allergen_claims_cannot_lose_qualifier_in_fast_result(
    monkeypatch, bound_evidence, statement
):
    _prepare(monkeypatch, bound_evidence)
    image, evidence = bound_evidence
    evidence["blocks"][0]["lines"][-1]["text"] = statement
    result, _, reasons = r3_api._prepare_client_job_result(
        json.dumps(evidence),
        [ImagePayload(image, "label.png", "image/png", ViewType.GENERAL)],
        InputKind.IMAGE,
        "fixture-owner",
    )
    assert result is None
    assert "QUALIFIED_ALLERGEN_EVIDENCE_REQUIRES_SERVER_REVIEW" in reasons


@pytest.mark.parametrize(
    "mutation",
    ["hash", "dimensions", "confidence", "owner", "sparse", "rotation", "oversized", "runtime"],
)
def test_invalid_or_weak_evidence_cannot_fast_complete(monkeypatch, bound_evidence, mutation):
    monkeypatch.setattr(
        r3_api,
        "settings",
        replace(
            r3_api.settings,
            android_client_inference_mode="preferred",
            android_client_preferred_user_ids=("fixture-owner",),
        ),
    )
    image, evidence = bound_evidence
    if mutation == "hash":
        evidence["source_image_sha256"] = "f" * 64
    elif mutation == "dimensions":
        evidence["image_height"] = 999
    elif mutation == "confidence":
        evidence["confidence"] = 0.99
    elif mutation == "owner":
        evidence["user_id"] = "another-owner"
    elif mutation == "sparse":
        evidence["blocks"][0]["lines"] = evidence["blocks"][0]["lines"][:2]
    elif mutation == "rotation":
        evidence["orientation_degrees"] = 90
    elif mutation == "runtime":
        evidence["ocr_provider"] = "PaddleOCR"
    else:
        evidence["text"] = "x" * 513_000
    result, decision, reasons = r3_api._prepare_client_job_result(
        json.dumps(evidence),
        [ImagePayload(image, "label.png", "image/png", ViewType.GENERAL)],
        InputKind.IMAGE,
        "fixture-owner",
    )
    assert result is None
    assert decision != "CLIENT_EVIDENCE_ACCEPTED"
    assert reasons


class MemoryJobStore:
    """API orchestration double, NOT proof of PostgreSQL transaction semantics."""

    def __init__(self):
        self.jobs = {}
        self.scans = {}
        self.usage = {}
        self.images = []
        self.lock = RLock()

    def create_scan_job(self, **kwargs):
        with self.lock:
            owner, key = kwargs["user_id"], kwargs["idempotency_key"]
            if (owner, key) in self.jobs:
                return self.jobs[owner, key], False
            if self.usage.get(owner, 0) >= kwargs["monthly_limit"]:
                raise ScanJobQuotaExceeded()
            result = kwargs.get("completed_result")
            now = datetime.now(UTC)
            record = {
                "job_id": f"job-{uuid4().hex}",
                "input_kind": kwargs["input_kind"],
                "status": "COMPLETE" if result else "QUEUED",
                "created_at": now,
                "started_at": now if result else None,
                "completed_at": now if result else None,
                "result_scan_id": result.scan_id if result else None,
            }
            self.jobs[owner, key] = record
            self.usage[owner] = self.usage.get(owner, 0) + 1
            self.images.extend(kwargs["images"])
            if result:
                self.scans[result.scan_id] = {
                    "user_id": owner,
                    "payload": result.model_dump(mode="json"),
                }
            return record, True

    def get_scan(self, scan_id):
        return self.scans.get(scan_id)

    def get_scan_job(self, owner, job_id):
        return next(
            (
                job
                for (user, _), job in self.jobs.items()
                if user == owner and job["job_id"] == job_id
            ),
            None,
        )


def _test_user(owner):
    return user_store.upsert_google_user(
        {"sub": owner, "email": f"{owner}@example.com", "email_verified": True}
    )


def _headers(owner):
    token, _ = create_session_token(_test_user(owner))
    return {"Authorization": f"Bearer {token}", "Idempotency-Key": "same-client-fixture"}


def test_api_fast_job_duplicate_quota_owner_and_refresh(monkeypatch, bound_evidence):
    store = MemoryJobStore()
    monkeypatch.setattr(r3_api, "postgres_store", store)
    monkeypatch.setattr(
        r3_api, "settings", replace(r3_api.settings, android_client_inference_mode="preferred")
    )
    queued = []

    async def enqueue(job_id):
        queued.append(job_id)

    monkeypatch.setattr(r3_api.dispatcher, "enqueue", enqueue)
    client = TestClient(app)
    first_owner, second_owner = _headers("preferred-owner-a"), _headers("preferred-owner-b")
    monkeypatch.setattr(
        r3_api,
        "settings",
        replace(
            r3_api.settings,
            android_client_preferred_user_ids=(
                _test_user("preferred-owner-a").id,
                _test_user("preferred-owner-b").id,
            ),
        ),
    )
    image, evidence = bound_evidence

    def submit(headers):
        return client.post(
            "/api/v1/scan/jobs/image",
            headers=headers,
            data={"evidence_json": json.dumps(evidence)},
            files={"file": ("label.png", image, "image/png")},
        )

    before_diary = client.get("/api/v1/diary", headers=first_owner).json()
    before_summary = client.get("/api/v1/analytics/summary", headers=first_owner).json()
    first, duplicate, other = submit(first_owner), submit(first_owner), submit(second_owner)
    assert client.get("/api/v1/diary", headers=first_owner).json() == before_diary
    assert client.get("/api/v1/analytics/summary", headers=first_owner).json() == before_summary
    assert first.status_code == duplicate.status_code == other.status_code == 202
    first_body = first.json()
    assert first_body["status"] == "COMPLETE"
    assert first_body["server_fallback_required"] is False
    assert duplicate.json()["job_id"] == first_body["job_id"]
    assert other.json()["job_id"] != first_body["job_id"]
    assert sorted(store.usage.values()) == [1, 1]
    assert len(store.scans) == 2
    assert store.images == queued == []
    path = f"/api/v1/scan/jobs/{first_body['job_id']}"
    assert client.get(path, headers=first_owner).json()["result"] == first_body["result"]
    assert client.get(path, headers=second_owner).status_code == 404


@pytest.mark.parametrize(
    "mode,bad_digest", [("shadow", False), ("disabled", False), ("preferred", True)]
)
def test_api_shadow_and_rejected_evidence_keep_worker_path(
    monkeypatch, bound_evidence, mode, bad_digest
):
    store = MemoryJobStore()
    monkeypatch.setattr(r3_api, "postgres_store", store)
    monkeypatch.setattr(
        r3_api, "settings", replace(r3_api.settings, android_client_inference_mode=mode)
    )
    queued = []

    async def enqueue(job_id):
        queued.append(job_id)

    monkeypatch.setattr(r3_api.dispatcher, "enqueue", enqueue)
    image, evidence = bound_evidence
    if bad_digest:
        evidence["source_image_sha256"] = "f" * 64
    monkeypatch.setattr(
        r3_api,
        "settings",
        replace(
            r3_api.settings, android_client_preferred_user_ids=(_test_user(f"fallback-{mode}").id,)
        ),
    )
    response = TestClient(app).post(
        "/api/v1/scan/jobs/image",
        headers=_headers(f"fallback-{mode}"),
        data={"evidence_json": json.dumps(evidence)},
        files={"file": ("label.png", image, "image/png")},
    )
    assert response.status_code == 202
    assert response.json()["status"] == "QUEUED"
    assert response.json()["server_fallback_required"] is True
    assert response.json()["client_evidence_reasons"]
    assert len(queued) == len(store.images) == 1
    assert store.scans == {}


def test_duplicate_reuses_existing_server_path_not_fresh_evidence(monkeypatch, bound_evidence):
    store = MemoryJobStore()
    monkeypatch.setattr(r3_api, "postgres_store", store)
    owner = _test_user("existing-worker-owner")
    monkeypatch.setattr(
        r3_api,
        "settings",
        replace(
            r3_api.settings,
            android_client_inference_mode="preferred",
            android_client_preferred_user_ids=(owner.id,),
        ),
    )
    queued = []

    async def enqueue(job_id):
        queued.append(job_id)

    monkeypatch.setattr(r3_api.dispatcher, "enqueue", enqueue)
    image, evidence = bound_evidence
    client = TestClient(app)
    headers = _headers("existing-worker-owner")
    first = client.post(
        "/api/v1/scan/jobs/image",
        headers=headers,
        files={"file": ("label.png", image, "image/png")},
    )
    duplicate = client.post(
        "/api/v1/scan/jobs/image",
        headers=headers,
        data={"evidence_json": json.dumps(evidence)},
        files={"file": ("label.png", image, "image/png")},
    )
    assert first.status_code == duplicate.status_code == 202
    assert first.json()["job_id"] == duplicate.json()["job_id"]
    assert duplicate.json()["status"] == "QUEUED"
    assert duplicate.json()["client_evidence_decision"] == "SERVER_FALLBACK_REQUIRED"
    assert duplicate.json()["client_evidence_reasons"] == ["EXISTING_SERVER_JOB_REUSED_AS_STORED"]
    assert duplicate.json()["server_fallback_required"] is True
    assert list(store.usage.values()) == [1]
    assert len(queued) == 1
    assert not store.scans


@pytest.fixture
def real_store():
    """Use only an explicit test DB, with a generated isolated schema and cleanup."""
    url = os.environ.get("NUTRILENS_TEST_POSTGRES_URL")
    if not url:
        pytest.skip("Real Postgres unavailable: set NUTRILENS_TEST_POSTGRES_URL explicitly.")
    schema = f"client_fast_test_{uuid4().hex}"
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    test_url = make_conninfo(url, options=f"-c search_path={schema}")
    try:
        with psycopg.connect(test_url) as connection:
            connection.execute("CREATE TABLE users (id text PRIMARY KEY)")
            connection.execute(
                "CREATE TABLE scans (id text PRIMARY KEY, user_id text NOT NULL "
                "REFERENCES users(id), payload jsonb NOT NULL, "
                "created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now())"
            )
            connection.execute(
                "CREATE TABLE scan_usage (user_id text REFERENCES users(id), "
                "period_start date, request_count integer, PRIMARY KEY(user_id, period_start))"
            )
            from pathlib import Path

            connection.execute(Path("backend/migrations/007_scan_jobs.sql").read_text())
            connection.execute("INSERT INTO users VALUES ('owner-a'), ('owner-b')")
        yield PostgresStore(test_url)
    finally:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def _store_args(result):
    return {
        "user_id": "owner-a",
        "idempotency_key": "a" * 64,
        "input_kind": "IMAGE",
        "view_types": ["GENERAL"],
        "languages": ["en"],
        "images": [],
        "period_start": date(2026, 9, 1),
        "monthly_limit": 1,
        "completed_result": result,
    }


def test_real_postgres_concurrent_dedup_quota_and_owner(monkeypatch, bound_evidence, real_store):
    from concurrent.futures import ThreadPoolExecutor

    result = _prepare(monkeypatch, bound_evidence)
    args = _store_args(result)
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda _: real_store.create_scan_job(**args), range(4)))
    assert sum(created for _, created in outcomes) == 1
    job = outcomes[0][0]
    assert job["status"] == "COMPLETE"
    assert real_store.get_scan_job("owner-b", job["job_id"]) is None
    assert real_store.claim_scan_jobs(5) == []
    with pytest.raises(ScanJobQuotaExceeded):
        real_store.create_scan_job(**{**args, "idempotency_key": "b" * 64})
    with pytest.raises(psycopg.errors.UniqueViolation):
        real_store.create_scan_job(**{**args, "user_id": "owner-b"})
    assert real_store.get_scan(result.scan_id)["user_id"] == "owner-a"
    other_result = result.model_copy(update={"scan_id": f"scan-{uuid4().hex}"})
    other, created = real_store.create_scan_job(
        **{**args, "user_id": "owner-b", "completed_result": other_result}
    )
    assert created and other["job_id"] != job["job_id"]
    with psycopg.connect(real_store.url) as connection:
        assert connection.execute("SELECT count(*) FROM scan_job_images").fetchone()[0] == 0
        assert connection.execute("SELECT sum(request_count) FROM scan_usage").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM scans").fetchone()[0] == 2


def test_real_postgres_result_insert_failure_rolls_back_quota(
    monkeypatch, bound_evidence, real_store
):
    result = _prepare(monkeypatch, bound_evidence)
    with psycopg.connect(real_store.url) as connection:
        connection.execute(
            "ALTER TABLE scan_jobs ADD CONSTRAINT fail_test CHECK (status != 'COMPLETE')"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        real_store.create_scan_job(**_store_args(result))
    with psycopg.connect(real_store.url) as connection:
        for table in ("scan_usage", "scans", "scan_jobs", "scan_job_images"):
            assert (
                connection.execute(
                    sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
                ).fetchone()[0]
                == 0
            )


def test_real_postgres_terminal_worker_failure_refunds_quota_and_deletes_images(real_store):
    period_start = date(2026, 9, 1)
    job, created = real_store.create_scan_job(
        **{
            **_store_args(None),
            "images": [("label.png", "image/png", b"bounded-image")],
        }
    )
    assert created and job["status"] == "QUEUED"

    first_claim = real_store.claim_scan_jobs(1)[0]
    assert real_store.fail_scan_job(
        user_id="owner-a",
        job_id=job["job_id"],
        lease_token=first_claim["lease_token"],
        error_code="AI_WORKER_UNAVAILABLE",
        error_message="Enhanced scan is temporarily unavailable.",
        retryable=True,
        period_start=period_start,
    )
    retry = real_store.get_scan_job("owner-a", job["job_id"])
    assert retry is not None and retry["status"] == "QUEUED"

    final_claim = real_store.claim_scan_jobs(1)[0]
    assert real_store.fail_scan_job(
        user_id="owner-a",
        job_id=job["job_id"],
        lease_token=final_claim["lease_token"],
        error_code="AI_WORKER_UNAVAILABLE",
        error_message="Enhanced scan is temporarily unavailable.",
        retryable=True,
        period_start=period_start,
    )
    failed = real_store.get_scan_job("owner-a", job["job_id"])
    assert failed is not None and failed["status"] == "FAILED"
    assert failed["error_code"] == "AI_WORKER_UNAVAILABLE"
    with psycopg.connect(real_store.url) as connection:
        assert connection.execute("SELECT count(*) FROM scan_job_images").fetchone()[0] == 0
        assert connection.execute("SELECT request_count FROM scan_usage").fetchone()[0] == 0
