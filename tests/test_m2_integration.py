from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.api import routes
from backend.app.core.errors import InvalidModelInputError, ModelUnavailableError
from backend.app.main import create_app
from backend.app.models.health_risk import IngredientRiskService
from backend.app.ocr.extractor import OcrResult
from backend.app.ocr.preprocessing import PreparedImage
from backend.app.ocr.service import OcrExecution
from backend.app.services import team_pipeline as team_pipeline_module
from backend.app.services.m2 import M2HealthPredictor
from backend.app.services.team_pipeline import TeamAnalysisPipeline


def nlp_result(*, basis: str = "per_100g", omit: str | None = None) -> dict:
    nutrition = {
        "sugars_100g": 25.0,
        "saturated_fat_100g": 6.0,
        "trans_fat_100g": 0.0,
        "sodium_100g": 0.4,
    }
    if omit:
        nutrition.pop(omit)
    return {
        "basis": basis,
        "nutrition": nutrition,
        "ingredients": ["Oats", "Brown Sugar"],
        "additives": ["INS 621", "Preservative"],
        "allergens": ["Milk"],
    }


class UnavailableRiskService:
    def predict(self, ingredients):
        raise ModelUnavailableError("Risk model artifact is unavailable.")


class AvailableRiskService:
    def predict(self, ingredients):
        assert ingredients == ["Oats", "Brown Sugar"]
        return {
            "risk_level": "MODERATE",
            "probabilities": {"LOW": 10.0, "MODERATE": 80.0, "HIGH": 10.0},
            "ingredient_text": "oats brown sugar",
            "model_version": "test",
        }


def test_both_m2_outputs_are_returned_when_risk_service_is_available():
    result = M2HealthPredictor(AvailableRiskService()).predict(nlp_result())

    assert result["status"] == "available"
    assert result["health_score"] == 72.0
    assert result["score_level"] == "GOOD"
    assert result["risk_level"] == "MODERATE"
    assert result["nutrition_score"]["nutrition_breakdown"]["sodium_penalty"] == 4.0
    assert result["ingredient_risk"]["probabilities"]["MODERATE"] == 80.0


def test_missing_nutrient_is_not_treated_as_zero():
    result = M2HealthPredictor(AvailableRiskService()).predict(
        nlp_result(omit="trans_fat_100g")
    )

    assert result["status"] == "partial"
    assert result["health_score"] is None
    assert result["nutrition_score"]["available"] is False
    assert result["nutrition_score"]["missing_nutrients"] == ["trans_fat_100g"]
    assert result["risk_level"] == "MODERATE"


@pytest.mark.parametrize("basis", ["per_100ml", "per_serving", "unknown"])
def test_non_100g_basis_is_preserved_and_never_converted(basis):
    result = M2HealthPredictor(AvailableRiskService()).predict(nlp_result(basis=basis))

    assert result["basis"] == basis
    assert result["nutrition_score"]["basis"] == basis
    assert result["health_score"] is None
    assert "no basis conversion" in result["nutrition_score"]["detail"]


def test_missing_lfs_artifacts_leave_risk_unavailable_but_keep_nutrition_score():
    result = M2HealthPredictor(UnavailableRiskService()).predict(nlp_result())

    assert result["status"] == "partial"
    assert result["health_score"] == 72.0
    assert result["risk_level"] is None
    assert result["ingredient_risk"] == {
        "available": False,
        "risk_level": None,
        "probabilities": {},
        "detail": "Risk model artifact is unavailable.",
    }


def test_original_nutrition_penalty_cap_is_preserved():
    extreme = nlp_result()
    extreme["nutrition"] = {
        "sugars_100g": 30.0,
        "saturated_fat_100g": 10.0,
        "trans_fat_100g": 1.0,
        "sodium_100g": 1.0,
    }
    extreme["additives"] = []

    result = M2HealthPredictor(AvailableRiskService()).predict(extreme)
    assert result["health_score"] == 65.0
    assert result["nutrition_score"]["breakdown"]["nutrition_penalty"] == 35.0


def test_risk_service_checks_hashes_before_loader_can_run(tmp_path):
    model_path = tmp_path / "model.pkl"
    vectorizer_path = tmp_path / "vectorizer.pkl"
    model_path.write_bytes(b"not-a-model")
    vectorizer_path.write_bytes(b"not-a-vectorizer")
    loader_calls = []

    service = IngredientRiskService(
        model_path=model_path,
        vectorizer_path=vectorizer_path,
        expected_model_sha256="0" * 64,
        expected_vectorizer_sha256="0" * 64,
        loader=lambda path: loader_calls.append(path),
    )

    with pytest.raises(ModelUnavailableError, match="provenance check"):
        service.predict(["oats"])
    assert loader_calls == []


def test_risk_service_refuses_files_without_configured_provenance(tmp_path):
    model_path = tmp_path / "model.pkl"
    vectorizer_path = tmp_path / "vectorizer.pkl"
    model_path.write_bytes(b"not-a-model")
    vectorizer_path.write_bytes(b"not-a-vectorizer")
    loader_calls = []
    service = IngredientRiskService(
        model_path=model_path,
        vectorizer_path=vectorizer_path,
        expected_model_sha256=None,
        expected_vectorizer_sha256=None,
        loader=lambda path: loader_calls.append(path),
    )

    assert service.readiness() == (
        False,
        "Risk model provenance digest is not configured.",
    )
    with pytest.raises(ModelUnavailableError, match="provenance digest"):
        service.predict(["oats"])
    assert loader_calls == []


@pytest.mark.parametrize(
    "ingredients",
    [[], ["   "], "sugar", None, ["oats", None], ["oats", 7]],
)
def test_risk_service_rejects_empty_or_malformed_ingredients_before_loading(
    tmp_path, ingredients
):
    loader_calls = []
    service = IngredientRiskService(
        model_path=tmp_path / "model.pkl",
        vectorizer_path=tmp_path / "vectorizer.pkl",
        expected_model_sha256="0" * 64,
        expected_vectorizer_sha256="0" * 64,
        loader=lambda path: loader_calls.append(path),
    )

    with pytest.raises(InvalidModelInputError):
        service.predict(ingredients)
    assert loader_calls == []


def test_m2_adapter_rejects_non_collection_ingredients_without_calling_model():
    class RecordingRiskService:
        called = False

        def predict(self, ingredients):
            self.called = True
            raise AssertionError("Malformed input must not reach the model.")

    risk_service = RecordingRiskService()
    malformed = nlp_result()
    malformed["ingredients"] = "oats, sugar"

    result = M2HealthPredictor(risk_service).predict(malformed)
    assert risk_service.called is False
    assert result["status"] == "partial"
    assert result["ingredient_risk"]["available"] is False
    assert result["ingredient_risk"]["risk_level"] is None


def test_risk_service_rejects_incompatible_sklearn_before_loader(tmp_path):
    model_path = tmp_path / "model.pkl"
    vectorizer_path = tmp_path / "vectorizer.pkl"
    model_path.write_bytes(b"verified-test-model")
    vectorizer_path.write_bytes(b"verified-test-vectorizer")
    loader_calls = []
    service = IngredientRiskService(
        model_path=model_path,
        vectorizer_path=vectorizer_path,
        expected_model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
        expected_vectorizer_sha256=hashlib.sha256(
            vectorizer_path.read_bytes()
        ).hexdigest(),
        expected_sklearn_version="0.0-test-mismatch",
        loader=lambda path: loader_calls.append(path),
    )

    ready, detail = service.readiness()
    assert ready is False
    assert "require scikit-learn 0.0-test-mismatch" in detail
    with pytest.raises(ModelUnavailableError, match="runtime has"):
        service.predict(["oats"])
    assert loader_calls == []


def test_verified_risk_artifacts_can_use_an_injected_non_pickle_loader(tmp_path):
    model_path = tmp_path / "model.pkl"
    vectorizer_path = tmp_path / "vectorizer.pkl"
    model_path.write_bytes(b"verified-test-model")
    vectorizer_path.write_bytes(b"verified-test-vectorizer")

    class Vectorizer:
        def transform(self, values):
            assert values == ["oats, brown sugar"]
            return [[1.0]]

    class Model:
        classes_ = [0, 1, 2]

        def predict(self, features):
            return [2]

        def predict_proba(self, features):
            return [[0.05, 0.15, 0.8]]

    objects = {model_path: Model(), vectorizer_path: Vectorizer()}
    service = IngredientRiskService(
        model_path=model_path,
        vectorizer_path=vectorizer_path,
        expected_model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
        expected_vectorizer_sha256=hashlib.sha256(vectorizer_path.read_bytes()).hexdigest(),
        loader=objects.__getitem__,
    )

    assert service.readiness()[0] is True
    result = service.predict([" OATS ", "Brown   Sugar"])
    assert result["risk_level"] == "HIGH"
    assert result["probabilities"] == {"LOW": 5.0, "MODERATE": 15.0, "HIGH": 80.0}


def test_stable_analyze_endpoint_keeps_contract_with_partial_m2(monkeypatch):
    label = """Nutrition Information per 100 g
Sugars 25 g
Saturated Fat 6 g
Trans Fat 0 g
Sodium 400 mg
Ingredients: Oats, Brown Sugar
Contains: Milk"""
    result = OcrResult(label, "tesseract", "eng", 92.0)
    prepared = PreparedImage(Image.new("L", (600, 900)), 600, 900, True)
    execution = OcrExecution(result, prepared)
    pipeline = TeamAnalysisPipeline(
        health_predictor=M2HealthPredictor(UnavailableRiskService())
    )
    monkeypatch.setattr(team_pipeline_module, "execute_ocr", lambda *args, **kwargs: execution)
    monkeypatch.setattr(routes, "get_team_analysis_pipeline", lambda: pipeline)

    response = TestClient(create_app()).post(
        "/api/v1/analyze",
        files={"image": ("synthetic.png", b"synthetic-image", "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial_success"
    assert payload["analysis"]["basis"] == "per_100g"
    assert payload["health"]["health_score"] == 74.0
    assert payload["health"]["risk_level"] is None
    assert payload["integrations"]["health"] == {
        "status": "partial",
        "provider": "member_2_nutrition_and_ingredient_risk",
    }
    assert any("Risk model artifact is unavailable" in warning for warning in payload["warnings"])
