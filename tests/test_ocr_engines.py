import io
from dataclasses import replace

import pytest
from PIL import Image

from backend.app.core.config import get_settings
from backend.app.core.errors import InvalidOcrEngineError
from backend.app.ocr import extractor, service
from backend.app.ocr.extractor import OcrResult
from backend.app.services import ocr_comparison


def png_bytes():
    output = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(output, "PNG")
    return output.getvalue()


def test_tesseract_engine_contract(monkeypatch):
    result = OcrResult("T text", "tesseract", "eng", 90.0)
    monkeypatch.setattr(service, "extract_text_from_image", lambda *args, **kwargs: result)
    output = service.execute_ocr(png_bytes(), "tesseract", "image/png")
    assert output.result.engine == "tesseract"
    assert output.normalized_contract()["mean_confidence"] == 0.9


@pytest.mark.parametrize("engine", ["easyocr", "compare", "cloud-ocr"])
def test_unsupported_ocr_engines_are_rejected(engine):
    with pytest.raises(InvalidOcrEngineError):
        service.resolve_ocr_engine(engine)


def test_default_engine_is_tesseract():
    assert service.resolve_ocr_engine(None) == "tesseract"


def test_benchmark_rejects_removed_engine():
    with pytest.raises(InvalidOcrEngineError):
        ocr_comparison.benchmark_environment("easyocr")


def test_optional_ground_truth_evaluation_is_reporting_only():
    evaluation = ocr_comparison.evaluate_nutrition_result(
        {"fat_100g": 0.0, "sugars_100g": 9.0, "fiber_100g": 1.0},
        {"fat_100g": 0.0, "sugars_100g": 10.0, "proteins_100g": 2.0},
    )
    assert evaluation["correct_fields"] == ["fat_100g"]
    assert "sugars_100g" in evaluation["incorrect_fields"]
    assert evaluation["missing_fields"] == ["proteins_100g"]
    assert evaluation["extra_fields"] == ["fiber_100g"]


def test_linux_tesseract_path_discovery(monkeypatch):
    settings = replace(get_settings(), tesseract_cmd=None)
    monkeypatch.setattr(extractor.shutil, "which", lambda command: "/usr/bin/tesseract")
    monkeypatch.setattr(extractor.pytesseract, "get_tesseract_version", lambda: "5.4.0")
    ready, _ = extractor.tesseract_readiness(settings)
    assert ready
    assert extractor.pytesseract.pytesseract.tesseract_cmd == "tesseract"


def test_windows_configured_tesseract_path_is_preserved(monkeypatch):
    command = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    settings = replace(get_settings(), tesseract_cmd=command)
    monkeypatch.setattr(extractor.shutil, "which", lambda value: value)
    monkeypatch.setattr(extractor.pytesseract, "get_tesseract_version", lambda: "5.4.0")
    ready, _ = extractor.tesseract_readiness(settings)
    assert ready
    assert extractor.pytesseract.pytesseract.tesseract_cmd == command
