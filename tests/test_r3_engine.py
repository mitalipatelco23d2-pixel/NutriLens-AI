from __future__ import annotations

import io
import math
import time
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
import pytest
import qrcode
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import backend.postgres_store as postgres_store_module
from ai.food_understanding.confidence import aggregate_scan_confidence
from ai.food_understanding.config import R3Config
from ai.food_understanding.evaluation import intersection_over_union, ocr_error_rates
from ai.food_understanding.extraction import (
    extract_dates,
    extract_front_candidates,
    extract_ingredients,
    extract_nutrition,
    merge_ingredient_allergen_evidence,
    merge_nutrition_evidence,
)
from ai.food_understanding.image_input import (
    ImageInputError,
    sanitize_filename,
    validate_image_bytes,
)
from ai.food_understanding.pipeline import FoodUnderstandingPipeline, ImagePayload
from ai.food_understanding.quality import assess_image_quality
from ai.food_understanding.recognition import meal_items, recognize_categories, unknown_portion
from ai.food_understanding.schemas import (
    Box,
    Correction,
    CorrectionRequest,
    DetectionMethod,
    ImageQuality,
    IngredientExtraction,
    InputKind,
    ModelMetadata,
    NutritionExtraction,
    NutritionRow,
    OCRAttempt,
    OCRLine,
    OCRResult,
    PreprocessProfile,
    Region,
    ViewType,
)
from ai.food_understanding.store import EphemeralScanStore, ScanNotFoundError
from ai.ocr.orchestrator import OCROrchestrator
from ai.vision.barcode_qr import decode_barcodes, decode_qr, sanitize_qr_payload
from ai.vision.nutrition_yolo_engine import NutritionYOLOInference, _map_box_to_original
from ai.vision.preprocessing import (
    correct_perspective,
    deskew,
    preprocess,
    rotate_cardinal,
)
from ai.vision.regions import (
    INGREDIENT_STOP_TERMS,
    INGREDIENT_TERMS,
    nutrition_regions_from_custom_yolo,
    text_region,
)
from ai.vision.yolo_engine import YOLO11Engine, YOLODetection, YOLOInference
from backend.auth import create_session_token, user_store
from backend.main import app
from backend.postgres_store import PostgresStore


def _image_bytes(
    *,
    size: tuple[int, int] = (640, 480),
    color: str = "white",
    image_format: str = "PNG",
    text: str | None = None,
    exif_orientation: int | None = None,
) -> bytes:
    image = Image.new("RGB", size, color)
    if text:
        ImageDraw.Draw(image).text((30, 30), text, fill="black")
    output = io.BytesIO()
    kwargs: dict[str, object] = {}
    if exif_orientation is not None:
        exif = image.getexif()
        exif[274] = exif_orientation
        kwargs["exif"] = exif
    image.save(output, format=image_format, **kwargs)
    return output.getvalue()


def _config(**overrides: object) -> R3Config:
    return replace(R3Config(), **overrides)


def test_image_input_accepts_png_and_records_content_metadata() -> None:
    validated = validate_image_bytes(
        _image_bytes(),
        filename="label.png",
        mime_type="image/png",
        view_id="view-1",
        view_type=ViewType.NUTRITION,
        config=_config(),
    )
    assert validated.metadata.detected_format == "PNG"
    assert validated.metadata.width == 640
    assert validated.metadata.retained is False
    assert len(validated.metadata.sha256) == 64


@pytest.mark.parametrize(
    ("content", "filename", "mime", "code"),
    [
        (b"", "empty.png", "image/png", "EMPTY_FILE"),
        (b"not-an-image", "broken.png", "image/png", "CORRUPT_IMAGE"),
        (_image_bytes(), "label.gif", "image/gif", "UNSUPPORTED_EXTENSION"),
        (_image_bytes(), "label.jpg", "image/jpeg", "EXTENSION_MISMATCH"),
        (_image_bytes(), "label.png", "image/jpeg", "MIME_MISMATCH"),
    ],
)
def test_image_input_rejects_invalid_uploads(
    content: bytes, filename: str, mime: str, code: str
) -> None:
    with pytest.raises(ImageInputError) as error:
        validate_image_bytes(
            content,
            filename=filename,
            mime_type=mime,
            view_id="view-1",
            view_type=ViewType.GENERAL,
            config=_config(),
        )
    assert error.value.code == code


def test_image_input_enforces_size_and_dimension_limits() -> None:
    content = _image_bytes(size=(100, 100))
    with pytest.raises(ImageInputError, match="limit") as size_error:
        validate_image_bytes(
            content,
            filename="label.png",
            mime_type="image/png",
            view_id="view-1",
            view_type=ViewType.GENERAL,
            config=_config(max_upload_bytes=10),
        )
    assert size_error.value.code == "FILE_TOO_LARGE"
    with pytest.raises(ImageInputError) as dimension_error:
        validate_image_bytes(
            content,
            filename="label.png",
            mime_type="image/png",
            view_id="view-1",
            view_type=ViewType.GENERAL,
            config=_config(min_image_dimension=120),
        )
    assert dimension_error.value.code == "IMAGE_TOO_SMALL"

    with pytest.raises(ImageInputError) as pixel_error:
        validate_image_bytes(
            _image_bytes(size=(1000, 1000)),
            filename="compressed.png",
            mime_type="image/png",
            view_id="view-1",
            view_type=ViewType.GENERAL,
            config=_config(max_image_pixels=999_999),
        )
    assert pixel_error.value.code == "IMAGE_TOO_MANY_PIXELS"


def test_exif_orientation_is_applied_once() -> None:
    validated = validate_image_bytes(
        _image_bytes(size=(400, 200), image_format="JPEG", exif_orientation=6),
        filename="rotated.jpg",
        mime_type="image/jpeg",
        view_id="view-1",
        view_type=ViewType.GENERAL,
        config=_config(),
    )
    assert (validated.metadata.width, validated.metadata.height) == (200, 400)
    assert validated.metadata.exif_orientation_applied is True


def test_filename_sanitization_prevents_path_traversal() -> None:
    assert sanitize_filename("../../private/evil label.png") == "evil_label.png"
    assert sanitize_filename(r"..\..\evil?.png") == "evil_.png"


def test_quality_assessment_detects_flat_dark_image() -> None:
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    quality, elapsed = assess_image_quality(image, _config())
    assert quality.blur_status == "BLURRY"
    assert quality.brightness_status == "UNDEREXPOSED"
    assert quality.contrast_status == "LOW"
    assert quality.retry_recommended is True
    assert elapsed >= 0


def test_quality_assessment_accepts_high_detail_image() -> None:
    checker = np.indices((480, 640)).sum(axis=0) % 2 * 255
    image = cv2.cvtColor(checker.astype(np.uint8), cv2.COLOR_GRAY2BGR)
    quality, _ = assess_image_quality(image, _config())
    assert quality.blur_status == "ACCEPTABLE"
    assert quality.resolution_ok is True


@pytest.mark.parametrize("degrees", [0, 90, 180, 270])
def test_cardinal_rotation_is_non_destructive(degrees: int) -> None:
    image = np.arange(3 * 60 * 80, dtype=np.uint8).reshape((60, 80, 3))
    original = image.copy()
    result = rotate_cardinal(image, degrees)
    assert np.array_equal(image, original)
    assert result.shape[:2] == ((80, 60) if degrees in {90, 270} else (60, 80))


def test_cardinal_detection_boxes_map_back_to_original_coordinates() -> None:
    assert _map_box_to_original(
        (60, 10, 90, 40), rotation=90, original_width=200, original_height=100
    ) == pytest.approx((10, 10, 40, 40))
    assert _map_box_to_original(
        (160, 60, 190, 90), rotation=180, original_width=200, original_height=100
    ) == pytest.approx((10, 10, 40, 40))
    assert _map_box_to_original(
        (10, 160, 40, 190), rotation=270, original_width=200, original_height=100
    ) == pytest.approx((10, 10, 40, 40))


def test_ocr_preprocessing_enforces_maximum_side() -> None:
    result = preprocess(
        np.zeros((300, 400, 3), dtype=np.uint8),
        PreprocessProfile.OCR_LABEL,
        maximum_ocr_side=100,
    )
    assert max(result.image.shape[:2]) <= 100
    assert result.metadata.steps[0].name == "bounded_resize"
    assert result.metadata.steps[0].applied is True


def test_ocr_preprocessing_accepts_a_grayscale_region_crop() -> None:
    result = preprocess(
        np.zeros((120, 160), dtype=np.uint8),
        PreprocessProfile.NUTRITION_TABLE,
    )
    assert result.image.ndim == 2


def test_custom_nutrition_regions_preserve_provenance() -> None:
    regions = nutrition_regions_from_custom_yolo(
        [
            YOLODetection(
                label="nutrition_table",
                confidence=0.91,
                bounding_box=Box(x=1, y=2, width=30, height=40),
                class_id=0,
            )
        ],
        "view-1",
    )
    assert regions[0].method == DetectionMethod.CUSTOM_MODEL
    assert regions[0].region_type == "nutrition_table"


def test_deskew_and_profiles_are_deterministic() -> None:
    image = np.full((600, 800, 3), 255, dtype=np.uint8)
    cv2.putText(image, "NUTRITION", (100, 300), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 4)
    matrix = cv2.getRotationMatrix2D((400, 300), 5, 1)
    skewed = cv2.warpAffine(image, matrix, (800, 600), borderValue=(255, 255, 255))
    corrected, angle, _ = deskew(skewed)
    first = preprocess(skewed, profile=PreprocessProfile.OCR_LABEL)
    second = preprocess(skewed, profile=PreprocessProfile.OCR_LABEL)
    assert corrected.shape == skewed.shape
    assert math.isfinite(angle)
    assert np.array_equal(first.image, second.image)


def test_perspective_correction_uses_only_plausible_rectangle() -> None:
    image = np.zeros((600, 800, 3), dtype=np.uint8)
    points = np.array([[120, 90], [700, 130], [650, 520], [90, 480]], dtype=np.int32)
    cv2.polylines(image, [points], True, (255, 255, 255), 8)
    corrected, applied, confidence, reason = correct_perspective(image)
    assert applied is True
    assert confidence >= 0.25
    assert corrected.size > 0
    assert "rectangular" in reason


class _FakeEngine:
    def __init__(self, attempt: OCRAttempt) -> None:
        self.name = attempt.engine
        self.attempt = attempt

    def recognize(self, image: np.ndarray, languages: list[str]) -> OCRAttempt:
        return self.attempt


def _attempt(
    engine: Literal["PaddleOCR", "EasyOCR", "TrOCR"],
    status: Literal["SUCCESS", "NO_TEXT", "UNAVAILABLE", "FAILED", "DISABLED"],
    *,
    confidence: float | None = None,
    text: str = "",
) -> OCRAttempt:
    return OCRAttempt(
        engine=engine,
        status=status,
        lines=[OCRLine(text=text, confidence=confidence)] if text else [],
        confidence=confidence,
        elapsed_ms=1,
    )


def test_ocr_selects_primary_without_fallback() -> None:
    primary = _FakeEngine(_attempt("PaddleOCR", "SUCCESS", confidence=0.91, text="LABEL"))
    fallback = _FakeEngine(_attempt("EasyOCR", "SUCCESS", confidence=0.95, text="OTHER"))
    result = OCROrchestrator(_config(), primary=primary, fallback=fallback).run(
        np.zeros((10, 10), dtype=np.uint8),
        languages=["en"],
        profile=PreprocessProfile.OCR_LABEL,
    )
    assert result.selected_engine == "PaddleOCR"
    assert result.text == "LABEL"
    assert len(result.attempts) == 1


def test_ocr_falls_back_without_merging_contradictory_text() -> None:
    primary = _FakeEngine(_attempt("PaddleOCR", "SUCCESS", confidence=0.2, text="BAD"))
    fallback = _FakeEngine(_attempt("EasyOCR", "SUCCESS", confidence=0.88, text="GOOD"))
    result = OCROrchestrator(_config(), primary=primary, fallback=fallback).run(
        np.zeros((10, 10), dtype=np.uint8),
        languages=["en"],
        profile=PreprocessProfile.OCR_LABEL,
    )
    assert result.selected_engine == "EasyOCR"
    assert result.text == "GOOD"
    assert "BAD" not in result.text
    assert result.fallback_reason is not None


def test_ocr_reports_engine_failure_without_fabricated_confidence() -> None:
    unavailable = _FakeEngine(_attempt("PaddleOCR", "UNAVAILABLE"))
    failed = _FakeEngine(_attempt("EasyOCR", "FAILED"))
    result = OCROrchestrator(_config(), primary=unavailable, fallback=failed).run(
        np.zeros((10, 10), dtype=np.uint8),
        languages=["en"],
        profile=PreprocessProfile.OCR_LABEL,
    )
    assert result.selected_engine is None
    assert result.confidence is None
    assert result.confidence_level == "UNRELIABLE"


def test_ocr_fallback_uses_the_controlled_model_cache(tmp_path: Path) -> None:
    config = _config(model_cache=tmp_path / "models")
    orchestrator = OCROrchestrator(config)
    assert orchestrator.fallback.model_storage_directory == config.model_cache / "easyocr"  # type: ignore[attr-defined]


def test_qr_decode_preserves_payload_and_marks_it_untrusted() -> None:
    generated = qrcode.make("https://example.invalid/food?value=01").convert("RGB")
    image = cv2.cvtColor(np.asarray(generated, dtype=np.uint8), cv2.COLOR_RGB2BGR)
    results, elapsed = decode_qr(image, view_id="view-1")
    assert results[0].value.endswith("value=01")
    assert results[0].safety_status == "UNTRUSTED"
    assert elapsed >= 0


def test_qr_decode_handles_rotation_and_sanitizes_control_characters() -> None:
    generated = qrcode.make("NLX-ROTATED-01").convert("RGB")
    image = cv2.cvtColor(np.asarray(generated, dtype=np.uint8), cv2.COLOR_RGB2BGR)
    results, _ = decode_qr(cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE), view_id="view-1")
    assert results[0].value == "NLX-ROTATED-01"
    cleaned, status = sanitize_qr_payload("ok\x00\x07payload")
    assert cleaned == "okpayload"
    assert status == "UNTRUSTED"


def test_barcode_adapter_preserves_leading_zero_and_checksum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDetector:
        def detectAndDecode(self, image: np.ndarray) -> tuple[list[str], list[str], np.ndarray]:
            return (
                ["012345678905"],
                ["UPC_A"],
                np.array([[[1, 1], [20, 1], [20, 10], [1, 10]]], dtype=np.float32),
            )

    monkeypatch.setattr(cv2, "barcode_BarcodeDetector", FakeDetector)
    results, _ = decode_barcodes(np.zeros((30, 30, 3), dtype=np.uint8), view_id="view-1")
    assert results[0].value == "012345678905"
    assert results[0].checksum_valid is True


def test_barcode_adapter_returns_no_fabricated_result_on_decode_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class EmptyDetector:
        def detectAndDecode(self, image: np.ndarray) -> tuple[list[str], list[str], None]:
            return [], [], None

    monkeypatch.setattr(cv2, "barcode_BarcodeDetector", EmptyDetector)
    results, _ = decode_barcodes(np.zeros((30, 30, 3), dtype=np.uint8), view_id="view-1")
    assert results == []


def test_nutrition_and_date_extraction_preserve_raw_ambiguity() -> None:
    lines = [
        OCRLine(
            text="Nutrition Energy 100 kcal",
            confidence=0.9,
            bounding_box=Box(x=0, y=0, width=250, height=30),
        ),
        OCRLine(
            text="Protein 4 g",
            confidence=0.8,
            bounding_box=Box(x=0, y=35, width=200, height=30),
        ),
        OCRLine(
            text="EXP 01/02/2028",
            confidence=0.9,
            bounding_box=Box(x=0, y=70, width=200, height=30),
        ),
    ]
    region = Region(
        region_id="nutrition",
        region_type="nutrition_table",
        bounding_box=Box(x=0, y=0, width=300, height=70),
        method=DetectionMethod.OCR_LAYOUT,
        confidence=0.9,
        source_view_id="view-1",
    )
    nutrition = extract_nutrition(lines, region)
    dates = extract_dates(lines, "view-1")
    assert [row.label for row in nutrition.table_rows] == ["energy", "protein"]
    assert dates[0].raw_text == "01/02/2028"
    assert dates[0].parsed_date is None
    assert dates[0].ambiguous is True


def test_layout_parser_recovers_noisy_per_100_ml_rows_and_serving_size() -> None:
    lines = [
        OCRLine(
            text="Nutrition Information",
            confidence=0.94,
            bounding_box=Box(x=0, y=0, width=180, height=18),
        ),
        OCRLine(
            text="Per 100 ml", confidence=0.92, bounding_box=Box(x=180, y=0, width=90, height=18)
        ),
        OCRLine(
            text="Per serving", confidence=0.9, bounding_box=Box(x=280, y=0, width=95, height=18)
        ),
        OCRLine(
            text="sring Size-250 mml",
            confidence=0.84,
            bounding_box=Box(x=0, y=22, width=190, height=18),
        ),
        OCRLine(text="rotein", confidence=0.9, bounding_box=Box(x=0, y=48, width=80, height=18)),
        OCRLine(text="3.6 g", confidence=0.93, bounding_box=Box(x=180, y=48, width=60, height=18)),
        OCRLine(text="9 g", confidence=0.9, bounding_box=Box(x=280, y=48, width=45, height=18)),
        OCRLine(
            text="Aded Sugar", confidence=0.88, bounding_box=Box(x=0, y=74, width=110, height=18)
        ),
        OCRLine(text="0 g", confidence=0.94, bounding_box=Box(x=180, y=74, width=45, height=18)),
        OCRLine(text="sdium", confidence=0.86, bounding_box=Box(x=0, y=100, width=70, height=18)),
        OCRLine(text="45 mg", confidence=0.92, bounding_box=Box(x=180, y=100, width=55, height=18)),
        OCRLine(text="Clctum", confidence=0.82, bounding_box=Box(x=0, y=126, width=70, height=18)),
        OCRLine(
            text="200 mg", confidence=0.91, bounding_box=Box(x=180, y=126, width=65, height=18)
        ),
    ]
    region = Region(
        region_id="nutrition-noisy",
        region_type="nutrition_table",
        bounding_box=Box(x=0, y=0, width=400, height=160),
        method=DetectionMethod.OCR_LAYOUT,
        confidence=0.9,
        source_view_id="view-1",
    )

    nutrition = extract_nutrition(lines, region)

    assert nutrition.basis == "PER_100_ML"
    assert (nutrition.serving_size_value, nutrition.serving_size_unit) == ("250", "ml")
    assert {row.canonical_label for row in nutrition.table_rows} >= {
        "protein",
        "added sugar",
        "sodium",
        "calcium",
    }
    protein = next(row for row in nutrition.table_rows if row.label == "protein")
    assert protein.raw_label == "rotein"
    assert protein.values[:2] == ["3.6", "9"]
    assert protein.units[:2] == ["g", "g"]
    assert protein.source_rows
    assert len(protein.source_boxes) == 3


def test_layout_parser_recovers_split_headers_and_bounded_severe_ocr_noise() -> None:
    lines = [
        OCRLine(text="Size", confidence=0.98, bounding_box=Box(x=20, y=20, width=55, height=30)),
        OCRLine(text="250 ml", confidence=0.94, bounding_box=Box(x=95, y=8, width=90, height=32)),
        OCRLine(text="Per", confidence=0.9, bounding_box=Box(x=260, y=62, width=45, height=25)),
        OCRLine(text="100ml", confidence=0.93, bounding_box=Box(x=250, y=84, width=95, height=28)),
        OCRLine(
            text="50 kcal", confidence=0.9, bounding_box=Box(x=250, y=132, width=100, height=30)
        ),
        OCRLine(text="Irteln", confidence=0.72, bounding_box=Box(x=8, y=176, width=75, height=34)),
        OCRLine(text="3.6", confidence=0.92, bounding_box=Box(x=250, y=170, width=55, height=30)),
        OCRLine(
            text="nrohydrakcs",
            confidence=0.71,
            bounding_box=Box(x=8, y=216, width=130, height=36),
        ),
        OCRLine(text="5.5g", confidence=0.9, bounding_box=Box(x=250, y=212, width=68, height=30)),
        OCRLine(text="Sugar", confidence=0.95, bounding_box=Box(x=8, y=258, width=70, height=32)),
        OCRLine(text="5.5g", confidence=0.9, bounding_box=Box(x=250, y=254, width=68, height=30)),
        OCRLine(
            text="[uded Sugar",
            confidence=0.78,
            bounding_box=Box(x=8, y=300, width=120, height=34),
        ),
        OCRLine(text="0g", confidence=0.9, bounding_box=Box(x=250, y=296, width=48, height=30)),
        OCRLine(text="@abFat", confidence=0.7, bounding_box=Box(x=8, y=342, width=80, height=34)),
        OCRLine(text="15g", confidence=0.9, bounding_box=Box(x=250, y=338, width=62, height=30)),
        OCRLine(text="4g", confidence=0.9, bounding_box=Box(x=330, y=338, width=48, height=30)),
        OCRLine(
            text="(auunled Fat",
            confidence=0.68,
            bounding_box=Box(x=8, y=384, width=130, height=34),
        ),
        OCRLine(text="0.99", confidence=0.91, bounding_box=Box(x=250, y=380, width=62, height=30)),
        OCRLine(text="239", confidence=0.9, bounding_box=Box(x=330, y=380, width=55, height=30)),
    ]
    region = Region(
        region_id="nutrition-split-header",
        region_type="nutrition_table",
        bounding_box=Box(x=0, y=0, width=420, height=440),
        method=DetectionMethod.CUSTOM_MODEL,
        confidence=0.85,
        source_view_id="view-1",
    )

    nutrition = extract_nutrition(lines, region)

    assert nutrition.basis == "PER_100_ML"
    assert (nutrition.serving_size_value, nutrition.serving_size_unit) == ("250", "ml")
    assert {row.label for row in nutrition.table_rows} >= {
        "energy",
        "protein",
        "carbohydrate",
        "total sugar",
        "added sugar",
        "total fat",
        "saturated fat",
    }
    total_fat = next(row for row in nutrition.table_rows if row.label == "total fat")
    assert total_fat.values[:2] == ["15", "4"]
    assert total_fat.raw_values[:2] == ["15g", "4g"]
    saturated_fat = next(row for row in nutrition.table_rows if row.label == "saturated fat")
    assert saturated_fat.values[:2] == ["0.99", "239"]
    assert saturated_fat.raw_values[:2] == ["0.99", "239"]


def test_layout_parser_handles_warped_mobile_ocr_without_footer_column_poisoning() -> None:
    lines = [
        OCRLine(text="Ingredients:", bounding_box=Box(x=80, y=20, width=100, height=18)),
        OCRLine(
            text="Fat 1.5% Max., SNF 10.5% Min.",
            bounding_box=Box(x=40, y=38, width=240, height=18),
        ),
        OCRLine(
            text="Pasteurized Cow Milk",
            bounding_box=Box(x=55, y=44, width=190, height=18),
        ),
        OCRLine(
            text="Alergen: CONTAINS MILK",
            bounding_box=Box(x=45, y=68, width=210, height=18),
        ),
        OCRLine(text="Nutrition Facts", bounding_box=Box(x=30, y=100, width=160, height=24)),
        OCRLine(text="Serving Size 250 mt", bounding_box=Box(x=30, y=130, width=170, height=18)),
        OCRLine(
            text="Nutrient Information 100 D ml",
            bounding_box=Box(x=30, y=155, width=245, height=18),
        ),
        OCRLine(text="% RDA per serve", bounding_box=Box(x=430, y=155, width=130, height=18)),
        OCRLine(text="Clories", bounding_box=Box(x=25, y=190, width=70, height=18)),
        OCRLine(text="50 kcal125 kcal", bounding_box=Box(x=265, y=182, width=155, height=20)),
        OCRLine(text="6%", bounding_box=Box(x=455, y=185, width=35, height=18)),
        OCRLine(text="Potein", bounding_box=Box(x=25, y=220, width=65, height=18)),
        OCRLine(text="3.6g", bounding_box=Box(x=270, y=212, width=55, height=18)),
        OCRLine(text="9g", bounding_box=Box(x=350, y=212, width=35, height=18)),
        OCRLine(text="18%", bounding_box=Box(x=455, y=212, width=40, height=18)),
        OCRLine(text="odium", bounding_box=Box(x=25, y=250, width=60, height=18)),
        OCRLine(text="45 mg 112 mg", bounding_box=Box(x=265, y=237, width=145, height=18)),
        # The calcium label was lost; its overlapping value line must not be
        # appended to sodium merely because it is nearby.
        OCRLine(text="200 mg 500 mg", bounding_box=Box(x=260, y=265, width=150, height=18)),
        OCRLine(
            text="Recommended Dietary Allowance (RDA) is based on a 2000 kcal diet",
            bounding_box=Box(x=20, y=310, width=500, height=20),
        ),
    ]
    nutrition_region = Region(
        region_id="warped-mobile-table",
        region_type="nutrition_table",
        bounding_box=Box(x=0, y=95, width=580, height=250),
        method=DetectionMethod.OCR_LAYOUT,
        confidence=0.4,
        source_view_id="mobile-shadow",
    )
    ingredient_region = Region(
        region_id="warped-mobile-ingredients",
        region_type="ingredient_list",
        bounding_box=Box(x=0, y=0, width=300, height=95),
        method=DetectionMethod.OCR_LAYOUT,
        confidence=0.4,
        source_view_id="mobile-shadow",
    )

    nutrition = extract_nutrition(lines, nutrition_region)
    ingredients = extract_ingredients(lines, ingredient_region)
    rows = {row.label: row for row in nutrition.table_rows}

    assert nutrition.basis == "PER_100_ML"
    assert (nutrition.serving_size_value, nutrition.serving_size_unit) == ("250", "ml")
    assert rows["energy"].values[:2] == ["50", "125"]
    assert rows["protein"].values[:2] == ["3.6", "9"]
    assert rows["sodium"].values == ["45", "112"]
    assert ingredients.raw_text == "Pasteurized Cow Milk"
    assert ingredients.allergen_text == "Alergen: CONTAINS MILK"


def test_brand_legal_context_recovers_repeated_name_without_product_specific_rule() -> None:
    lines = [
        OCRLine(
            text="Low Fat Cow Milk",
            bounding_box=Box(x=20, y=20, width=260, height=70),
        ),
        OCRLine(
            text="Meadow Fresh - Live Better, Meadow Fresh logo are",
            bounding_box=Box(x=20, y=500, width=420, height=22),
        ),
        OCRLine(
            text="registered trademark of Example Dairy Ltd",
            bounding_box=Box(x=20, y=530, width=380, height=20),
        ),
    ]

    brands, products = extract_front_candidates(lines, "view-1")

    assert products[0].value == "Low Fat Cow Milk"
    assert brands[0].value == "Meadow Fresh"


def test_front_candidates_reject_section_slogan_noise_and_require_brand_evidence() -> None:
    lines = [
        OCRLine(
            text="Live bettex",
            confidence=0.84,
            bounding_box=Box(x=70, y=15, width=150, height=25),
        ),
        OCRLine(
            text="LOW Fat Cow Milk",
            confidence=0.82,
            bounding_box=Box(x=20, y=60, width=300, height=65),
        ),
        OCRLine(
            text="MatrientInformation serve serve",
            confidence=0.89,
            bounding_box=Box(x=10, y=500, width=350, height=35),
        ),
        OCRLine(
            text="Nutrition Facts",
            confidence=0.92,
            bounding_box=Box(x=10, y=550, width=240, height=40),
        ),
        OCRLine(
            text="Pasteurized Cow Milk",
            confidence=0.9,
            bounding_box=Box(x=10, y=200, width=250, height=28),
        ),
    ]

    brands, products = extract_front_candidates(lines, "view-1")

    assert brands == []
    assert products[0].value == "LOW Fat Cow Milk"
    assert {candidate.value for candidate in products} == {
        "LOW Fat Cow Milk",
        "Pasteurized Cow Milk",
    }


def test_front_candidates_accept_explicit_brand_label() -> None:
    lines = [
        OCRLine(
            text="Brand: Meadow Fresh",
            confidence=0.9,
            bounding_box=Box(x=10, y=10, width=180, height=28),
        ),
        OCRLine(
            text="Oat Cereal",
            confidence=0.88,
            bounding_box=Box(x=10, y=50, width=230, height=60),
        ),
    ]

    brands, products = extract_front_candidates(lines, "view-1")

    assert brands[0].value == "Meadow Fresh"
    assert products[0].value == "Oat Cereal"


def test_unit_aware_parser_recovers_letter_o_only_when_it_is_a_zero_value() -> None:
    lines = [
        OCRLine(text="Nutrition Facts", bounding_box=Box(x=0, y=0, width=160, height=20)),
        OCRLine(text="Amount Per Serving", bounding_box=Box(x=0, y=25, width=180, height=20)),
        OCRLine(text="Total Fat Og", bounding_box=Box(x=0, y=55, width=150, height=20)),
        OCRLine(text="Sodiumn Omg", bounding_box=Box(x=0, y=80, width=150, height=20)),
        OCRLine(
            text="Total Carb. less than 1g",
            bounding_box=Box(x=0, y=105, width=220, height=20),
        ),
    ]
    region = Region(
        region_id="zero-letter-o",
        region_type="nutrition_table",
        bounding_box=Box(x=0, y=0, width=240, height=140),
        method=DetectionMethod.OCR_LAYOUT,
        confidence=0.4,
        source_view_id="mobile-shadow",
    )

    rows = {row.label: row for row in extract_nutrition(lines, region).table_rows}

    assert rows["total fat"].values == ["0"]
    assert rows["total fat"].raw_values == ["Og"]
    assert rows["sodium"].values == ["0"]
    assert rows["sodium"].raw_values == ["Omg"]
    assert rows["carbohydrate"].values == ["1"]


def test_layout_parser_does_not_use_energy_value_as_anchor_or_shift_rows() -> None:
    lines = [
        OCRLine(
            text="Per 100 ml", confidence=0.95, bounding_box=Box(x=340, y=230, width=140, height=50)
        ),
        OCRLine(
            text="50 kcal", confidence=0.93, bounding_box=Box(x=340, y=303, width=140, height=48)
        ),
        OCRLine(
            text="125 kcal", confidence=0.95, bounding_box=Box(x=490, y=303, width=150, height=45)
        ),
        OCRLine(
            text="Clories", confidence=0.83, bounding_box=Box(x=14, y=331, width=90, height=54)
        ),
        OCRLine(text="3.6g", confidence=0.99, bounding_box=Box(x=358, y=353, width=110, height=61)),
        OCRLine(text="9g", confidence=0.99, bounding_box=Box(x=530, y=358, width=73, height=53)),
        OCRLine(text="moteln", confidence=0.64, bounding_box=Box(x=11, y=380, width=88, height=62)),
        OCRLine(text="5.5g", confidence=0.92, bounding_box=Box(x=363, y=413, width=103, height=54)),
        OCRLine(text="14g", confidence=0.94, bounding_box=Box(x=524, y=406, width=90, height=58)),
        OCRLine(
            text="abohydratcs", confidence=0.9, bounding_box=Box(x=15, y=421, width=185, height=73)
        ),
    ]
    region = Region(
        region_id="nutrition-perspective-skew",
        region_type="nutrition_table",
        bounding_box=Box(x=0, y=200, width=700, height=350),
        method=DetectionMethod.CUSTOM_MODEL,
        confidence=0.85,
        source_view_id="view-1",
    )

    nutrition = extract_nutrition(lines, region)

    rows = {row.label: row for row in nutrition.table_rows}
    assert rows["energy"].values[:2] == ["50", "125"]
    assert rows["protein"].values[:2] == ["3.6", "9"]
    assert rows["carbohydrate"].values[:2] == ["5.5", "14"]


def test_ingredient_boundaries_allergen_product_and_date_are_conservative() -> None:
    lines = [
        OCRLine(
            text="Country Delight",
            confidence=0.9,
            bounding_box=Box(x=10, y=0, width=170, height=30),
        ),
        OCRLine(
            text="Low Fat Cow Milk",
            confidence=0.92,
            bounding_box=Box(x=10, y=35, width=240, height=48),
        ),
        OCRLine(
            text="Ingredients: Pasteurized Cow Milk",
            confidence=0.91,
            bounding_box=Box(x=10, y=100, width=300, height=24),
        ),
        OCRLine(
            text="CONTAINS MILK",
            confidence=0.95,
            bounding_box=Box(x=10, y=130, width=160, height=22),
        ),
        OCRLine(
            text="Allergen",
            confidence=0.89,
            bounding_box=Box(x=10, y=142, width=90, height=16),
        ),
        OCRLine(
            text="Net Quantity: 450 ml",
            confidence=0.9,
            bounding_box=Box(x=10, y=160, width=190, height=22),
        ),
        OCRLine(
            text="Nutrition Information",
            confidence=0.9,
            bounding_box=Box(x=10, y=190, width=230, height=22),
        ),
        OCRLine(
            text="Saturated Fat 0.99 g",
            confidence=0.9,
            bounding_box=Box(x=10, y=220, width=220, height=22),
        ),
        OCRLine(
            text="For Batch No., USE BY DATE, MRP",
            confidence=0.8,
            bounding_box=Box(x=10, y=250, width=310, height=20),
        ),
    ]
    region = text_region(
        lines,
        terms=INGREDIENT_TERMS,
        stop_terms=INGREDIENT_STOP_TERMS,
        region_type="ingredient_list",
        view_id="view-1",
    )
    assert region is not None
    assert region.bounding_box.y + region.bounding_box.height < 160

    extraction = extract_ingredients(lines, region)
    assert extraction.raw_text == "Pasteurized Cow Milk"
    assert extraction.allergen_text == "CONTAINS MILK"
    assert extract_dates(lines, "view-1") == []
    brands, products = extract_front_candidates(lines, "view-1")
    values = [candidate.value for candidate in brands + products]
    assert "Low Fat Cow Milk" in values
    assert all(
        "Batch" not in value and "MRP" not in value and "Net Quantity" not in value
        for value in values
    )


def test_crop_ingredients_recover_explicit_allergen_from_full_label() -> None:
    crop = IngredientExtraction(
        raw_text="Pasteurized; Milk; Cow",
        allergen_text="Allergen :-; CONTAINS",
        allergen_confidence=0.83,
        confidence=0.84,
    )
    full_label = IngredientExtraction(
        raw_text="Cow Milk",
        allergen_text="MILK",
        allergen_confidence=0.96,
        confidence=0.7,
    )

    merged = merge_ingredient_allergen_evidence(crop, full_label)

    assert merged.raw_text == crop.raw_text
    assert merged.allergen_text == "MILK"
    assert merged.allergen_confidence == 0.96


def test_crop_nutrition_merges_more_complete_full_label_rows() -> None:
    crop = NutritionExtraction(
        basis="PER_100_ML",
        table_rows=[
            NutritionRow(
                label="total fat",
                canonical_label="total fat",
                values=["4"],
                raw_values=["4g"],
                units=["g"],
                confidence=0.92,
            ),
            NutritionRow(
                label="protein",
                canonical_label="protein",
                values=["3.6", "9"],
                raw_values=["3.6g", "9g"],
                units=["g", "g"],
                confidence=0.95,
            ),
            NutritionRow(
                label="cholesterol",
                canonical_label="cholesterol",
                values=["4"],
                raw_values=["4mg"],
                units=["mg"],
                confidence=0.88,
            ),
        ],
    )
    full_label = NutritionExtraction(
        basis="PER_100_ML",
        table_rows=[
            NutritionRow(
                label="total fat",
                canonical_label="total fat",
                values=["1.5", "4"],
                raw_values=["1.5g", "4g"],
                units=["g", "g"],
                confidence=0.88,
            ),
            NutritionRow(
                label="sodium",
                canonical_label="sodium",
                values=["45", "112"],
                raw_values=["45mg", "112mg"],
                units=["mg", "mg"],
                confidence=0.9,
            ),
            NutritionRow(
                label="cholesterol",
                canonical_label="cholesterol",
                values=["45", "4", "112", "10"],
                raw_values=["45mg", "4mg", "112mg", "10mg"],
                units=["mg", "mg", "mg", "mg"],
                confidence=0.96,
            ),
        ],
    )

    merged = merge_nutrition_evidence(crop, full_label)
    rows = {row.label: row for row in merged.table_rows}

    assert rows["total fat"].values == ["1.5", "4"]
    assert rows["protein"].values == ["3.6", "9"]
    assert rows["sodium"].values == ["45", "112"]
    assert rows["cholesterol"].values == ["4"]


def test_scan_job_completion_inserts_scan_before_foreign_key_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statements: list[str] = []

    class Cursor:
        def __init__(self, statement: str) -> None:
            self.statement = statement
            self.rowcount = 1

        def fetchone(self) -> tuple[int] | None:
            return (1,) if self.statement.startswith("SELECT 1 FROM scan_jobs") else None

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, query: str, _params: object = None) -> Cursor:
            statement = " ".join(query.split())
            statements.append(statement)
            return Cursor(statement)

    monkeypatch.setattr(
        postgres_store_module.psycopg, "connect", lambda *_args, **_kwargs: Connection()
    )

    completed = PostgresStore("postgresql://test").complete_scan_job(
        user_id="user-1",
        job_id="job-1",
        lease_token="lease-1",
        result={"scan_id": "scan-1"},
    )

    assert completed is True
    assert statements[0].startswith("SELECT 1 FROM scan_jobs")
    assert statements[1].startswith("INSERT INTO scans")
    assert statements[2].startswith("UPDATE scan_jobs")
    assert statements[3].startswith("DELETE FROM scan_job_images")


def test_structured_failure_caps_overall_confidence() -> None:
    quality = ImageQuality(
        blur_score=150,
        blur_status="ACCEPTABLE",
        brightness_score=120,
        brightness_status="ACCEPTABLE",
        contrast_score=60,
        contrast_status="ACCEPTABLE",
        resolution_ok=True,
        quality_status="HIGH",
        retry_recommended=False,
    )
    result = aggregate_scan_confidence(
        quality=quality,
        ocr_confidence=0.92,
        barcode_confidence=None,
        region_confidences=[0.9],
        category_confidence=0.8,
        nutrition_confidence=0.05,
        ingredient_confidence=0.1,
        allergen_confidence=0.1,
        product_confidence=0.7,
    )
    assert result.numeric_score is not None and result.numeric_score < 0.4
    assert result.level == "UNRELIABLE"


def test_product_category_meal_and_portion_foundations_are_conservative() -> None:
    lines = [
        OCRLine(
            text="Brand: Granary",
            confidence=0.9,
            bounding_box=Box(x=10, y=10, width=160, height=40),
        ),
        OCRLine(
            text="Oat Cereal",
            confidence=0.85,
            bounding_box=Box(x=10, y=60, width=220, height=60),
        ),
    ]
    brands, products = extract_front_candidates(lines, "view-1")
    detections = [
        YOLODetection(
            label="banana",
            confidence=0.8,
            bounding_box=Box(x=0, y=0, width=100, height=100),
            class_id=46,
        )
    ]
    categories = recognize_categories(lines, detections, "view-1")
    items = meal_items(detections, "view-1")
    portion = unknown_portion(items[0].item_id)
    assert products[0].value == "Oat Cereal"
    assert brands[0].value == "Granary"
    assert {candidate.value for candidate in categories} == {"banana", "cereal"}
    assert len(items) == 1
    assert portion.method == "UNKNOWN"
    assert portion.estimated_amount is None


def test_yolo_wrapper_does_not_download_when_disabled(tmp_path: Path) -> None:
    config = _config(model_cache=tmp_path, allow_model_downloads=False)
    result = YOLO11Engine(config).infer(np.zeros((320, 320, 3), dtype=np.uint8))
    assert result.error_code == "YOLO_UNAVAILABLE:MODEL_NOT_CACHED"
    assert result.metadata.training_status == "PRETRAINED"
    assert result.metadata.loaded is False


def test_custom_detector_provenance_does_not_leak_pretrained_unavailable_warning() -> None:
    custom_metadata = ModelMetadata(
        model_name="fixture custom nutrition detector",
        model_version="fixture-v1",
        source="test fixture",
        task="nutrition-table region detection",
        framework="fixture",
        device="cpu",
        license="test",
        training_status="CUSTOM_FINE_TUNED",
        loaded=True,
    )
    general_metadata = ModelMetadata(
        model_name="fixture pretrained detector",
        model_version="fixture-v1",
        source="test fixture",
        task="general object detection",
        framework="fixture",
        device="cpu",
        license="test",
        training_status="PRETRAINED",
        loaded=False,
    )

    class CustomDetector:
        def infer(self, image: np.ndarray) -> NutritionYOLOInference:
            return NutritionYOLOInference(
                detections=[
                    YOLODetection(
                        label="nutrition_table",
                        confidence=0.91,
                        bounding_box=Box(
                            x=0,
                            y=0,
                            width=image.shape[1],
                            height=image.shape[0],
                        ),
                        class_id=0,
                    )
                ],
                elapsed_ms=1,
                error_code=None,
                metadata=custom_metadata,
                rotation_degrees=0,
            )

    class MissingGeneralDetector:
        def infer(self, image: np.ndarray) -> YOLOInference:
            return YOLOInference(
                detections=[],
                elapsed_ms=1,
                error_code="YOLO_UNAVAILABLE:MODEL_NOT_CACHED",
                metadata=general_metadata,
            )

    class FixtureOCR:
        def run(
            self,
            image: np.ndarray,
            *,
            languages: list[str],
            profile: PreprocessProfile,
        ) -> OCRResult:
            lines = [
                OCRLine(
                    text="Nutrition Information Per 100 ml",
                    confidence=0.9,
                    bounding_box=Box(x=0, y=0, width=image.shape[1], height=20),
                ),
                OCRLine(
                    text="Protein 3.6 g",
                    confidence=0.9,
                    bounding_box=Box(x=0, y=25, width=image.shape[1], height=20),
                ),
            ]
            return OCRResult(
                selected_engine="FixtureOCR",
                lines=lines,
                text="\n".join(line.text for line in lines),
                confidence=0.9,
                confidence_level="HIGH",
                preprocessing_profile=profile,
            )

    pipeline = FoodUnderstandingPipeline(
        _config(),
        ocr=FixtureOCR(),  # type: ignore[arg-type]
        detector=MissingGeneralDetector(),  # type: ignore[arg-type]
        nutrition_detector=CustomDetector(),  # type: ignore[arg-type]
    )
    result = pipeline.scan(
        [
            ImagePayload(
                content=_image_bytes(text="FIXTURE"),
                filename="fixture.png",
                mime_type="image/png",
            )
        ],
        input_kind=InputKind.PRODUCT,
    )

    assert any(region.method == DetectionMethod.CUSTOM_MODEL for region in result.regions)
    assert all("MODEL_NOT_CACHED" not in warning for warning in result.warnings)
    assert [model.model_name for model in result.models] == ["fixture custom nutrition detector"]


def test_evaluation_helpers_compute_metrics_only_from_supplied_ground_truth() -> None:
    rates = ocr_error_rates("energy 100 kcal", "energy 10 kcal")
    assert rates.character_error_rate > 0
    assert rates.word_error_rate == pytest.approx(1 / 3)
    assert intersection_over_union((0, 0, 100, 100), (50, 50, 100, 100)) == pytest.approx(
        2500 / 17500
    )


def test_pipeline_and_ephemeral_store_support_correction_and_deletion() -> None:
    result = FoodUnderstandingPipeline(_config()).scan(
        [
            ImagePayload(
                content=_image_bytes(text="TEST LABEL"),
                filename="fixture.png",
                mime_type="image/png",
            )
        ],
        input_kind=InputKind.PRODUCT,
    )
    assert result.status == "COMPLETED_WITH_WARNINGS"
    from ai.food_understanding.insight_composer import compose_scan_insights

    assert result.insights == compose_scan_insights(result.nutrition, result.ingredients)
    assert result.images_retained is False
    assert result.models[0].training_status == "CUSTOM_FINE_TUNED"
    assert result.models[0].model_version == "r3-nutrition-yolo11n-v1"
    store = EphemeralScanStore()
    store.save(result)
    corrected = store.correct(
        result.scan_id,
        CorrectionRequest(
            corrections=[Correction(field="product_name", corrected_value="Corrected product")]
        ),
    )
    assert corrected.corrections[0].training_label is False
    assert store.delete(result.scan_id) is True
    with pytest.raises(ScanNotFoundError):
        store.get(result.scan_id)

    now = [0.0]
    bounded = EphemeralScanStore(max_records=2, ttl_seconds=5, clock=lambda: now[0])
    first = result.model_copy(update={"scan_id": "scan-first"})
    second = result.model_copy(update={"scan_id": "scan-second"})
    third = result.model_copy(update={"scan_id": "scan-third"})
    bounded.save(first, owner_id="owner")
    bounded.save(second, owner_id="owner")
    bounded.save(third, owner_id="owner")
    with pytest.raises(ScanNotFoundError):
        bounded.get("scan-first")
    assert {item.scan_id for item in bounded.list(owner_id="owner")} == {
        "scan-third",
        "scan-second",
    }
    now[0] = 6.0
    with pytest.raises(ScanNotFoundError):
        bounded.get("scan-second")


def test_pipeline_reruns_ocr_on_detected_nutrition_and_ingredient_crops() -> None:
    class RoutedOCR:
        def run(
            self,
            image: np.ndarray,
            *,
            languages: list[str],
            profile: PreprocessProfile,
        ) -> OCRResult:
            if profile == PreprocessProfile.GENERAL_PRODUCT:
                lines = [
                    OCRLine(
                        text="Nutrition Energy 100 kcal",
                        confidence=0.9,
                        bounding_box=Box(x=5, y=5, width=250, height=35),
                    ),
                    OCRLine(
                        text="Ingredients oats, nuts",
                        confidence=0.85,
                        bounding_box=Box(x=5, y=70, width=260, height=35),
                    ),
                ]
            elif profile == PreprocessProfile.NUTRITION_TABLE:
                lines = [
                    OCRLine(
                        text="Energy 100 kcal",
                        confidence=0.88,
                        bounding_box=Box(x=0, y=0, width=image.shape[1], height=20),
                    )
                ]
            else:
                lines = [
                    OCRLine(
                        text="Ingredients oats, nuts",
                        confidence=0.84,
                        bounding_box=Box(x=0, y=0, width=image.shape[1], height=20),
                    )
                ]
            return OCRResult(
                selected_engine="FixtureOCR",
                lines=lines,
                text="\n".join(line.text for line in lines),
                confidence=0.85,
                confidence_level="HIGH",
                preprocessing_profile=profile,
            )

    pipeline = FoodUnderstandingPipeline(_config(), ocr=RoutedOCR())  # type: ignore[arg-type]
    result = pipeline.scan(
        [
            ImagePayload(
                content=_image_bytes(text="SOFTWARE FIXTURE"),
                filename="fixture.png",
                mime_type="image/png",
            )
        ],
        input_kind=InputKind.PRODUCT,
    )
    assert "view-1:nutrition" in result.ocr_results
    assert "view-1:ingredients" in result.ocr_results
    assert result.nutrition.table_rows[0].label == "energy"
    assert result.ingredients.raw_text == "oats, nuts"


def test_pipeline_reuses_strong_full_page_ingredient_and_allergen_evidence() -> None:
    class RoutedOCR:
        def __init__(self) -> None:
            self.profiles: list[PreprocessProfile] = []

        def run(
            self,
            image: np.ndarray,
            *,
            languages: list[str],
            profile: PreprocessProfile,
        ) -> OCRResult:
            self.profiles.append(profile)
            if profile == PreprocessProfile.GENERAL_PRODUCT:
                lines = [
                    OCRLine(
                        text="Nutrition Energy 100 kcal",
                        confidence=0.94,
                        bounding_box=Box(x=5, y=5, width=250, height=35),
                    ),
                    OCRLine(
                        text="Ingredients: rolled oats, cocoa",
                        confidence=0.96,
                        bounding_box=Box(x=5, y=70, width=280, height=30),
                    ),
                    OCRLine(
                        text="Contains: milk",
                        confidence=0.97,
                        bounding_box=Box(x=5, y=105, width=180, height=30),
                    ),
                ]
            elif profile == PreprocessProfile.NUTRITION_TABLE:
                lines = [
                    OCRLine(
                        text="Energy 100 kcal",
                        confidence=0.92,
                        bounding_box=Box(x=0, y=0, width=image.shape[1], height=20),
                    )
                ]
            else:
                raise AssertionError("A high-confidence ingredient crop must not be OCRed again.")
            return OCRResult(
                selected_engine="FixtureOCR",
                lines=lines,
                text="\n".join(line.text for line in lines),
                confidence=0.94,
                confidence_level="HIGH",
                preprocessing_profile=profile,
            )

    routed_ocr = RoutedOCR()
    pipeline = FoodUnderstandingPipeline(_config(), ocr=routed_ocr)  # type: ignore[arg-type]
    result = pipeline.scan(
        [
            ImagePayload(
                content=_image_bytes(text="SOFTWARE FIXTURE"),
                filename="fixture.png",
                mime_type="image/png",
            )
        ],
        input_kind=InputKind.PRODUCT,
    )

    assert PreprocessProfile.INGREDIENT_LIST not in routed_ocr.profiles
    assert "view-1:ingredients" not in result.ocr_results
    assert result.ingredients.raw_text == "rolled oats, cocoa"
    assert result.ingredients.allergen_text == "Contains: milk"


def test_api_upload_get_correct_delete_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.r3_api as r3_api

    class FixtureOCR:
        def run(
            self,
            image: np.ndarray,
            *,
            languages: list[str],
            profile: PreprocessProfile,
        ) -> OCRResult:
            return OCRResult(
                selected_engine="FixtureOCR",
                lines=[],
                text="",
                confidence=None,
                confidence_level="UNRELIABLE",
                preprocessing_profile=profile,
            )

    fixture_pipeline = FoodUnderstandingPipeline(_config(), ocr=FixtureOCR())  # type: ignore[arg-type]
    monkeypatch.setattr(r3_api.pipeline, "scan", fixture_pipeline.scan)
    client = TestClient(app)
    user = user_store.upsert_google_user(
        {
            "sub": "r3-history-owner",
            "email": "r3-history@example.com",
            "email_verified": True,
        }
    )
    token, _ = create_session_token(user)
    headers = {"Authorization": f"Bearer {token}"}
    created = client.post(
        "/api/v1/scan/product",
        headers=headers,
        files={"files": ("label.png", _image_bytes(text="LABEL"), "image/png")},
        data={"view_types": "GENERAL", "languages": "en"},
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["images_retained"] is False
    scan_id = payload["scan_id"]
    history = client.get("/api/v1/scan/history", headers=headers)
    assert history.status_code == 200
    assert history.json()[0]["scan_id"] == scan_id
    assert "ocr_results" not in history.json()[0]
    assert client.get(f"/api/v1/scan/{scan_id}", headers=headers).status_code == 200
    corrected = client.patch(
        f"/api/v1/scan/{scan_id}/corrections",
        headers=headers,
        json={"corrections": [{"field": "ingredient_text", "corrected_value": "oats, nuts"}]},
    )
    assert corrected.status_code == 200
    assert corrected.json()["corrections"][0]["training_label"] is False
    assert client.delete(f"/api/v1/scan/{scan_id}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/scan/{scan_id}", headers=headers).status_code == 404


def test_public_scan_requires_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.auth as auth

    monkeypatch.setattr(auth, "settings", replace(auth.settings, app_environment="production"))
    response = TestClient(app).post(
        "/api/v1/scan/image",
        files={"file": ("label.png", _image_bytes(), "image/png")},
    )
    assert response.status_code == 401


@pytest.mark.parametrize(
    ("filename", "mime"),
    [("../../escape.png", "image/png"), ("spoof.jpg", "image/jpeg")],
)
def test_api_security_upload_paths(filename: str, mime: str) -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/scan/image",
        files={"file": (filename, _image_bytes(), mime)},
    )
    if filename.endswith(".png"):
        assert response.status_code == 201
        assert response.json()["input_metadata"][0]["safe_filename"] == "escape.png"
    else:
        assert response.status_code == 422
        assert response.json()["detail"]["error_code"] == "EXTENSION_MISMATCH"


def test_api_rejects_zero_byte_and_oversized_upload() -> None:
    client = TestClient(app)
    empty = client.post("/api/v1/scan/image", files={"file": ("empty.png", b"", "image/png")})
    assert empty.status_code == 422
    oversized = client.post(
        "/api/v1/scan/image",
        files={"file": ("large.png", b"x" * (10 * 1024 * 1024 + 1), "image/png")},
    )
    assert oversized.status_code == 422
    assert oversized.json()["detail"]["error_code"] == "FILE_TOO_LARGE"


def test_api_timeout_is_structured(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.r3_api as r3_api

    original = r3_api.pipeline.scan

    def slow_scan(*args: object, **kwargs: object) -> object:
        time.sleep(0.05)
        return original(*args, **kwargs)

    monkeypatch.setattr(r3_api.pipeline, "scan", slow_scan)
    monkeypatch.setattr(r3_api, "settings", replace(r3_api.settings, r3_scan_timeout_seconds=0.001))
    response = TestClient(app).post(
        "/api/v1/scan/image",
        files={"file": ("label.png", _image_bytes(), "image/png")},
    )
    assert response.status_code == 504
    assert response.json()["detail"]["error_code"] == "SCAN_TIMEOUT"


def test_scan_allowance_is_reserved_before_upload_read(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.r3_api as r3_api

    user = user_store.upsert_google_user(
        {
            "sub": "quota-preflight-user",
            "email": "quota@example.com",
            "email_verified": True,
            "name": "Quota User",
        }
    )
    token, _ = create_session_token(user)
    now = datetime.now(UTC)
    key = (user.id, date(now.year, now.month, 1))
    r3_api._scan_usage[key] = 10

    async def unexpected_read(_upload: object) -> bytes:
        raise AssertionError("upload was read after quota exhaustion")

    monkeypatch.setattr(r3_api, "_read_upload", unexpected_read)
    try:
        response = TestClient(app).post(
            "/api/v1/scan/image",
            files={"file": ("label.png", _image_bytes(), "image/png")},
            headers={"Authorization": f"Bearer {token}"},
        )
    finally:
        r3_api._scan_usage.pop(key, None)
    assert response.status_code == 429
    assert response.json()["detail"] == "Monthly scan allowance reached."


def test_async_scan_idempotency_quota_wakeup_and_cross_user_isolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.r3_api as r3_api

    class FakeJobStore:
        def __init__(self) -> None:
            self.by_key: dict[tuple[str, str], dict[str, object]] = {}
            self.by_id: dict[str, dict[str, object]] = {}
            self.quota_reservations = 0

        def create_scan_job(self, **values: object) -> tuple[dict[str, object], bool]:
            identity = (str(values["user_id"]), str(values["idempotency_key"]))
            existing = self.by_key.get(identity)
            if existing is not None:
                return existing, False
            now = datetime.now(UTC)
            record: dict[str, object] = {
                "job_id": "job-secure-fixture",
                "user_id": identity[0],
                "input_kind": str(values["input_kind"]),
                "status": "QUEUED",
                "created_at": now,
                "started_at": None,
                "completed_at": None,
                "result_scan_id": None,
                "error_code": None,
                "error_message": None,
            }
            self.quota_reservations += 1
            self.by_key[identity] = record
            self.by_id[str(record["job_id"])] = record
            return record, True

        def get_scan_job(self, user_id: str, job_id: str) -> dict[str, object] | None:
            record = self.by_id.get(job_id)
            return record if record is not None and record["user_id"] == user_id else None

        def get_scan(self, scan_id: str) -> None:
            return None

    store = FakeJobStore()
    wakeups: list[str] = []

    async def record_wakeup(job_id: str) -> None:
        wakeups.append(job_id)

    monkeypatch.setattr(r3_api, "postgres_store", store)
    monkeypatch.setattr(r3_api.dispatcher, "enqueue", record_wakeup)
    owner = user_store.upsert_google_user(
        {
            "sub": "async-owner-fixture",
            "email": "async-owner@example.com",
            "email_verified": True,
        }
    )
    intruder = user_store.upsert_google_user(
        {
            "sub": "async-intruder-fixture",
            "email": "async-intruder@example.com",
            "email_verified": True,
        }
    )
    owner_token, _ = create_session_token(owner)
    intruder_token, _ = create_session_token(intruder)
    client = TestClient(app)
    request = {
        "headers": {
            "Authorization": f"Bearer {owner_token}",
            "Idempotency-Key": "same-public-fixture",
        },
        "files": [("files", ("label.png", _image_bytes(), "image/png"))],
        "data": {"view_types": "GENERAL", "languages": "en"},
    }

    first = client.post("/api/v1/scan/jobs/product", **request)
    duplicate = client.post("/api/v1/scan/jobs/product", **request)

    assert first.status_code == duplicate.status_code == 202
    assert first.json()["job_id"] == duplicate.json()["job_id"]
    assert store.quota_reservations == 1
    assert wakeups == ["job-secure-fixture"]
    denied = client.get(
        f"/api/v1/scan/jobs/{first.json()['job_id']}",
        headers={"Authorization": f"Bearer {intruder_token}"},
    )
    assert denied.status_code == 404


def test_product_aggregate_pixel_budget_prevents_inference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.r3_api as r3_api

    monkeypatch.setattr(r3_api, "encoded_pixel_count", lambda _content: 30_000_000)

    def unexpected_scan(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("inference ran above aggregate pixel budget")

    monkeypatch.setattr(r3_api.pipeline, "scan", unexpected_scan)
    response = TestClient(app).post(
        "/api/v1/scan/product",
        files=[
            ("files", ("front.png", _image_bytes(), "image/png")),
            ("files", ("back.png", _image_bytes(), "image/png")),
        ],
        data={"view_types": "FRONT,BACK"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error_code"] == "TOO_MANY_PRODUCT_PIXELS"


def test_scan_history_requires_authentication() -> None:
    assert TestClient(app).get("/api/v1/scan/history").status_code == 401
