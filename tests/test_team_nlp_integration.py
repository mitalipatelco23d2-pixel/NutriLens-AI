from __future__ import annotations

from fastapi.testclient import TestClient
from PIL import Image

from backend.app.api import routes
from backend.app.main import create_app
from backend.app.ocr.extractor import OcrResult
from backend.app.ocr.preprocessing import PreparedImage
from backend.app.ocr.service import OcrExecution
from backend.app.services import team_pipeline as team_pipeline_module
from backend.app.services.team_pipeline import TeamAnalysisPipeline


SYNTHETIC_LABEL = """Nutrition Information per 100 g
Energy 500 kcal
Total Fat 20 g
Saturated Fat 5 g
Carbohydrate 50 g
Total Sugars 10 g
Protein 8 g
Sodium 300 mg
Ingredients: Potatoes, Vegetable Oil, Flavour Enhancer INS 621, Salt
Contains: Milk"""


class RecordingHealthPredictor:
    provider = "member_2_recording_test"

    def __init__(self) -> None:
        self.nlp_result = None

    def predict(self, nlp_result):
        self.nlp_result = nlp_result
        return {"health_score": 72, "model_version": "integration-test"}


class RecordingExplainer:
    provider = "member_5_recording_test"

    def __init__(self) -> None:
        self.nlp_result = None
        self.health_result = None

    def explain(self, nlp_result, health_result):
        self.nlp_result = nlp_result
        self.health_result = health_result
        return {"summary": "Synthetic explanation", "sources": []}


class BrokenMember1:
    provider = "broken_member_1_test"

    def analyze(self, ocr_result):
        raise RuntimeError("synthetic M1 failure")


def execution(text: str, confidence: float = 40.0) -> OcrExecution:
    result = OcrResult(text, "tesseract", "eng", confidence)
    prepared = PreparedImage(Image.new("L", (600, 900)), 600, 900, True)
    return OcrExecution(result, prepared)


def test_stable_analyze_endpoint_runs_real_m1_then_passes_same_result_to_m2_and_m5(
    monkeypatch,
):
    health = RecordingHealthPredictor()
    explainer = RecordingExplainer()
    pipeline = TeamAnalysisPipeline(health_predictor=health, explainer=explainer)
    monkeypatch.setattr(
        team_pipeline_module,
        "execute_ocr",
        lambda *args, **kwargs: execution(SYNTHETIC_LABEL),
    )
    monkeypatch.setattr(routes, "get_team_analysis_pipeline", lambda: pipeline)

    response = TestClient(create_app()).post(
        "/api/v1/analyze",
        files={"image": ("synthetic.png", b"synthetic-image", "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["analysis"]["ingredients"] == [
        "Potatoes",
        "Vegetable Oil",
        "Flavour Enhancer INS 621",
        "Salt",
    ]
    assert payload["analysis"]["additives"] == ["Flavour enhancer", "INS 621"]
    assert payload["analysis"]["allergens"] == ["Milk"]
    assert payload["analysis"]["nutrition"]["energy_kcal_100g"] == 500
    assert payload["analysis"]["nutrition"]["sodium_100g"] == 0.3
    assert payload["analysis"]["basis"] == "per_100g"
    assert payload["analysis"]["metadata"]["ocr_engine"] == "tesseract"
    assert payload["analysis"]["metadata"]["ocr_rotation"] == 0
    assert payload["integrations"]["nlp"]["provider"] == "member_1_packaged_food_nlp"
    assert payload["health"]["health_score"] == 72
    assert payload["explanation"]["summary"] == "Synthetic explanation"
    assert any("OCR confidence was low" in warning for warning in payload["warnings"])
    assert sum("OCR confidence was low" in warning for warning in payload["warnings"]) == 1

    assert health.nlp_result is not None
    assert health.nlp_result["ingredients"] == payload["analysis"]["ingredients"]
    assert health.nlp_result["additives"] == payload["analysis"]["additives"]
    assert health.nlp_result["basis"] == "per_100g"
    assert explainer.nlp_result is health.nlp_result
    assert explainer.health_result == {
        "health_score": 72,
        "model_version": "integration-test",
    }


def test_milk_basis_and_missing_values_reach_downstream_adapters_unchanged(monkeypatch):
    label = """Nutrition Facts
Per 100 ml
Sodium 45 mg
Ingredient: asteurized Cow Milk
Allergen: CONTAINS MILK"""
    health = RecordingHealthPredictor()
    explainer = RecordingExplainer()
    monkeypatch.setattr(
        team_pipeline_module,
        "execute_ocr",
        lambda *args, **kwargs: execution(label, confidence=90.0),
    )

    response = TeamAnalysisPipeline(
        health_predictor=health,
        explainer=explainer,
    ).analyze_image(b"synthetic-image", "image/png")

    assert response.analysis["basis"] == "per_100ml"
    assert response.analysis["nutrition"] == {"sodium_100g": 0.045}
    assert response.analysis["nutrition_details"]["sodium_100g"]["basis"] == "per_100ml"
    assert response.analysis["ingredients"] == ["asteurized Cow Milk"]
    assert "sugars_100g" not in response.analysis["nutrition"]
    assert health.nlp_result["basis"] == "per_100ml"
    assert explainer.nlp_result is health.nlp_result


def test_member1_adapter_failure_falls_back_without_crashing_stable_api(monkeypatch):
    pipeline = TeamAnalysisPipeline(
        text_analyzer=BrokenMember1(),
        health_predictor=RecordingHealthPredictor(),
        explainer=RecordingExplainer(),
    )
    monkeypatch.setattr(
        team_pipeline_module,
        "execute_ocr",
        lambda *args, **kwargs: execution(SYNTHETIC_LABEL, confidence=90.0),
    )
    monkeypatch.setattr(routes, "get_team_analysis_pipeline", lambda: pipeline)

    response = TestClient(create_app()).post(
        "/api/v1/analyze",
        files={"image": ("synthetic.png", b"synthetic-image", "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["analysis"]["ingredients"][0] == "Potatoes"
    assert payload["integrations"]["nlp"] == {
        "status": "fallback",
        "provider": "member_1_packaged_food_nlp",
    }
    assert any(
        "configured Member 1 analyzer was unavailable" in warning
        for warning in payload["warnings"]
    )
