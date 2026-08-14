import json

from PIL import Image

from backend.app.ocr.extractor import OcrResult
from backend.app.ocr.preprocessing import PreparedImage
from backend.app.ocr.service import OcrExecution
from backend.app.services import ocr_comparison
from scripts import compare_ocr


def fake_execution() -> OcrExecution:
    result = OcrResult(
        text="Nutrition information\nPer 100 g\nEnergy 100 kcal\nIngredients: oats",
        engine="tesseract", language="eng", mean_confidence=80.0, selected_rotation=90,
    )
    return OcrExecution(result, PreparedImage(Image.new("L", (100, 100)), 100, 100, True))


def test_tesseract_benchmark_schema_and_parser_debug(monkeypatch):
    monkeypatch.setattr(ocr_comparison, "execute_ocr", lambda *args, **kwargs: fake_execution())
    monkeypatch.setattr(
        ocr_comparison, "benchmark_environment",
        lambda engine, settings=None: {"operating_system": "Test", "python_version": "3.12", "device": "cpu", "tesseract_version": "5.4"},
    )
    result = ocr_comparison.benchmark_ocr_engine(b"image")
    assert set(result) >= {"environment", "runtime", "ocr", "analysis", "ocr_debug"}
    assert result["analysis"]["basis"] == "per_100g"
    assert result["ocr_debug"]["raw_text"].startswith("Nutrition information")
    assert result["ocr_debug"]["nutrition_keyword_recognized"] is True
    assert result["ocr_debug"]["numeric_nutrition_rows_recognized"] is True
    assert "candidate_parses" in result["ocr_debug"]


def test_tesseract_cli_json(monkeypatch, tmp_path, capsys):
    image = tmp_path / "label with spaces.png"
    image.write_bytes(b"image")
    monkeypatch.setattr(compare_ocr, "benchmark_ocr_engine", lambda *args, **kwargs: {"runtime": {}, "ocr": {}, "analysis": {}})
    assert compare_ocr.main([str(image), "--engine", "tesseract", "--json"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["engine"] == "tesseract"
    assert output["image"] == image.name


def test_non_table_calorie_word_is_classified_as_ocr_recognition_failure(monkeypatch):
    execution = fake_execution()
    execution = OcrExecution(
        OcrResult("Calorie Diet\nunrelated package text", "tesseract", "eng", 60.0),
        execution.prepared,
    )
    monkeypatch.setattr(ocr_comparison, "execute_ocr", lambda *args, **kwargs: execution)
    monkeypatch.setattr(ocr_comparison, "benchmark_environment", lambda *args, **kwargs: {})
    result = ocr_comparison.benchmark_ocr_engine(b"image")
    assert result["ocr_debug"]["diagnosis"] == "OCR recognition failure"
