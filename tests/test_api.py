from fastapi.testclient import TestClient

from backend.main import app
from backend.service_health import clear_service_health_cache, collect_service_health
from backend.settings import Settings


def test_legacy_ungoverned_scoring_route_is_not_exposed():
    response = TestClient(app).post(
        "/api/v1/analyze",
        json={"ingredients": "sugar", "nutrients": {}},
    )
    assert response.status_code == 404


def test_health_reports_each_foundation_service(monkeypatch):
    clear_service_health_cache()
    monkeypatch.setattr("backend.service_health.check_postgres", lambda _: "healthy")
    monkeypatch.setattr("backend.service_health.check_mongodb", lambda _: "healthy")
    monkeypatch.setattr("backend.service_health.check_neo4j", lambda _: "healthy")
    monkeypatch.setattr("backend.service_health.check_redis", lambda _: "healthy")
    result = collect_service_health(Settings())
    assert result == {
        "api": "healthy",
        "postgres": "healthy",
        "mongodb": "healthy",
        "neo4j": "healthy",
        "redis": "healthy",
    }

    assert collect_service_health(Settings()) == result


def test_liveness_does_not_probe_dependencies(monkeypatch):
    monkeypatch.setattr(
        "backend.main.collect_service_health",
        lambda _: (_ for _ in ()).throw(AssertionError("readiness probe called")),
    )
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["services"] == {"api": "healthy"}


def test_health_endpoint_reports_degraded_state(monkeypatch):
    monkeypatch.setattr(
        "backend.main.collect_service_health",
        lambda _: {
            "api": "healthy",
            "postgres": "unavailable",
            "mongodb": "healthy",
            "neo4j": "healthy",
            "redis": "healthy",
        },
    )
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["services"]["postgres"] == "unavailable"


def test_liveness_reports_only_a_valid_deployed_revision(monkeypatch):
    from backend.main import liveness

    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    assert liveness()["source_revision"] is None
    monkeypatch.setenv("RENDER_GIT_COMMIT", "non-revision-value-must-not-be-exposed")
    assert liveness()["source_revision"] is None
    monkeypatch.setenv("RENDER_GIT_COMMIT", "A" * 40)
    assert liveness()["source_revision"] == "a" * 40
