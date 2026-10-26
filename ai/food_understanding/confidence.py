"""Transparent field-source confidence aggregation."""

from __future__ import annotations

from ai.food_understanding.schemas import ConfidenceLevel, ConfidenceSummary, ImageQuality


def confidence_level(value: float | None) -> ConfidenceLevel:
    if value is None:
        return ConfidenceLevel.UNRELIABLE
    if value >= 0.85:
        return ConfidenceLevel.HIGH
    if value >= 0.65:
        return ConfidenceLevel.MEDIUM
    if value >= 0.4:
        return ConfidenceLevel.LOW
    return ConfidenceLevel.UNRELIABLE


def aggregate_scan_confidence(
    *,
    quality: ImageQuality,
    ocr_confidence: float | None,
    barcode_confidence: float | None,
    region_confidences: list[float],
    category_confidence: float | None,
    nutrition_confidence: float | None = None,
    ingredient_confidence: float | None = None,
    allergen_confidence: float | None = None,
    product_confidence: float | None = None,
) -> ConfidenceSummary:
    quality_scores = {
        ConfidenceLevel.HIGH: 0.9,
        ConfidenceLevel.MEDIUM: 0.7,
        ConfidenceLevel.LOW: 0.45,
        ConfidenceLevel.UNRELIABLE: 0.2,
    }
    sources: dict[str, float] = {"image_quality": quality_scores[quality.quality_status]}
    if ocr_confidence is not None:
        sources["ocr"] = ocr_confidence
    if barcode_confidence is not None:
        sources["barcode"] = barcode_confidence
    if region_confidences:
        sources["regions"] = sum(region_confidences) / len(region_confidences)
    if category_confidence is not None:
        sources["category"] = category_confidence
    structured = {
        key: value
        for key, value in {
            "nutrition_structure": nutrition_confidence,
            "ingredient_structure": ingredient_confidence,
            "allergen_evidence": allergen_confidence,
            "product_structure": product_confidence,
        }.items()
        if value is not None
    }
    sources.update(structured)
    technical_values = [value for key, value in sources.items() if key not in structured]
    score: float | None
    if structured:
        technical_mean = sum(technical_values) / len(technical_values) if technical_values else 0.0
        structure_mean = sum(structured.values()) / len(structured)
        score = 0.35 * technical_mean + 0.65 * structure_mean
        # A missing critical structure stage must keep the overall result cautious,
        # even when image quality and OCR are excellent.
        score = min(score, 0.25 + 0.75 * min(structured.values()))
    else:
        score = sum(technical_values) / len(technical_values) if technical_values else None
    return ConfidenceSummary(
        level=confidence_level(score),
        numeric_score=score,
        sources=sources,
        explanation=[
            "Overall confidence weights structured extraction more heavily than "
            "image and OCR signals.",
            "A weak critical structure stage conservatively caps the overall score.",
            "It is not accuracy, medical certainty, or a health assessment.",
        ],
    )
