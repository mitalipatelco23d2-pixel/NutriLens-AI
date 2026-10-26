"""Unit tests for OCR '1001 ml' safety and strict nutrition basis handling.

Codex physical-device QA finding:
Internally inconsistent OCR evidence should be rejected rather than guessed.
- 'per 100 ml' -> PER_100_ML
- 'per 1001 ml' with header context -> PER_100_ML
- standalone '1001 ml' -> NOT PER_100_ML / UNKNOWN
- serving size '1001 ml' -> NOT PER_100_ML / rejected as implausible (> 1000 ml)
- package quantity '1500 ml' -> NOT PER_100_ML
"""

from ai.food_understanding.extraction import (
    _is_per_100_ml_basis,
    extract_nutrition,
)
from ai.food_understanding.schemas import Box, DetectionMethod, OCRLine, Region
from backend.client_evidence_gate import (
    ClientEvidenceDecision,
    classify_client_evidence,
)
from backend.client_inference_contract import (
    AndroidClientInferenceMode,
    ClientOcrBlock,
    ClientOcrEvidence,
    ClientOcrLine,
)


def _make_lines(texts: list[str]) -> list[OCRLine]:
    return [
        OCRLine(
            text=t,
            bounding_box=Box(x=10.0, y=10.0 + i * 25.0, width=400.0, height=20.0),
            confidence=0.95,
        )
        for i, t in enumerate(texts)
    ]


def _make_region() -> Region:
    return Region(
        region_id="reg-1",
        region_type="nutrition_table",
        bounding_box=Box(x=0.0, y=0.0, width=1000.0, height=1000.0),
        method=DetectionMethod.OCR_LAYOUT,
        confidence=1.0,
        source_view_id="view-1",
    )


def test_per_100_ml_canonical() -> None:
    """Canonical 'per 100 ml' resolves to PER_100_ML."""
    assert _is_per_100_ml_basis("per 100 ml") is True
    assert _is_per_100_ml_basis("Nutrition Information per 100 ml") is True
    assert _is_per_100_ml_basis("/ 100 ml") is True

    lines = _make_lines(
        [
            "Nutrition Information",
            "Per 100 ml",
            "Energy: 45 kcal",
            "Carbohydrate: 11 g",
            "Total Fat: 0 g",
            "Protein: 0.5 g",
        ]
    )
    result = extract_nutrition(lines, _make_region())
    assert result.basis == "PER_100_ML"


def test_per_1001_ml_with_header_context() -> None:
    """OCR confusion 'per 1001 ml' in nutrition header context safely resolves to PER_100_ML."""
    assert _is_per_100_ml_basis("per 1001 ml") is True
    assert _is_per_100_ml_basis("Nutritional Facts per 1001 ml") is True
    assert _is_per_100_ml_basis("Nutrition per 100 1 ml") is True

    lines = _make_lines(
        [
            "Nutritional Information",
            "per 1001 ml",
            "Energy: 50 kcal",
            "Total Sugars: 12 g",
            "Sodium: 30 mg",
            "Protein: 0 g",
        ]
    )
    result = extract_nutrition(lines, _make_region())
    assert result.basis == "PER_100_ML"


def test_standalone_1001_ml_not_converted() -> None:
    """Standalone '1001 ml' without context is NOT converted to PER_100_ML."""
    assert _is_per_100_ml_basis("1001 ml") is False
    assert _is_per_100_ml_basis("item size 1001 ml") is False

    lines = _make_lines(
        [
            "1001 ml",
            "Energy: 45 kcal",
            "Carbohydrate: 10 g",
            "Fat: 1 g",
            "Protein: 2 g",
        ]
    )
    result = extract_nutrition(lines, _make_region())
    assert result.basis != "PER_100_ML"
    assert result.basis == "UNKNOWN"


def test_package_quantity_1500_ml_not_converted() -> None:
    """Package quantities such as '1500 ml' or arbitrary volumes
    are never converted to PER_100_ML.
    """
    assert _is_per_100_ml_basis("1500 ml") is False
    assert _is_per_100_ml_basis("Net Volume: 1500 ml") is False
    assert _is_per_100_ml_basis("per 1500 ml") is False

    lines = _make_lines(
        [
            "Net Quantity: 1500 ml",
            "Energy: 120 kcal",
            "Total Carbohydrate: 25 g",
            "Total Fat: 2 g",
            "Protein: 4 g",
        ]
    )
    result = extract_nutrition(lines, _make_region())
    assert result.basis != "PER_100_ML"


def test_serving_size_1001_ml_rejected_as_implausible() -> None:
    """Serving size '1001 ml' is flagged as implausible (> 1000 ml) and triggers server fallback."""
    evidence = ClientOcrEvidence(
        client_inference_contract_version="1.0.0",
        platform="ANDROID",
        app_version="1.0.0+1",
        source="CLIENT_ANDROID_MLKIT",
        ocr_provider="ML_KIT_TEXT_RECOGNITION_V2",
        ocr_provider_version="16.0.1",
        cold_start=False,
        elapsed_ms=180,
        image_width=1080,
        image_height=1920,
        source_image_sha256="b" * 64,
        orientation_degrees=0,
        text="",
        blocks=[
            ClientOcrBlock(
                text=(
                    "Nutrition Facts\nServing size: 1001 ml\nEnergy: 50 kcal\n"
                    "Carbohydrate: 12 g\nFat: 0 g\nProtein: 1 g"
                ),
                bounds={"left": 50, "top": 100, "right": 800, "bottom": 800},
                recognized_languages=["en"],
                lines=[
                    ClientOcrLine(
                        text="Nutrition Facts",
                        bounds={"left": 50, "top": 100, "right": 500, "bottom": 150},
                        confidence=None,
                    ),
                    ClientOcrLine(
                        text="Serving size: 1001 ml",
                        bounds={"left": 50, "top": 160, "right": 500, "bottom": 210},
                        confidence=None,
                    ),
                    ClientOcrLine(
                        text="Energy: 50 kcal",
                        bounds={"left": 50, "top": 220, "right": 500, "bottom": 270},
                        confidence=None,
                    ),
                    ClientOcrLine(
                        text="Carbohydrate: 12 g",
                        bounds={"left": 50, "top": 280, "right": 500, "bottom": 330},
                        confidence=None,
                    ),
                    ClientOcrLine(
                        text="Fat: 0 g",
                        bounds={"left": 50, "top": 340, "right": 500, "bottom": 390},
                        confidence=None,
                    ),
                    ClientOcrLine(
                        text="Protein: 1 g",
                        bounds={"left": 50, "top": 400, "right": 500, "bottom": 450},
                        confidence=None,
                    ),
                ],
            )
        ],
    )

    gate_result = classify_client_evidence(
        evidence,
        verified_image_sha256=evidence.source_image_sha256,
        verified_image_width=evidence.image_width,
        verified_image_height=evidence.image_height,
        rollout_mode=AndroidClientInferenceMode.PREFERRED,
    )
    # Must NOT guess or rewrite to 100 ml; must flag IMPLAUSIBLE_NUTRIENT_VALUE
    assert "IMPLAUSIBLE_NUTRIENT_VALUE" in gate_result.reasons
    assert gate_result.decision == ClientEvidenceDecision.FALLBACK_REQUIRED
