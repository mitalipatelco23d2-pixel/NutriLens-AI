from fastapi.testclient import TestClient
import pytest

from backend.app.api import routes
from backend.app.core.errors import ModelUnavailableError
from backend.app.main import create_app
from backend.app.schemas.common import IntegrationStatus, OcrMetadata
from backend.app.schemas.nutrition import HealthScoreResult, ImageAnalysisResponse
from backend.app.ocr.extractor import OcrResult
from backend.app.ocr.preprocessing import PreparedImage
from backend.app.ocr.service import OcrExecution
from PIL import Image


client = TestClient(create_app())

VALID_MANUAL = {
    "basis": "per_100g", "energy_100g": 840, "fat_100g": 10,
    "saturated_fat_100g": 3, "sugars_100g": 12, "fiber_100g": 2,
    "proteins_100g": 5, "salt_100g": 0.5, "sodium_100g": 0.2,
}


class ReadyScorer:
    def readiness(self): return True, "ready"
    def predict(self, features): return 4.5


class UnavailableScorer:
    def predict(self, features): raise ModelUnavailableError()


class NotReadyScorer:
    def readiness(self): return False, "missing"


class FakePipeline:
    def analyze(self, content, content_type, include_raw_text=False):
        return ImageAnalysisResponse(
            status="partial", basis="per_100g", extracted_nutrition={}, normalized_nutrition={},
            ingredients=[], missing_required_fields=["energy_100g"], warnings=["missing nutrients"],
            health_score=HealthScoreResult(performed=False, detail="not scored"),
            ocr=OcrMetadata(language="eng", preprocessing_applied=True, image_width=10, image_height=10),
            integrations={"rag": IntegrationStatus(status="not_configured", provider="member_5_adapter")},
        )


class FakeTeamPipeline:
    def analyze_text(self, contract):
        return {
            "request_id": "text-request", "status": "partial_success", "ocr": None,
            "analysis": {"ingredients": ["oats"], "nutrition": {}}, "health": None,
            "explanation": None, "integrations": {}, "warnings": ["health unavailable"],
        }

    def analyze_image(self, content, content_type, engine=None):
        return {
            "request_id": "image-request", "status": "partial_success",
            "ocr": {"engine": "tesseract", "confidence": 0.9, "rotation": 90},
            "analysis": {"ingredients": [], "nutrition": {}}, "health": None,
            "explanation": None, "integrations": {}, "warnings": [],
        }


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_versioned_health_endpoint():
    assert client.get("/api/v1/health").status_code == 200


def test_readiness_endpoint(monkeypatch):
    monkeypatch.setattr(routes, "get_health_score_service", lambda: ReadyScorer())
    monkeypatch.setattr(routes, "tesseract_readiness", lambda settings: (True, "ready"))
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert "easyocr" not in response.json()["dependencies"]
    assert response.json()["dependencies"]["tesseract"]["ready"] is True


def test_readiness_returns_503_when_dependency_is_missing(monkeypatch):
    monkeypatch.setattr(routes, "get_health_score_service", lambda: NotReadyScorer())
    monkeypatch.setattr(routes, "tesseract_readiness", lambda settings: (False, "missing"))
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_valid_manual_score(monkeypatch):
    monkeypatch.setattr(routes, "get_health_score_service", lambda: ReadyScorer())
    response = client.post("/api/v1/score/manual", json=VALID_MANUAL)
    assert response.status_code == 200
    assert response.json()["health_score"]["value"] == 4.5


def test_invalid_manual_score_has_consistent_error_schema():
    payload = dict(VALID_MANUAL); payload.pop("fiber_100g")
    response = client.post("/api/v1/score/manual", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_manual_score_dependency_unavailable(monkeypatch):
    monkeypatch.setattr(routes, "get_health_score_service", lambda: UnavailableScorer())
    response = client.post("/api/v1/score/manual", json=VALID_MANUAL)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "model_unavailable"
    assert "path" not in response.text.lower()


def test_manual_score_rejects_impossible_saturated_fat():
    payload = dict(VALID_MANUAL); payload["saturated_fat_100g"] = 11
    assert client.post("/api/v1/score/manual", json=payload).status_code == 422


def test_mocked_image_analysis(monkeypatch):
    monkeypatch.setattr(routes, "get_image_analysis_pipeline", lambda: FakePipeline())
    response = client.post("/api/v1/analyze/image", files={"image": ("label.png", b"content", "image/png")})
    assert response.status_code == 200
    assert response.json()["status"] == "partial"


def test_unsupported_upload_type():
    response = client.post("/api/v1/analyze/image", files={"image": ("label.gif", b"GIF89a", "image/gif")})
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"


def test_corrupt_image():
    response = client.post("/api/v1/analyze/image", files={"image": ("label.png", b"bad", "image/png")})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_image"


def test_missing_upload_is_validation_error():
    response = client.post("/api/v1/analyze/image")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_ocr_endpoint_runs_tesseract(monkeypatch):
    prepared = PreparedImage(Image.new("L", (10, 10)), 10, 10, True)
    monkeypatch.setattr(
        routes,
        "execute_ocr",
        lambda *args: OcrExecution(OcrResult("tesseract text", "tesseract", "eng", 80), prepared),
    )
    response = client.post(
        "/api/v1/ocr?engine=tesseract",
        files={"image": ("label.png", b"content", "image/png")},
    )
    assert response.status_code == 200
    assert response.json()["engine"] == "tesseract"
    assert response.json()["raw_text"] == "tesseract text"


def test_ocr_endpoint_rejects_invalid_engine():
    response = client.post(
        "/api/v1/ocr?engine=cloud",
        files={"image": ("label.png", b"content", "image/png")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_ocr_engine"


@pytest.mark.parametrize("engine", ["easyocr", "compare"])
def test_ocr_endpoint_rejects_removed_engines(engine):
    response = client.post(
        f"/api/v1/ocr?engine={engine}",
        files={"image": ("label.png", b"content", "image/png")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_ocr_engine"


def test_analyze_text_team_endpoint(monkeypatch):
    monkeypatch.setattr(routes, "get_team_analysis_pipeline", lambda: FakeTeamPipeline())
    response = client.post("/api/v1/analyze-text", json={"raw_text": "Ingredients: oats"})
    assert response.status_code == 200
    assert response.json()["request_id"] == "text-request"


def test_stable_analyze_endpoint(monkeypatch):
    monkeypatch.setattr(routes, "get_team_analysis_pipeline", lambda: FakeTeamPipeline())
    response = client.post(
        "/api/v1/analyze", files={"image": ("label.png", b"content", "image/png")}
    )
    assert response.status_code == 200
    assert response.json()["ocr"]["rotation"] == 90
