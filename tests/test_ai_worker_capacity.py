"""Capacity rejection must be explicit, bounded, and safe to retry."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace

import httpx
import pytest
from fastapi.testclient import TestClient

from ai.food_understanding.pipeline import ImagePayload
from ai.food_understanding.schemas import (
    ConfidenceLevel,
    ConfidenceSummary,
    InputKind,
    R3ScanResult,
    Timing,
    ViewType,
)


def _result_payload() -> dict[str, object]:
    return R3ScanResult(
        scan_id="worker-result",
        trace_id="capacity-test",
        status="COMPLETED",
        input_kind=InputKind.PRODUCT,
        input_metadata=[],
        image_quality={},
        preprocessing={},
        confidence_summary=ConfidenceSummary(level=ConfidenceLevel.MEDIUM),
        timings=Timing(
            validation_ms=0,
            quality_ms=0,
            preprocessing_ms=0,
            detection_ms=0,
            barcode_qr_ms=0,
            ocr_ms=0,
            extraction_ms=0,
            total_ms=0,
        ),
    ).model_dump(mode="json")


def _payload() -> ImagePayload:
    return ImagePayload(b"image", "label.png", "image/png", ViewType.GENERAL)


def test_production_client_rejects_unsupported_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.ai_worker_client as worker_client

    monkeypatch.setattr(
        worker_client,
        "settings",
        replace(
            worker_client.settings,
            app_environment="production",
            ai_worker_provider="unsupported",
            ai_worker_url="https://worker.example.test",
            ai_worker_token="worker-secret",
        ),
    )

    with pytest.raises(worker_client.RemoteAIWorkerError, match="provider"):
        asyncio.run(
            worker_client.run_remote_scan(
                [_payload()],
                input_kind=InputKind.PRODUCT,
                languages=["en"],
                trace_id="job-provider-gate",
            )
        )


def test_production_client_rejects_azure_host_mislabeled_as_oci(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.ai_worker_client as worker_client

    monkeypatch.setattr(
        worker_client,
        "settings",
        replace(
            worker_client.settings,
            app_environment="production",
            ai_worker_provider="oci",
            ai_worker_url="https://worker.centralindia.azurecontainerapps.io",
            ai_worker_token="worker-secret",
        ),
    )

    with pytest.raises(worker_client.RemoteAIWorkerError, match="endpoint"):
        asyncio.run(
            worker_client.run_remote_scan(
                [_payload()],
                input_kind=InputKind.PRODUCT,
                languages=["en"],
                trace_id="job-provider-host-gate",
            )
        )


def test_worker_capacity_rejection_is_machine_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.ai_worker_api as worker_api

    class FullCapacity:
        async def acquire(self) -> None:
            raise TimeoutError

        def release(self) -> None:  # pragma: no cover - acquire never succeeds
            raise AssertionError("capacity rejection must not release an unacquired slot")

    monkeypatch.setattr(
        worker_api,
        "settings",
        replace(
            worker_api.settings,
            ai_worker_token="worker-secret",
            ai_worker_queue_timeout_seconds=0.01,
        ),
    )
    monkeypatch.setattr(worker_api, "_inference_slots", FullCapacity())
    response = TestClient(worker_api.app).post(
        "/internal/r3/scan",
        headers={"Authorization": "Bearer worker-secret"},
        files=[("files", ("label.png", b"image", "image/png"))],
        data={
            "input_kind": "PRODUCT",
            "view_types": "GENERAL",
            "languages": "en",
            "trace_id": "capacity-test",
        },
    )

    assert response.status_code == 503
    assert response.headers["X-NutriLens-Worker-Error"] == "capacity-full"
    assert response.headers["Retry-After"] == "2"


def _async_client_factory(
    responses: list[httpx.Response], created: list[int]
) -> Callable[..., httpx.AsyncClient]:
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    def factory(**kwargs: object) -> httpx.AsyncClient:
        created.append(1)
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    return factory


def test_client_retries_explicit_capacity_with_fresh_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.ai_worker_client as worker_client

    created: list[int] = []
    responses = [
        httpx.Response(
            503,
            headers={"X-NutriLens-Worker-Error": "capacity-full", "Retry-After": "0"},
        ),
        httpx.Response(
            503,
            headers={"X-NutriLens-Worker-Error": "capacity-full", "Retry-After": "0"},
        ),
        httpx.Response(200, json=_result_payload()),
    ]
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(
        worker_client,
        "settings",
        replace(
            worker_client.settings,
            app_environment="production",
            ai_worker_provider="oci",
            ai_worker_url="https://worker.example.test",
            ai_worker_token="worker-secret",
            ai_worker_capacity_retry_attempts=3,
            ai_worker_capacity_retry_base_seconds=0,
        ),
    )
    monkeypatch.setattr(
        worker_client.httpx,
        "AsyncClient",
        _async_client_factory(responses, created),
    )
    monkeypatch.setattr(worker_client.asyncio, "sleep", fake_sleep)

    result = asyncio.run(
        worker_client.run_remote_scan(
            [_payload()], input_kind=InputKind.PRODUCT, languages=["en"], trace_id="job-a"
        )
    )

    assert result.scan_id == "worker-result"
    assert len(created) == 3
    assert sleeps == [0, 0]


def test_client_does_not_retry_ambiguous_service_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.ai_worker_client as worker_client

    created: list[int] = []
    responses = [httpx.Response(503, json={"detail": "inference unavailable"})]
    monkeypatch.setattr(
        worker_client,
        "settings",
        replace(
            worker_client.settings,
            app_environment="production",
            ai_worker_provider="oci",
            ai_worker_url="https://worker.example.test",
            ai_worker_token="worker-secret",
            ai_worker_capacity_retry_attempts=8,
        ),
    )
    monkeypatch.setattr(
        worker_client.httpx,
        "AsyncClient",
        _async_client_factory(responses, created),
    )

    with pytest.raises(worker_client.RemoteAIWorkerError):
        asyncio.run(
            worker_client.run_remote_scan(
                [_payload()],
                input_kind=InputKind.PRODUCT,
                languages=["en"],
                trace_id="job-b",
            )
        )

    assert len(created) == 1


def test_client_capacity_retry_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.ai_worker_client as worker_client

    created: list[int] = []
    responses = [
        httpx.Response(503, headers={"X-NutriLens-Worker-Error": "capacity-full"}),
        httpx.Response(503, headers={"X-NutriLens-Worker-Error": "capacity-full"}),
    ]

    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr(
        worker_client,
        "settings",
        replace(
            worker_client.settings,
            app_environment="production",
            ai_worker_provider="oci",
            ai_worker_url="https://worker.example.test",
            ai_worker_token="worker-secret",
            ai_worker_capacity_retry_attempts=2,
            ai_worker_capacity_retry_base_seconds=0,
        ),
    )
    monkeypatch.setattr(
        worker_client.httpx,
        "AsyncClient",
        _async_client_factory(responses, created),
    )
    monkeypatch.setattr(worker_client.asyncio, "sleep", fake_sleep)

    with pytest.raises(worker_client.RemoteAIWorkerError):
        asyncio.run(
            worker_client.run_remote_scan(
                [_payload()],
                input_kind=InputKind.PRODUCT,
                languages=["en"],
                trace_id="job-c",
            )
        )

    assert len(created) == 2


@pytest.mark.parametrize(
    "url, accepted",
    [
        ("https://worker.centralindia.azurecontainerapps.io", True),
        ("https://worker.azurewebsites.net", True),
        ("https://worker.example.test", False),
        ("http://worker.azurewebsites.net", False),
        ("https://worker.azurewebsites.net.attacker.test", False),
        ("https://user:password@worker.azurewebsites.net", False),
        ("https://worker.azurewebsites.net?token=x", False),
    ],
)
def test_temporary_azure_provider_requires_truthful_https_host(url, accepted):
    from backend.ai_worker_client import is_supported_worker_configuration

    assert is_supported_worker_configuration("azure", url) is accepted
