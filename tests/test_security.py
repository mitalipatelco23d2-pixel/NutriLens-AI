from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from backend.auth import User, create_session_token
from backend.security import OperationalLoggingMiddleware, RateLimitMiddleware


def _app(
    *,
    default_per_minute: int = 60,
    backend: str = "memory",
    redis_client: Any | None = None,
    fail_closed: bool = False,
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        default_per_minute=default_per_minute,
        backend=backend,
        redis_client=redis_client,
        fail_closed=fail_closed,
    )

    @app.get("/api/v1/example")
    def example() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/health")
    def readiness() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/scan/jobs/job-test")
    def scan_job_status() -> dict[str, str]:
        return {"status": "QUEUED"}

    @app.post("/api/v1/scan/jobs/product")
    def create_scan_job() -> dict[str, str]:
        return {"status": "QUEUED"}

    return app


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    async def eval(self, script: str, keys: int, key: str, window: int) -> list[int]:
        assert "INCR" in script
        assert keys == 1
        assert window == 60
        self.counts[key] = self.counts.get(key, 0) + 1
        return [self.counts[key], 45]


class FailingRedis:
    async def eval(self, *_args: object) -> list[int]:
        raise RedisError("unavailable")


class TransientRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0

    async def eval(self, script: str, keys: int, key: str, window: int) -> list[int]:
        self.attempts += 1
        if self.attempts == 1:
            raise RedisError("transient")
        return await super().eval(script, keys, key, window)


def test_memory_rate_limit_returns_headers_and_429() -> None:
    with TestClient(_app(default_per_minute=2)) as client:
        first = client.get("/api/v1/example")
        second = client.get("/api/v1/example")
        limited = client.get("/api/v1/example")

    assert first.headers["X-RateLimit-Limit"] == "2"
    assert first.headers["X-RateLimit-Remaining"] == "1"
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert limited.status_code == 429
    assert limited.json() == {"detail": "Rate limit exceeded."}
    assert int(limited.headers["Retry-After"]) >= 1


def test_redis_rate_limit_uses_verified_subject_and_collapses_invalid_tokens() -> None:
    redis = FakeRedis()
    app = _app(
        default_per_minute=1,
        backend="redis",
        redis_client=redis,
        fail_closed=True,
    )
    first_token, _ = create_session_token(
        User(id="user-a", google_subject="a", email="a@example.com", name="A", avatar_url=None)
    )
    second_token, _ = create_session_token(
        User(id="user-b", google_subject="b", email="b@example.com", name="B", avatar_url=None)
    )
    with TestClient(app) as client:
        first = client.get("/api/v1/example", headers={"Authorization": f"Bearer {first_token}"})
        limited = client.get("/api/v1/example", headers={"Authorization": f"Bearer {first_token}"})
        other_user = client.get(
            "/api/v1/example", headers={"Authorization": f"Bearer {second_token}"}
        )

    assert first.status_code == 200
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "45"
    assert other_user.status_code == 200
    assert len(redis.counts) == 2
    assert all(first_token not in key and second_token not in key for key in redis.counts)

    invalid_redis = FakeRedis()
    invalid_app = _app(default_per_minute=1, backend="redis", redis_client=invalid_redis)
    with TestClient(invalid_app) as client:
        assert (
            client.get(
                "/api/v1/example", headers={"Authorization": "Bearer attacker-1"}
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/api/v1/example", headers={"Authorization": "Bearer attacker-2"}
            ).status_code
            == 429
        )
    assert len(invalid_redis.counts) == 1


def test_public_redis_failure_fails_closed_but_health_is_available() -> None:
    app = _app(backend="redis", redis_client=FailingRedis(), fail_closed=True)
    with TestClient(app) as client:
        unavailable = client.get("/api/v1/example")
        health = client.get("/health")

    assert unavailable.status_code == 503
    assert unavailable.json() == {"detail": "Rate limiting is temporarily unavailable."}
    assert unavailable.headers["Retry-After"] == "5"
    assert health.status_code == 200
    assert "X-RateLimit-Limit" not in health.headers


def test_transient_redis_failure_is_retried_once() -> None:
    redis = TransientRedis()
    app = _app(backend="redis", redis_client=redis, fail_closed=True)

    with TestClient(app) as client:
        response = client.get("/api/v1/example")

    assert response.status_code == 200
    assert response.headers["X-RateLimit-Remaining"] == "59"
    assert redis.attempts == 2


def test_readiness_is_rate_limited_while_liveness_is_exempt() -> None:
    with TestClient(_app(default_per_minute=1)) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/health").status_code == 429
        assert client.get("/health").status_code == 200


def test_unknown_paths_cannot_rotate_memory_rate_limit_buckets() -> None:
    with TestClient(_app(default_per_minute=1)) as client:
        assert client.get("/first-unknown-path").status_code == 404
        assert client.get("/second-unknown-path").status_code == 429


def test_scan_job_status_reads_have_a_separate_polling_budget() -> None:
    with TestClient(_app(default_per_minute=1)) as client:
        submitted = client.post("/api/v1/scan/jobs/product")
        first_poll = client.get("/api/v1/scan/jobs/job-test")
        second_poll = client.get("/api/v1/scan/jobs/job-test")

    assert submitted.status_code == 200
    assert submitted.headers["X-RateLimit-Limit"] == "15"
    assert first_poll.status_code == 200
    assert second_poll.status_code == 200
    assert first_poll.headers["X-RateLimit-Limit"] == "120"


def test_scan_submission_budget_is_isolated_per_authenticated_owner() -> None:
    redis = FakeRedis()
    app = _app(backend="redis", redis_client=redis, fail_closed=True)
    first_token, _ = create_session_token(
        User(
            id="scan-owner-a",
            google_subject="scan-a",
            email="scan-a@example.com",
            name="Scan A",
            avatar_url=None,
        )
    )
    second_token, _ = create_session_token(
        User(
            id="scan-owner-b",
            google_subject="scan-b",
            email="scan-b@example.com",
            name="Scan B",
            avatar_url=None,
        )
    )

    with TestClient(app) as client:
        first = client.post(
            "/api/v1/scan/jobs/product",
            headers={"Authorization": f"Bearer {first_token}"},
        )
        same_owner = client.post(
            "/api/v1/scan/jobs/product",
            headers={"Authorization": f"Bearer {first_token}"},
        )
        other_owner = client.post(
            "/api/v1/scan/jobs/product",
            headers={"Authorization": f"Bearer {second_token}"},
        )

    assert first.headers["X-RateLimit-Remaining"] == "14"
    assert same_owner.headers["X-RateLimit-Remaining"] == "13"
    assert other_owner.headers["X-RateLimit-Remaining"] == "14"
    assert len(redis.counts) == 2


def test_operational_logging_correlates_without_recording_credentials(caplog: Any) -> None:
    app = FastAPI()
    app.add_middleware(OperationalLoggingMiddleware)

    @app.get("/private")
    def private() -> dict[str, bool]:
        return {"ok": True}

    caplog.set_level("INFO", logger="nutrilens.operations")
    with TestClient(app) as client:
        response = client.get(
            "/private?health_note=secret",
            headers={
                "Authorization": "Bearer should-never-be-logged",
                "X-Request-ID": "client-request-123",
            },
        )

    assert response.headers["X-Request-ID"] == "client-request-123"
    logged = "\n".join(record.message for record in caplog.records)
    assert '"event":"http_request_complete"' in logged
    assert '"request_id":"client-request-123"' in logged
    assert "should-never-be-logged" not in logged
    assert "health_note" not in logged
    assert "secret" not in logged
