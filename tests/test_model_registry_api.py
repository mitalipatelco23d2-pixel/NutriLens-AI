from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.auth import User, create_session_token, current_user, user_store
from backend.entitlements import PlanCode, SpecialRole, SubscriptionStatus
from backend.main import app
from backend.model_registry_api import load_model_registry


def _headers() -> dict[str, str]:
    user = user_store.upsert_google_user(
        {
            "sub": "registry-consumer",
            "email": "registry@example.com",
            "email_verified": True,
        }
    )
    token, _ = create_session_token(user)
    return {"Authorization": f"Bearer {token}"}


def test_registry_loads_governed_models_and_held_out_metrics() -> None:
    registry = load_model_registry()

    assert registry.registry_version == "1.0.0"
    assert len(registry.models) >= 6
    custom = next(
        model for model in registry.models if model.training_status == "CUSTOM_FINE_TUNED"
    )
    assert custom.checksum
    assert custom.dataset_version
    assert custom.metrics["held_out_test"]["map50"] > 0
    # A checked-in/locally mounted artifact may be present without a verified
    # checksum; the API exposes that distinction instead of overstating
    # deployment readiness.
    assert custom.artifact_status in {"NOT_INSTALLED", "PRESENT", "CHECKSUM_VERIFIED"}


def test_registry_api_requires_administrator_role() -> None:
    response = TestClient(app).get("/api/v1/system/models", headers=_headers())

    assert response.status_code == 403


def test_registry_api_returns_metadata_to_administrator() -> None:
    admin = User(
        id="registry-admin",
        google_subject="registry-admin",
        email="admin@example.com",
        name="Registry Admin",
        avatar_url=None,
        plan=PlanCode.FREE,
        subscription_status=SubscriptionStatus.FREE,
        roles=frozenset({SpecialRole.ADMIN}),
    )
    app.dependency_overrides[current_user] = lambda: admin
    try:
        response = TestClient(app).get("/api/v1/system/models")
    finally:
        app.dependency_overrides.pop(current_user, None)

    assert response.status_code == 200
    assert response.json()["download_policy"] == "OPT_IN_ONLY"
    assert "deployment readiness" in response.json()["claims_boundary"]


def test_admin_feature_endpoint_returns_no_raw_text_or_identifiers(monkeypatch) -> None:
    import backend.model_registry_api as registry_api

    admin = User(
        id="feature-admin",
        google_subject="feature-admin",
        email="feature-admin@example.com",
        name="Feature Admin",
        avatar_url=None,
        plan=PlanCode.FREE,
        subscription_status=SubscriptionStatus.FREE,
        roles=frozenset({SpecialRole.ADMIN}),
    )
    scan = SimpleNamespace(
        contract_version="3.0.0",
        scan_id="private-scan-id",
        ingredients=SimpleNamespace(),
        nutrition=SimpleNamespace(),
        confidence_summary=SimpleNamespace(numeric_score=0.8),
        ocr_results={"front": SimpleNamespace(text="private label text")},
        barcode_results=[],
        product_name_candidates=[],
    )
    intelligence = SimpleNamespace(
        contract_version="4.0.0",
        confidence=SimpleNamespace(resolved_ingredient_ratio=1),
        complexity=SimpleNamespace(
            ingredient_count=1,
            additive_count=0,
            unresolved_count=0,
            compound_ingredient_count=0,
        ),
        allergens=[],
        hidden_sugars=SimpleNamespace(signals=[]),
        sodium_sources=SimpleNamespace(signals=[]),
        oils_and_fats=SimpleNamespace(signals=[]),
        sweeteners=SimpleNamespace(signals=[]),
        preservatives=SimpleNamespace(signals=[]),
        nova=SimpleNamespace(group_number=1),
    )
    monkeypatch.setattr(registry_api, "get_owned_scan_result", lambda scan_id, user: scan)
    monkeypatch.setattr(
        registry_api,
        "get_r4_service",
        lambda: SimpleNamespace(analyze=lambda ingredients, nutrition: intelligence),
    )
    app.dependency_overrides[current_user] = lambda: admin
    try:
        response = TestClient(app).get("/api/v1/system/models/features/scans/private")
    finally:
        app.dependency_overrides.pop(current_user, None)

    assert response.status_code == 200
    assert response.json()["values"]["ingredient_count"] == 1
    assert "private-scan-id" not in response.text
    assert "private label text" not in response.text
