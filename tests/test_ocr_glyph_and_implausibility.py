"""Tests for Phase 0 nutrition defect fixes:
NLX-RQA-001 (glyph normalization) and NLX-RQA-002 (implausible facts reach gate).
"""

import pytest

from ai.food_understanding.extraction import extract_nutrition
from ai.food_understanding.schemas import Box, DetectionMethod, OCRLine, Region
from backend.client_evidence_gate import (
    ClientEvidenceDecision,
    _has_implausible_value,
    classify_client_evidence,
)
from backend.client_inference_contract import AndroidClientInferenceMode


def _line(text: str, x: float, y: float, w: float = 80.0, h: float = 30.0) -> OCRLine:
    return OCRLine(text=text, confidence=0.95, bounding_box=Box(x=x, y=y, width=w, height=h))


def _region() -> Region:
    return Region(
        region_id="reg-test",
        region_type="nutrition_table",
        bounding_box=Box(x=0, y=0, width=1000, height=1000),
        method=DetectionMethod.OCR_LAYOUT,
        confidence=0.95,
        source_view_id="view-1",
    )


def test_nlx_rqa_001_ocr_glyph_normalization_with_provenance_preserved():
    """Observed tokens like S7, J8, O are normalized to 57, 18, 0 with raw tokens intact."""
    lines = [
        _line("Nutrition Information", 50, 20, 300, 30),
        _line("Per 100g", 250, 60, 100, 25),
        _line("Per serving (30g)", 450, 60, 150, 25),
        _line("Protein", 50, 140, 100, 25),
        _line("S7 g", 250, 140, 80, 25),
        _line("J8 g", 450, 140, 80, 25),
    ]
    res = extract_nutrition(lines, _region())
    protein = next(r for r in res.table_rows if r.canonical_label == "protein")

    # Values normalized for downstream use
    assert protein.values == ["57", "18"]
    # Provenance preserved: raw observed tokens unchanged
    assert protein.raw_values == ["S7 g", "J8 g"]
    # Normalization traces recorded
    assert len(protein.normalization_traces) == 2
    assert protein.normalization_traces[0].observed_token == "S7"
    assert protein.normalization_traces[0].normalized_value == "57"
    assert protein.normalization_traces[0].normalization_type == "OCR_GLYPH_S_TO_5"

    assert protein.normalization_traces[1].observed_token == "J8"
    assert protein.normalization_traces[1].normalized_value == "18"
    assert protein.normalization_traces[1].normalization_type == "OCR_GLYPH_J_TO_1"


def test_nlx_rqa_002_implausible_facts_reach_the_gate_and_trigger_fallback():
    """An impossible nutrient value (e.g. 150g protein per 100g) must not be silently dropped.

    It must reach the gate and be flagged as IMPLAUSIBLE or INCONSISTENT.
    """
    lines = [
        _line("Nutrition Information", 50, 20, 300, 30),
        _line("Per 100g", 250, 60, 100, 25),
        _line("Per serving (30g)", 450, 60, 150, 25),
        _line("Protein", 50, 140, 100, 25),
        _line("150 g", 250, 140, 80, 25),
        _line("7.5 g", 450, 140, 80, 25),
    ]
    res = extract_nutrition(lines, _region())
    protein = next(r for r in res.table_rows if r.canonical_label == "protein")

    # The 150g protein was NOT silently dropped
    assert "150" in protein.values
    assert len(protein.parsed_values) == 2
    assert protein.parsed_values[0].value == "150"
    assert protein.parsed_values[0].basis == "PER_100_G"

    # _has_implausible_value catches it:
    assert _has_implausible_value(res) is True


def test_full_pipeline_raw_ocr_to_gate_classification_for_glyph_and_implausibility():
    """Test full pipeline: Raw OCR -> extract_nutrition -> client_evidence_gate -> decision."""
    from backend.client_inference_contract import (
        ClientOcrBlock,
        ClientOcrEvidence,
        ClientOcrLine,
    )

    # 1. Glyphs S7 g, J8 g, O g in contextual table
    lines_glyph = [
        _line("Nutrition Facts", 50, 20, 300, 30),
        _line("Per 100g", 250, 60, 100, 25),
        _line("Per serving (40g)", 450, 60, 150, 25),
        _line("Total Fat", 50, 100, 100, 25),
        _line("S7 g", 250, 100, 80, 25),
        _line("J8 g", 450, 100, 80, 25),
        _line("Added Sugar", 50, 140, 100, 25),
        _line("O g", 250, 140, 80, 25),
        _line("O g", 450, 140, 80, 25),
    ]
    extracted = extract_nutrition(lines_glyph, _region())
    fat_row = next(r for r in extracted.table_rows if r.canonical_label == "total fat")
    assert fat_row.values == ["57", "18"]
    assert fat_row.raw_values == ["S7 g", "J8 g"]
    sugar_row = next(r for r in extracted.table_rows if r.canonical_label == "added sugar")
    assert sugar_row.values == ["0", "0"]
    assert sugar_row.raw_values == ["O g", "O g"]

    # In ClientOcrEvidence gate:
    glyph_block_text = (
        "Nutrition Facts\nPer 100g\nPer serving (40g)\nTotal Fat S7 g J8 g\nAdded Sugar O g O g"
    )
    blocks = [
        ClientOcrBlock(
            text=glyph_block_text,
            bounds={"left": 50, "top": 20, "right": 550, "bottom": 200},
            recognized_languages=["en"],
            lines=[
                ClientOcrLine(
                    text=line_item.text,
                    bounds={
                        "left": int(line_item.bounding_box.x),
                        "top": int(line_item.bounding_box.y),
                        "right": int(line_item.bounding_box.x + line_item.bounding_box.width),
                        "bottom": int(line_item.bounding_box.y + line_item.bounding_box.height),
                    },
                )
                for line_item in lines_glyph
            ],
        )
    ]
    evidence = ClientOcrEvidence(
        client_inference_contract_version="1.0.0",
        platform="ANDROID",
        app_version="1.0.0+1",
        source="CLIENT_ANDROID_MLKIT",
        ocr_provider="ML_KIT_TEXT_RECOGNITION_V2",
        ocr_provider_version="16.0.1",
        cold_start=False,
        elapsed_ms=45,
        image_width=800,
        image_height=600,
        source_image_sha256="a" * 64,
        orientation_degrees=0,
        blocks=blocks,
    )
    eval_res = classify_client_evidence(
        evidence,
        verified_image_sha256="a" * 64,
        verified_image_width=800,
        verified_image_height=600,
        rollout_mode=AndroidClientInferenceMode.PREFERRED,
    )
    assert eval_res.decision in {
        ClientEvidenceDecision.ACCEPTED,
        ClientEvidenceDecision.FALLBACK_REQUIRED,
    }

    # 2. Implausible 150 g per 100 g / 7.5 g per 40 g
    lines_implausible = [
        _line("Nutrition Facts", 50, 20, 300, 30),
        _line("Per 100g", 250, 60, 100, 25),
        _line("Per serving (40g)", 450, 60, 150, 25),
        _line("Total Fat", 50, 100, 100, 25),
        _line("150 g", 250, 100, 80, 25),
        _line("7.5 g", 450, 100, 80, 25),
    ]
    extracted_imp = extract_nutrition(lines_implausible, _region())
    # Must be recognized as implausible and trigger fallback
    assert _has_implausible_value(extracted_imp) is True

    blocks_imp = [
        ClientOcrBlock(
            text="Nutrition Facts\nPer 100g\nPer serving (40g)\nTotal Fat 150 g 7.5 g",
            bounds={"left": 50, "top": 20, "right": 550, "bottom": 200},
            recognized_languages=["en"],
            lines=[
                ClientOcrLine(
                    text=line_item.text,
                    bounds={
                        "left": int(line_item.bounding_box.x),
                        "top": int(line_item.bounding_box.y),
                        "right": int(line_item.bounding_box.x + line_item.bounding_box.width),
                        "bottom": int(line_item.bounding_box.y + line_item.bounding_box.height),
                    },
                )
                for line_item in lines_implausible
            ],
        )
    ]
    evidence_imp = ClientOcrEvidence(
        client_inference_contract_version="1.0.0",
        platform="ANDROID",
        app_version="1.0.0+1",
        source="CLIENT_ANDROID_MLKIT",
        ocr_provider="ML_KIT_TEXT_RECOGNITION_V2",
        ocr_provider_version="16.0.1",
        cold_start=False,
        elapsed_ms=45,
        image_width=800,
        image_height=600,
        source_image_sha256="b" * 64,
        orientation_degrees=0,
        blocks=blocks_imp,
    )
    eval_imp = classify_client_evidence(
        evidence_imp,
        verified_image_sha256="b" * 64,
        verified_image_width=800,
        verified_image_height=600,
        rollout_mode=AndroidClientInferenceMode.PREFERRED,
    )
    # MUST fall back to server when physical impossibilities exist
    assert eval_imp.decision == ClientEvidenceDecision.FALLBACK_REQUIRED
    assert any("IMPLAUSIBLE" in r or "INCONSISTENT" in r for r in eval_imp.reasons)


@pytest.mark.parametrize(
    ("category", "nutrient", "glyph_token", "expected_num", "trace_type"),
    [
        ("beverage", "Energy", "S7 kcal", "57", "OCR_GLYPH_S_TO_5"),
        ("dairy", "Protein", "J8 g", "18", "OCR_GLYPH_J_TO_1"),
        ("cereal", "Added Sugars", "O g", "0", "OCR_GLYPH_O_TO_0"),
        ("snack", "Total Carbohydrate", "S2 g", "52", "OCR_GLYPH_S_TO_5"),
        ("biscuit", "Sodium", "J5 mg", "15", "OCR_GLYPH_J_TO_1"),
    ],
)
def test_randomized_category_glyph_normalization(
    category, nutrient, glyph_token, expected_num, trace_type
):
    """Test glyph normalization across arbitrary product categories."""
    lines = [
        _line(f"Nutrition Facts for {category}", 50, 20, 300, 30),
        _line("Per 100g", 250, 60, 100, 25),
        _line(nutrient, 50, 100, 150, 25),
        _line(glyph_token, 250, 100, 80, 25),
    ]
    res = extract_nutrition(lines, _region())
    row = res.table_rows[0]
    assert row.values[0] == expected_num
    assert glyph_token.split()[0] in row.raw_values[0]
    assert any(t.normalization_type == trace_type for t in row.normalization_traces)
