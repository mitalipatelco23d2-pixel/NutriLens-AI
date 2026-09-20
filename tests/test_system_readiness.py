from __future__ import annotations

from types import SimpleNamespace

from backend.app.core.config import get_settings
from backend.app.schemas.common import DependencyStatus
from backend.app.services import system_readiness


class RiskService:
    def __init__(self, ready: bool) -> None:
        self.ready = ready

    def readiness(self):
        return (
            self.ready,
            "risk ready" if self.ready else "risk unavailable",
        )


def test_nutrition_scoring_readiness_exercises_integrated_rules():
    assert system_readiness.nutrition_scoring_readiness() == (
        True,
        "M2 deterministic per-100-g nutrition scoring is available.",
    )


def test_required_dependency_evaluation_ignores_optional_unavailability():
    dependencies = {
        name: DependencyStatus(
            ready=True,
            detail="ready",
            metadata={"required": True, "enabled": True},
        )
        for name in system_readiness.REQUIRED_COMPONENTS
    }
    dependencies["optional"] = DependencyStatus(
        ready=False,
        detail="disabled",
        metadata={"required": False, "enabled": False},
    )

    assert system_readiness.required_dependencies_ready(dependencies) is True


def test_required_dependency_evaluation_rejects_missing_required_key():
    dependencies = {
        name: DependencyStatus(
            ready=True,
            detail="ready",
            metadata={"required": True, "enabled": True},
        )
        for name in system_readiness.REQUIRED_COMPONENTS
        if name != "ingredient_risk"
    }

    assert system_readiness.required_dependencies_ready(dependencies) is False


def test_build_readiness_reports_integrated_components(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        system_readiness,
        "tesseract_readiness",
        lambda active_settings: (True, "tesseract ready"),
    )
    monkeypatch.setattr(
        system_readiness,
        "get_m2_health_predictor",
        lambda: SimpleNamespace(risk_service=RiskService(True)),
    )

    dependencies = system_readiness.build_readiness_dependencies(settings)

    assert "model" not in dependencies
    assert dependencies["backend_api"].ready is True
    assert dependencies["nutrition_scoring"].ready is True
    assert dependencies["ingredient_risk"].ready is True
    assert dependencies["ingredient_risk"].metadata == {
        "required": True,
        "enabled": True,
        "expected_sklearn_version": "1.9.1",
        "runtime_sklearn_version": "1.9.1",
    }
    assert dependencies["knowledge_base"].metadata["required"] is False
    assert dependencies["shap"].metadata["enabled"] is False
    assert dependencies["rag"].metadata["enabled"] is False
    assert dependencies["rag"].metadata["live_request_performed"] is False
    assert system_readiness.required_dependencies_ready(dependencies) is True


def test_required_risk_classifier_failure_makes_system_not_ready(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        system_readiness,
        "tesseract_readiness",
        lambda active_settings: (True, "tesseract ready"),
    )
    monkeypatch.setattr(
        system_readiness,
        "get_m2_health_predictor",
        lambda: SimpleNamespace(risk_service=RiskService(False)),
    )

    dependencies = system_readiness.build_readiness_dependencies(settings)

    assert dependencies["ingredient_risk"].ready is False
    assert system_readiness.required_dependencies_ready(dependencies) is False
