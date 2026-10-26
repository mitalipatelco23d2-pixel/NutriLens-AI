"""HTTP security middleware for local and horizontally scaled public modes."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from hashlib import sha256
from threading import RLock
from time import monotonic, perf_counter
from typing import Any, Literal
from uuid import uuid4

import redis.asyncio as redis_async
from fastapi import Request, Response, status
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware

_operations_logger = logging.getLogger("nutrilens.operations")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,80}$")
_REDIS_RATE_LIMIT_ATTEMPTS = 2
_REDIS_RATE_LIMIT_RETRY_SECONDS = 0.1


class OperationalLoggingMiddleware(BaseHTTPMiddleware):
    """Emit a minimal request-completion event without request content or credentials."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        supplied_request_id = request.headers.get("x-request-id", "")
        request_id = (
            supplied_request_id
            if _REQUEST_ID.fullmatch(supplied_request_id)
            else f"req-{uuid4().hex}"
        )
        started = perf_counter()
        response_status = status.HTTP_500_INTERNAL_SERVER_ERROR
        try:
            response = await call_next(request)
            response_status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            event = {
                "event": "http_request_complete",
                "request_id": request_id,
                "method": request.method,
                "status": response_status,
                "duration_ms": round((perf_counter() - started) * 1000, 2),
            }
            _operations_logger.info(json.dumps(event, separators=(",", ":")))


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Cache-Control"] = (
            "no-store"
            if "/auth/" in request.url.path
            or request.url.path.startswith(
                ("/api/v1/hydration", "/api/v1/weight", "/api/v1/recipes/custom")
            )
            else "no-cache"
        )
        return response


_REDIS_WINDOW_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window protection with an atomic Redis public-mode backend."""

    def __init__(
        self,
        app: object,
        *,
        default_per_minute: int = 120,
        backend: Literal["memory", "redis"] | str = "memory",
        redis_url: str = "redis://localhost:6379/0",
        fail_closed: bool = False,
        redis_client: Any | None = None,
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        if backend not in {"memory", "redis"}:
            raise ValueError("Rate-limit backend must be 'memory' or 'redis'.")
        self.default_per_minute = default_per_minute
        self.backend = backend
        self.fail_closed = fail_closed
        self._requests: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = RLock()
        self._redis = (
            redis_client
            if redis_client is not None
            else redis_async.Redis.from_url(
                redis_url,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            if backend == "redis"
            else None
        )

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path == "/health":
            return await call_next(request)

        limit = self._limit_for(request.url.path, request.method)
        key = self._request_key(request)
        try:
            if self.backend == "redis":
                allowed, remaining, retry_after = await self._redis_hit(key, limit)
            else:
                allowed, remaining, retry_after = self._memory_hit(key, limit)
        except (RedisError, OSError):
            if self.fail_closed:
                return Response(
                    content='{"detail":"Rate limiting is temporarily unavailable."}',
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    media_type="application/json",
                    headers={"Retry-After": "5"},
                )
            allowed, remaining, retry_after = self._memory_hit(key, limit)

        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(remaining),
        }
        if not allowed:
            headers["Retry-After"] = str(retry_after)
            return Response(
                content='{"detail":"Rate limit exceeded."}',
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                media_type="application/json",
                headers=headers,
            )

        response = await call_next(request)
        response.headers.update(headers)
        return response

    async def _redis_hit(self, key: str, limit: int) -> tuple[bool, int, int]:
        if self._redis is None:
            raise RedisError("Redis rate limiter is not configured.")
        for attempt in range(_REDIS_RATE_LIMIT_ATTEMPTS):
            try:
                result = await self._redis.eval(_REDIS_WINDOW_SCRIPT, 1, key, 60)
                break
            except (RedisError, OSError):
                if attempt + 1 >= _REDIS_RATE_LIMIT_ATTEMPTS:
                    raise
                await asyncio.sleep(_REDIS_RATE_LIMIT_RETRY_SECONDS)
        count, ttl = int(result[0]), max(int(result[1]), 1)
        return count <= limit, max(limit - count, 0), ttl

    def _memory_hit(self, key: str, limit: int) -> tuple[bool, int, int]:
        now = monotonic()
        with self._lock:
            empty_keys: list[str] = []
            for candidate, candidate_bucket in self._requests.items():
                while candidate_bucket and now - candidate_bucket[0] >= 60:
                    candidate_bucket.popleft()
                if not candidate_bucket:
                    empty_keys.append(candidate)
            for candidate in empty_keys:
                self._requests.pop(candidate, None)
            bucket = self._requests[key]
            while bucket and now - bucket[0] >= 60:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, round(60 - (now - bucket[0])))
                return False, 0, retry_after
            bucket.append(now)
            return True, limit - len(bucket), 60

    def _request_key(self, request: Request) -> str:
        authorization = request.headers.get("authorization", "")
        subject: str | None = None
        if authorization.lower().startswith("bearer "):
            token = authorization.split(None, 1)[1].strip()
            try:
                from backend.auth import decode_session_token

                subject = decode_session_token(token)
            except Exception:
                subject = None
        host = request.client.host if request.client else "unknown"
        identity = f"subject:{subject}" if subject is not None else f"host:{host}"
        scope = self._scope_for(request.url.path, request.method)
        digest = sha256(f"{identity}:{scope}".encode()).hexdigest()
        return f"nutrilens:rate-limit:{digest}"

    def _scope_for(self, path: str, method: str) -> str:
        if method == "GET" and "/scan/jobs/" in path:
            return "scan_job_status"
        if "/scan/" in path or path.endswith("/scan"):
            return "scan"
        if "/auth/" in path:
            return "auth"
        if "/payments/" in path:
            return "payments"
        return "general"

    def _limit_for(self, path: str, method: str) -> int:
        if method == "GET" and "/scan/jobs/" in path:
            return 120
        if "/scan/" in path or path.endswith("/scan"):
            return 15
        if "/auth/" in path or "/payments/" in path:
            return 30
        return self.default_per_minute
