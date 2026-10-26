"""Durable, owner-scoped scan dispatch backed by PostgreSQL and Redis wake-ups."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import UTC, date, datetime
from typing import Any, cast

import redis.asyncio as redis_async
from redis.exceptions import RedisError

from ai.food_understanding.pipeline import ImagePayload
from ai.food_understanding.schemas import InputKind, ViewType
from backend.ai_worker_client import RemoteAIWorkerError, run_remote_scan
from backend.settings import settings

_WAKE_QUEUE = "nutrilens:scan-jobs:wake:v1"


class ScanJobDispatcher:
    """Dispatch durable jobs while heavy inference stays isolated in the OCI worker."""

    def __init__(self) -> None:
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._runner: asyncio.Task[None] | None = None
        self._active: set[asyncio.Task[None]] = set()
        self._redis = redis_async.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )

    async def start(self) -> None:
        if self._runner is None:
            self._runner = asyncio.create_task(self._run(), name="scan-job-dispatcher")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._runner is not None:
            await self._runner
        for task in tuple(self._active):
            task.cancel()
        if self._active:
            await asyncio.gather(*self._active, return_exceptions=True)
        await self._redis.aclose()

    async def enqueue(self, job_id: str) -> None:
        """Persisted PostgreSQL state is authoritative; Redis only wakes a dispatcher quickly."""
        self._wake.set()
        try:
            await self._redis.lpush(_WAKE_QUEUE, job_id)
            await self._redis.expire(_WAKE_QUEUE, settings.scan_job_queue_ttl_seconds)
        except (RedisError, OSError):
            # The periodic durable-store sweep still dispatches work safely.
            return

    async def _run(self) -> None:
        while not self._stop.is_set():
            available = settings.scan_job_dispatch_concurrency - len(self._active)
            if available > 0:
                claimed = await asyncio.to_thread(self._claim, available)
                for job in claimed:
                    task = asyncio.create_task(self._process(job), name=f"scan-job:{job['job_id']}")
                    self._active.add(task)
                    task.add_done_callback(self._active.discard)
            self._wake.clear()
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=settings.scan_job_poll_seconds)

    @staticmethod
    def _claim(limit: int) -> list[dict[str, object]]:
        if postgres_store is None:
            return []
        return postgres_store.claim_scan_jobs(limit)

    async def _process(self, job: dict[str, object]) -> None:
        if postgres_store is None:
            return
        job_id = str(job["job_id"])
        user_id = str(job["user_id"])
        lease_token = str(job["lease_token"])
        images = cast(list[tuple[str, str, bytes]], job.get("images", []))
        try:
            # Reconstruct the per-image view type list without trusting a caller
            # after the durable job was accepted.
            view_types = [ViewType(value) for value in cast(list[str], job["view_types"])]
            payloads = [
                ImagePayload(content, filename, mime_type, view_types[index])
                for index, (filename, mime_type, content) in enumerate(images)
            ]
            result = await asyncio.wait_for(
                run_remote_scan(
                    payloads,
                    input_kind=InputKind(str(job["input_kind"])),
                    languages=[str(value) for value in cast(list[Any], job["languages"])],
                    trace_id=f"job-{job_id}",
                ),
                timeout=settings.scan_job_timeout_seconds,
            )
            await asyncio.to_thread(
                postgres_store.complete_scan_job,
                user_id=user_id,
                job_id=job_id,
                lease_token=lease_token,
                result=result.model_dump(mode="json"),
            )
        except TimeoutError:
            await self._fail(job, "TIMED_OUT", "The scan exceeded its processing deadline.", True)
        except RemoteAIWorkerError:
            await self._fail(
                job,
                "AI_WORKER_UNAVAILABLE",
                (
                    "Enhanced scan is temporarily unavailable. "
                    "Please try a clearer photo or retry later."
                ),
                True,
            )
        except (ValueError, OSError):
            await self._fail(job, "INVALID_SCAN", "The scan input could not be processed.", False)
        except Exception:
            await self._fail(job, "SCAN_FAILED", "The scan could not be completed safely.", True)

    async def _fail(
        self, job: dict[str, object], error_code: str, error_message: str, retryable: bool
    ) -> None:
        if postgres_store is None:
            return
        now = datetime.now(UTC)
        await asyncio.to_thread(
            postgres_store.fail_scan_job,
            user_id=str(job["user_id"]),
            job_id=str(job["job_id"]),
            lease_token=str(job["lease_token"]),
            error_code=error_code,
            error_message=error_message,
            retryable=retryable,
            period_start=date(now.year, now.month, 1),
        )


dispatcher = ScanJobDispatcher()

# Imported lazily to avoid a settings/storage import cycle during module startup.
from backend.storage_runtime import postgres_store  # noqa: E402
