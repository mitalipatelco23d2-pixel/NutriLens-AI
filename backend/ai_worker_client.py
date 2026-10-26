"""Authenticated dispatch from the business API to the private AI worker."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from urllib.parse import urlparse

import httpx

from ai.food_understanding.pipeline import ImagePayload
from ai.food_understanding.schemas import InputKind, R3ScanResult
from backend.settings import settings

logger = logging.getLogger(__name__)
CAPACITY_ERROR_HEADER = "X-NutriLens-Worker-Error"
CAPACITY_ERROR_VALUE = "capacity-full"
_MAX_CAPACITY_RETRY_DELAY_SECONDS = 10.0
_AZURE_WORKER_HOST_SUFFIXES = (".azurecontainerapps.io", ".azurewebsites.net")
SUPPORTED_AI_WORKER_PROVIDERS = frozenset({"azure", "oci"})


class RemoteAIWorkerError(RuntimeError):
    """A bounded, safe-to-show remote-worker failure."""


def is_oci_worker_configuration(provider: str, worker_url: str) -> bool:
    """Return whether configuration truthfully identifies a non-Azure OCI worker."""
    parsed = urlparse(worker_url.rstrip("/"))
    hostname = (parsed.hostname or "").casefold()
    return (
        provider == "oci"
        and parsed.scheme == "https"
        and bool(hostname)
        and not hostname.endswith(_AZURE_WORKER_HOST_SUFFIXES)
    )


def is_azure_worker_configuration(provider: str, worker_url: str) -> bool:
    """Return whether configuration truthfully identifies an Azure fallback worker."""
    parsed = urlparse(worker_url.rstrip("/"))
    hostname = (parsed.hostname or "").casefold()
    return (
        provider == "azure"
        and parsed.scheme == "https"
        and hostname.endswith(_AZURE_WORKER_HOST_SUFFIXES)
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def is_supported_worker_configuration(provider: str, worker_url: str) -> bool:
    """Return whether configuration truthfully identifies an authenticated fallback worker."""
    if provider == "oci":
        return is_oci_worker_configuration(provider, worker_url)
    if provider == "azure":
        return is_azure_worker_configuration(provider, worker_url)
    return False


def _endpoint() -> str:
    if (
        settings.app_environment != "development"
        and settings.ai_worker_provider not in SUPPORTED_AI_WORKER_PROVIDERS
    ):
        logger.warning(
            "Production AI worker provider must be one of: %s",
            sorted(SUPPORTED_AI_WORKER_PROVIDERS),
        )
        raise RemoteAIWorkerError("Production AI worker provider is not configured safely.")
    base = settings.ai_worker_url.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        logger.warning("AI worker endpoint is not configured with a valid URL")
        raise RemoteAIWorkerError("AI worker endpoint is not configured safely.")
    if settings.app_environment != "development" and parsed.scheme != "https":
        logger.warning("AI worker endpoint must use HTTPS host=%s", parsed.netloc)
        raise RemoteAIWorkerError("Production AI worker endpoint must use HTTPS.")
    if settings.app_environment != "development" and not is_supported_worker_configuration(
        settings.ai_worker_provider, base
    ):
        logger.warning(
            "Production AI worker endpoint is not configured safely for provider=%s host=%s",
            settings.ai_worker_provider,
            parsed.netloc,
        )
        raise RemoteAIWorkerError("Production AI worker endpoint is not configured safely.")
    if not settings.ai_worker_token:
        logger.warning("AI worker credential is not configured")
        raise RemoteAIWorkerError("AI worker credential is unavailable.")
    return f"{base}/internal/r3/scan"


def _is_capacity_response(response: httpx.Response) -> bool:
    """Only an explicit pre-inference rejection is safe to retry automatically."""
    return (
        response.status_code == 503
        and response.headers.get(CAPACITY_ERROR_HEADER, "").casefold() == CAPACITY_ERROR_VALUE
    )


def _capacity_retry_delay_seconds(
    *, trace_id: str, retry_number: int, retry_after: str | None
) -> float:
    base = max(0.0, settings.ai_worker_capacity_retry_base_seconds)
    exponential = min(_MAX_CAPACITY_RETRY_DELAY_SECONDS, base * (2 ** (retry_number - 1)))
    # Stable per-job jitter prevents a burst from retrying every request in lockstep.
    digest = hashlib.sha256(f"{trace_id}:{retry_number}".encode()).digest()
    jitter = (int.from_bytes(digest[:2], "big") / 65535) * min(base, 1.0)
    try:
        server_minimum = max(0.0, float(retry_after or "0"))
    except ValueError:
        server_minimum = 0.0
    return float(max(server_minimum, exponential + jitter))


async def run_remote_scan(
    payloads: list[ImagePayload],
    *,
    input_kind: InputKind,
    languages: list[str],
    trace_id: str,
) -> R3ScanResult:
    endpoint = _endpoint()
    files: list[tuple[str, tuple[str, bytes, str]]] = [
        ("files", (payload.filename, payload.content, payload.mime_type)) for payload in payloads
    ]
    data = {
        "input_kind": input_kind.value,
        "view_types": ",".join(payload.view_type.value for payload in payloads),
        "languages": ",".join(languages[:4]),
        "trace_id": trace_id,
    }
    timeout = httpx.Timeout(settings.r3_scan_timeout_seconds + 5.0, connect=10.0)
    max_attempts = max(1, settings.ai_worker_capacity_retry_attempts)
    response: httpx.Response | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            # A fresh connection lets the configured provider route a rejected
            # request to a worker that became ready after the prior attempt.
            # Ambiguous transport failures are never retried because inference may
            # already have started.
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.post(
                    endpoint,
                    data=data,
                    files=files,
                    headers={"Authorization": f"Bearer {settings.ai_worker_token}"},
                )
        except httpx.HTTPError as exc:
            logger.warning(
                "AI worker transport failed host=%s error=%s",
                urlparse(settings.ai_worker_url).netloc or "unconfigured",
                type(exc).__name__,
            )
            raise RemoteAIWorkerError("Private AI worker is temporarily unavailable.") from exc
        if not _is_capacity_response(response) or attempt == max_attempts:
            break
        delay = _capacity_retry_delay_seconds(
            trace_id=trace_id,
            retry_number=attempt,
            retry_after=response.headers.get("Retry-After"),
        )
        logger.info(
            "AI worker capacity full host=%s attempt=%s/%s retry_in_seconds=%.2f",
            urlparse(settings.ai_worker_url).netloc or "unconfigured",
            attempt,
            max_attempts,
            delay,
        )
        await asyncio.sleep(delay)
    if response is None:  # pragma: no cover - the loop always executes at least once
        raise RemoteAIWorkerError("Private AI worker is temporarily unavailable.")
    if response.status_code != 200:
        logger.warning(
            "AI worker rejected scan host=%s status=%s",
            urlparse(settings.ai_worker_url).netloc or "unconfigured",
            response.status_code,
        )
        raise RemoteAIWorkerError("Private AI worker could not process this scan.")
    try:
        return R3ScanResult.model_validate(response.json())
    except ValueError as exc:
        raise RemoteAIWorkerError("Private AI worker returned an invalid scan result.") from exc
