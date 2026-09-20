import asyncio
import io

import pytest
from fastapi import UploadFile
from PIL import Image, ImageDraw

from backend.app.core.config import get_settings
from backend.app.core.errors import InvalidImageError, OcrProcessingError, UnsupportedMediaTypeError, UploadTooLargeError
from backend.app.ocr import extractor
from backend.app.ocr.extractor import OcrCandidate, OcrWord
from backend.app.ocr.panel_detection import detect_nutrition_panels, table_row_bounds
from backend.app.ocr.preprocessing import read_upload_limited, validate_and_preprocess_image


def image_bytes(image_format="PNG", size=(200, 100)):
    output = io.BytesIO()
    Image.new("RGB", size, "white").save(output, format=image_format)
    return output.getvalue()


def test_preprocessing_decodes_and_upscales_small_image():
    prepared = validate_and_preprocess_image(image_bytes(), "image/png")
    assert (prepared.original_width, prepared.original_height) == (200, 100)
    assert prepared.image.mode == "L"
    assert prepared.image.size == (600, 300)
    assert prepared.preprocessing_applied


def test_jpeg_without_exif_orientation_remains_valid_for_ocr():
    content = image_bytes("JPEG", (320, 180))
    with Image.open(io.BytesIO(content)) as source:
        assert source.getexif().get(274) is None
    prepared = validate_and_preprocess_image(content, "image/jpeg")
    assert prepared.original_width == 320
    assert prepared.original_height == 180


def test_corrupt_image_is_rejected():
    with pytest.raises(InvalidImageError):
        validate_and_preprocess_image(b"not an image", "image/png")


def test_unsupported_media_type_is_rejected():
    with pytest.raises(UnsupportedMediaTypeError):
        validate_and_preprocess_image(image_bytes(), "image/gif")


def test_empty_upload_is_rejected():
    upload = UploadFile(filename="empty.png", file=io.BytesIO(b""))
    with pytest.raises(InvalidImageError):
        asyncio.run(read_upload_limited(upload, 100))


def test_oversized_upload_is_rejected_without_unbounded_read():
    upload = UploadFile(filename="large.png", file=io.BytesIO(b"x" * 101))
    with pytest.raises(UploadTooLargeError):
        asyncio.run(read_upload_limited(upload, 100))


def test_tesseract_unavailable_is_reported(monkeypatch):
    monkeypatch.setattr(extractor.shutil, "which", lambda _: None)
    ready, detail = extractor.tesseract_readiness(get_settings())
    assert not ready
    assert "not found" in detail


def test_mocked_ocr_output_and_confidence(monkeypatch):
    monkeypatch.setattr(extractor, "tesseract_readiness", lambda settings=None: (True, "ok"))
    monkeypatch.setattr(
        extractor.pytesseract,
        "image_to_data",
        lambda *args, **kwargs: {
            "text": ["Energy", "840", "kJ"],
            "conf": ["95", "90", "88"],
            "block_num": [1, 1, 1], "par_num": [1, 1, 1], "line_num": [1, 1, 1],
        },
    )
    result = extractor.extract_text_from_image(Image.new("L", (20, 20)))
    assert result.text == "Energy 840 kJ"
    assert result.mean_confidence == 91.0


def test_empty_mocked_ocr_result_is_rejected(monkeypatch):
    monkeypatch.setattr(extractor, "tesseract_readiness", lambda settings=None: (True, "ok"))
    monkeypatch.setattr(
        extractor.pytesseract,
        "image_to_data",
        lambda *args, **kwargs: {"text": [], "conf": [], "block_num": [], "par_num": [], "line_num": []},
    )
    with pytest.raises(OcrProcessingError):
        extractor.extract_text_from_image(Image.new("L", (20, 20)))


def candidate(text, confidence, rotation, psm=11, region="full"):
    quality, tokens, keywords = extractor.score_ocr_text(text, confidence)
    return OcrCandidate(text, confidence, rotation, psm, quality, tokens, keywords, region=region)


def test_orientation_scoring_chooses_readable_90_degree_candidate():
    candidates = [
        candidate("a ee 1", 42, 0),
        candidate("Nutrition Information Energy Total Fat Sodium Protein", 76, 90),
        candidate("random package", 70, 180),
        candidate("x y z", 20, 270),
    ]
    assert extractor.select_best_orientation(candidates).rotation == 90


def test_extract_text_reports_selected_rotation_and_psm(monkeypatch):
    monkeypatch.setattr(extractor, "tesseract_readiness", lambda settings=None: (True, "ok"))

    def fake_pass(image, language, rotation, psm, region="full"):
        if rotation == 90:
            text = "Nutrition Information\nValue Per 100 g\nEnergy (Kcal) 399.3"
            confidence = 84 if psm == 6 else 78
        else:
            text = "unrelated package" if rotation == 0 else ""
            confidence = 35 if text else None
        return candidate(text, confidence, rotation, psm, region)

    monkeypatch.setattr(extractor, "_run_tesseract_pass", fake_pass)
    result = extractor.extract_text_from_image(Image.new("L", (600, 300)))
    assert result.selected_rotation == 90
    assert result.selected_psm == 6
    assert result.candidate_count == 5
    assert "Energy (Kcal) 399.3" in result.text


def test_grid_and_keyword_evidence_detects_nutrition_panel():
    image = Image.new("L", (500, 350), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 45, 370, 285), outline="black", width=4)
    for y in range(85, 285, 35):
        draw.line((70, y, 370, y), fill="black", width=3)
    draw.line((265, 45, 265, 285), fill="black", width=3)
    words = tuple(
        OcrWord(text, 90, 80, top, 75, 20, 1, 1, line)
        for line, (text, top) in enumerate(
            (("Nutrition", 55), ("Energy", 95), ("Fat", 130), ("Sodium", 165),
             ("Sugar", 200), ("Protein", 235)),
            start=1,
        )
    )
    panels = detect_nutrition_panels(image, words)
    assert panels
    assert panels[0].keyword_count >= 5


def test_rectified_grid_exposes_repeated_table_row_bounds():
    image = Image.new("L", (600, 500), "black")
    draw = ImageDraw.Draw(image)
    for y in range(20, 461, 55):
        draw.line((10, y, 590, y), fill="white", width=4)
    draw.line((10, 20, 10, 460), fill="white", width=4)
    draw.line((590, 20, 590, 460), fill="white", width=4)

    rows = table_row_bounds(image)

    assert len(rows) >= 7
    assert all(45 <= bottom - top <= 65 for top, bottom in rows)


def test_cell_refinement_requires_repeated_numeric_ocr(monkeypatch):
    words = (
        OcrWord("Value", 90, 20, 10, 50, 20, 1, 1, 1),
        OcrWord("Per", 90, 90, 10, 35, 20, 1, 1, 1),
        OcrWord("100g", 90, 200, 40, 55, 20, 1, 1, 2),
        OcrWord("Energy", 90, 20, 100, 70, 20, 1, 1, 3),
        OcrWord("(Kcal)", 90, 100, 100, 60, 20, 1, 1, 3),
        OcrWord("93", 40, 205, 100, 25, 20, 1, 1, 3),
    )
    base = OcrCandidate(
        "Value Per\n100g\nEnergy (Kcal) 93", 60, 0, 6, 100, 8, 2,
        words=words, region="nutrition_table", source_image=Image.new("L", (400, 200), "white")
    )
    readings = iter(("399.3", "399.3", "noise", ""))
    monkeypatch.setattr(extractor.pytesseract, "image_to_string", lambda *args, **kwargs: next(readings))
    refined = extractor._refine_numeric_cells(base, "eng")
    assert any(word.text == "399.3" and word.confidence == 100 for word in refined.words)
    assert not any(word.text == "93" for word in refined.words)
