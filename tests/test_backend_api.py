import io
import sys
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import app


client = TestClient(app)


def create_test_image():
    """Create a minimal valid PNG image with some text for testing."""
    img = Image.new("RGB", (200, 100), color="white")
    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    img_bytes.seek(0)
    return img_bytes.getvalue()


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "NutriLens AI backend"


def test_analyze_endpoint_accepts_image_and_returns_pipeline_result():
    """Test the analyze endpoint with mocked OCR for now.
    
    Once EasyOCR is installed, remove the mock and use real OCR.
    """
    image_bytes = create_test_image()
    
    # Mock the OCR service to return sample text
    with patch('app.ocr.easyocr_service.EasyOCRService.extract_text') as mock_ocr:
        mock_ocr.return_value = "Nutrition Facts\nServing Size 1 cup\nCalories 100"
        
        response = client.post(
            "/api/analyze",
            files={"file": ("label.png", io.BytesIO(image_bytes), "image/png")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert "final_result" in body
    assert "ocr_text" in body
    assert body["ocr_text"] == "Nutrition Facts\nServing Size 1 cup\nCalories 100"
    assert "score_prediction" in body
    assert "health_risk_prediction" in body


def test_analyze_endpoint_rejects_non_image_upload():
    response = client.post(
        "/api/analyze",
        files={"file": ("notes.txt", io.BytesIO(b"hello world"), "text/plain")},
    )

    assert response.status_code == 400
    assert "image" in response.json()["detail"].lower()
