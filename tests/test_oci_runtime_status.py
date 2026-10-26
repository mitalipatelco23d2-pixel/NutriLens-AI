from __future__ import annotations

from dataclasses import replace

import backend.model_registry_api as model_registry_api
from backend.auth import User
from backend.entitlements import PlanCode, SpecialRole, SubscriptionStatus


def _admin() -> User:
    return User(
        id="oci-runtime-admin",
        google_subject=None,
        email="admin@example.test",
        name="Runtime Admin",
        avatar_url=None,
        plan=PlanCode.FREE,
        subscription_status=SubscriptionStatus.FREE,
        roles=frozenset({SpecialRole.ADMIN}),
    )


def test_runtime_status_rejects_unsupported_provider(monkeypatch) -> None:
    monkeypatch.setattr(model_registry_api, "collect_service_health", lambda _: {})
    monkeypatch.setattr(
        model_registry_api,
        "settings",
        replace(
            model_registry_api.settings,
            ai_worker_provider="unsupported_cloud",
            ai_worker_url="https://legacy-worker.example.test",
            ai_worker_token="configured-token",
        ),
    )

    status = model_registry_api.get_ai_runtime_status(_admin())

    assert "azure_ai_worker" not in status.components
    assert status.components["server_ai_worker"].state == "BLOCKED_EXTERNAL"
    assert (
        "Fallback AI worker is not configured or blocked."
        in status.components["server_ai_worker"].detail
    )


def test_runtime_status_reports_configured_azure_bridge_worker(monkeypatch) -> None:
    monkeypatch.setattr(model_registry_api, "collect_service_health", lambda _: {})
    monkeypatch.setattr(
        model_registry_api,
        "settings",
        replace(
            model_registry_api.settings,
            ai_worker_provider="azure",
            ai_worker_url="https://worker.centralindia.azurecontainerapps.io",
            ai_worker_token="azure-secret",
            ai_runtime_public_validated=True,
        ),
    )

    status = model_registry_api.get_ai_runtime_status(_admin())

    assert status.components["server_ai_worker"].state == "READY_PUBLIC"
    assert status.components["server_ai_worker"].detail == (
        "Authenticated Azure AI worker fallback bridge is configured."
    )


def test_runtime_status_reports_configured_oci_worker(monkeypatch) -> None:
    monkeypatch.setattr(model_registry_api, "collect_service_health", lambda _: {})
    monkeypatch.setattr(
        model_registry_api,
        "settings",
        replace(
            model_registry_api.settings,
            ai_worker_provider="oci",
            ai_worker_url="https://ai-worker.example.test",
            ai_worker_token="server-secret",
            ai_runtime_public_validated=True,
        ),
    )

    status = model_registry_api.get_ai_runtime_status(_admin())

    assert status.components["server_ai_worker"].state == "READY_PUBLIC"
    assert status.components["server_ai_worker"].detail == (
        "Authenticated OCI AI worker is configured."
    )


def test_runtime_status_rejects_azure_host_mislabeled_as_oci(monkeypatch) -> None:
    monkeypatch.setattr(model_registry_api, "collect_service_health", lambda _: {})
    monkeypatch.setattr(
        model_registry_api,
        "settings",
        replace(
            model_registry_api.settings,
            ai_worker_provider="oci",
            ai_worker_url="https://legacy.centralindia.azurecontainerapps.io",
            ai_worker_token="configured-but-rejected",
            ai_runtime_public_validated=True,
        ),
    )

    status = model_registry_api.get_ai_runtime_status(_admin())

    assert status.components["server_ai_worker"].state == "BLOCKED_EXTERNAL"
