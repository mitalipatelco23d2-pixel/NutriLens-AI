"""Rounding-aware contradictions must not become accepted client scan facts."""

import pytest

from ai.food_understanding.insight_composer import compose_scan_insights
from ai.food_understanding.nutrition_consistency import inconsistent_serving_rows
from ai.food_understanding.schemas import NutritionExtraction, NutritionRow


def nutrition(value="15", serving="4", unit="g", size_unit="ml"):
    return NutritionExtraction(
        basis="PER_100_ML",
        table_columns=["per 100 ml", "per serving"],
        serving_size_value="250",
        serving_size_unit=size_unit,
        table_rows=[NutritionRow(label="total fat", values=[value, serving], units=[unit, unit])],
    )


@pytest.mark.parametrize(
    "value,serving,conflicts",
    [
        ("15", "4", {0}),
        ("1.5", "4", set()),
        ("3.6", "9", set()),
        ("45", "112", set()),
        ("0", "0", set()),
        ("0.1", "8", {0}),
        ("<0.1", "0", set()),
        ("NaN", "4", set()),
        ("1,5", "4", set()),
    ],
)
def test_rounding_intervals(value, serving, conflicts):
    assert inconsistent_serving_rows(nutrition(value, serving)) == conflicts


def test_no_mass_volume_or_percentage_conversion():
    assert inconsistent_serving_rows(nutrition(size_unit="g")) == set()
    assert inconsistent_serving_rows(nutrition(unit="%")) == set()
    label = nutrition()
    label.table_rows[0].units = ["g", "mg"]
    assert inconsistent_serving_rows(label) == set()


def test_ambiguous_or_missing_columns_are_not_inferred():
    label = nutrition()
    for columns in [[], ["per 100 ml"], ["per 100 ml", "per serving", "per serving"]]:
        label.table_columns = columns
        assert inconsistent_serving_rows(label) == set()


def test_more_amount_values_than_declared_headers_is_ambiguous():
    from backend.client_evidence_gate import _has_ambiguous_value_columns

    label = nutrition("1.5", "4")
    label.basis = "PER_SERVING"
    label.table_columns = ["per serving"]
    assert _has_ambiguous_value_columns(label) is True


def test_conflicting_fact_is_omitted_without_changing_raw_evidence():
    label = nutrition()
    insights = compose_scan_insights(label, None)
    assert not any("15 g" in h.description for h in insights.structured_highlights)
    assert any("conflict" in warning for warning in insights.things_to_watch)
    assert label.table_rows[0].values == ["15", "4"]


def test_physical_milk_evidence_recovers_consistent_decimal_and_rejects_contradiction():
    from pathlib import Path

    from backend.client_evidence_gate import ClientEvidenceDecision, classify_client_evidence
    from backend.client_inference_contract import AndroidClientInferenceMode, ClientOcrEvidence

    raw = (Path(__file__).parent / "fixtures/mlkit-milk-recovery.json").read_text()
    evidence = ClientOcrEvidence.model_validate_json(raw)
    gate = classify_client_evidence(
        evidence,
        verified_image_sha256=evidence.source_image_sha256,
        verified_image_width=evidence.image_width,
        verified_image_height=evidence.image_height,
        rollout_mode=AndroidClientInferenceMode.PREFERRED,
    )
    # Governed safety policy: preserve OCR numeric evidence without inventing decimal points.
    # Contradictory raw OCR ("15 g" per 100 ml vs "4 g" per 250 ml serving)
    # triggers governed fallback.
    assert gate.decision is ClientEvidenceDecision.FALLBACK_REQUIRED
    assert "INCONSISTENT_SERVING_NUTRIENT_VALUES" in gate.reasons

    # When OCR evidence contains consistent numbers ("1.5 g"), it is accepted without rewriting.
    consistent = ClientOcrEvidence.model_validate_json(raw.replace('"15 g"', '"1.5 g"'))
    consistent_gate = classify_client_evidence(
        consistent,
        verified_image_sha256=consistent.source_image_sha256,
        verified_image_width=consistent.image_width,
        verified_image_height=consistent.image_height,
        rollout_mode=AndroidClientInferenceMode.PREFERRED,
    )
    assert consistent_gate.decision is ClientEvidenceDecision.ACCEPTED
    assert consistent_gate.nutrition is not None
    assert consistent_gate.nutrition.basis == "PER_100_ML"
    assert consistent_gate.nutrition.serving_size_value == "250"
    assert consistent_gate.nutrition.serving_size_unit == "ml"
    fat = next(
        row for row in consistent_gate.nutrition.table_rows if row.canonical_label == "total fat"
    )
    assert fat.values[:2] == ["1.5", "4"]

    contradicting = ClientOcrEvidence.model_validate_json(raw.replace('"15 g"', '"19 g"'))
    contradicting_gate = classify_client_evidence(
        contradicting,
        verified_image_sha256=contradicting.source_image_sha256,
        verified_image_width=contradicting.image_width,
        verified_image_height=contradicting.image_height,
        rollout_mode=AndroidClientInferenceMode.PREFERRED,
    )
    assert contradicting_gate.decision is ClientEvidenceDecision.FALLBACK_REQUIRED
    assert "INCONSISTENT_SERVING_NUTRIENT_VALUES" in contradicting_gate.reasons


def test_physical_milk_1001_ml_ocr_confusion_does_not_become_per_serving():
    from pathlib import Path

    from backend.client_evidence_gate import ClientEvidenceDecision, classify_client_evidence
    from backend.client_inference_contract import AndroidClientInferenceMode, ClientOcrEvidence

    raw = (Path(__file__).parent / "fixtures/mlkit-milk-recovery.json").read_text()
    evidence = ClientOcrEvidence.model_validate_json(
        raw.replace("100 D ml", "1001 ml").replace('"15 g"', '"19 g"')
    )
    gate = classify_client_evidence(
        evidence,
        verified_image_sha256=evidence.source_image_sha256,
        verified_image_width=evidence.image_width,
        verified_image_height=evidence.image_height,
        rollout_mode=AndroidClientInferenceMode.PREFERRED,
    )
    assert gate.nutrition_basis == "PER_100_ML"
    assert gate.decision is ClientEvidenceDecision.FALLBACK_REQUIRED
    assert "INCONSISTENT_SERVING_NUTRIENT_VALUES" in gate.reasons
