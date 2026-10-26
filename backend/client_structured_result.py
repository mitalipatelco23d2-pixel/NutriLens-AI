"""Server parsing of bounded, image-bound but unverified client OCR evidence.

No image/OCR model is invoked here. The result is authoritative only for the
owner's saved scan, not a claim that the client supplied truthful text.
"""

from __future__ import annotations

from uuid import uuid4

from ai.food_understanding.extraction import extract_dates, extract_front_candidates
from ai.food_understanding.insight_composer import compose_scan_insights
from ai.food_understanding.schemas import (
    ClientEvidenceProvenance,
    ConfidenceLevel,
    ConfidenceSummary,
    ImageMetadata,
    InputKind,
    ManualReviewField,
    OCRResult,
    PreprocessProfile,
    R3ScanResult,
    Timing,
)
from backend.client_evidence_gate import (
    ClientEvidenceDecision,
    ClientEvidenceGateResult,
    _ocr_lines,
)
from backend.client_inference_contract import ClientOcrEvidence, validate_client_evidence


def build_client_structured_result(
    evidence: ClientOcrEvidence,
    gate: ClientEvidenceGateResult,
    metadata: ImageMetadata,
    *,
    input_kind: InputKind,
    validation_ms: float,
    extraction_ms: float,
) -> R3ScanResult:
    if (
        gate.decision is not ClientEvidenceDecision.ACCEPTED
        or gate.nutrition is None
        or gate.ingredients is None
        or metadata.sha256 != evidence.source_image_sha256
        or (metadata.width, metadata.height) != (evidence.image_width, evidence.image_height)
        or evidence.orientation_degrees != 0
        or metadata.exif_orientation_applied
        or input_kind not in {InputKind.IMAGE, InputKind.PRODUCT, InputKind.OCR}
    ):
        raise ValueError("A supported label and accepted, source-bound evidence are required.")
    lines = _ocr_lines(evidence)
    view_id = "client-android-ocr"
    brands, products = extract_front_candidates(lines, view_id)
    validation = validate_client_evidence(evidence)
    insights = compose_scan_insights(
        nutrition=gate.nutrition,
        ingredients=gate.ingredients,
        brand_candidates=brands,
        product_name_candidates=products,
    )
    return R3ScanResult(
        scan_id=f"scan-{uuid4().hex}",
        trace_id=f"client-{uuid4().hex}",
        status="COMPLETED_WITH_WARNINGS",
        input_kind=input_kind,
        input_metadata=[metadata.model_copy(update={"view_id": view_id, "retained": False})],
        image_quality={},
        preprocessing={},
        regions=[region for region in (gate.nutrition.region, gate.ingredients.region) if region],
        ocr_results={
            view_id: OCRResult(
                selected_engine="CLIENT_ANDROID_MLKIT",
                attempts=[],
                lines=lines,
                text="\n".join(line.text for line in lines),
                confidence=None,
                confidence_level=ConfidenceLevel.UNRELIABLE,
                preprocessing_profile=PreprocessProfile.OCR_LABEL,
                fallback_reason="Client-reported OCR; no server OCR or detector executed.",
            )
        },
        nutrition=gate.nutrition,
        ingredients=gate.ingredients,
        brand_candidates=brands,
        product_name_candidates=products,
        date_candidates=extract_dates(lines, view_id),
        confidence_summary=ConfidenceSummary(
            level=ConfidenceLevel.LOW,
            numeric_score=None,
            sources={"nutrition_parsing": gate.nutrition_confidence or 0.0},
            explanation=[
                "Server validated source image bytes and parsed bounded client OCR evidence.",
                "Binding does not verify OCR text or attest that ML Kit actually executed.",
                "Overall accuracy is uncalibrated; verify nutrition and allergens on the package.",
            ],
        ),
        warnings=[
            "CLIENT_OCR_CONTENT_NOT_INDEPENDENTLY_VERIFIED",
            "SERVER_OCR_AND_DETECTOR_NOT_RUN_CLIENT_PREFERRED_PATH",
            "IMAGE_QUALITY_NOT_ASSESSED",
            "ALLERGEN_ABSENCE_IS_NOT_SAFETY_EVIDENCE",
        ],
        manual_review_fields=[
            ManualReviewField(
                field="nutrition", reason="Check client OCR values against the label."
            ),
            ManualReviewField(
                field="allergens", reason="Check the package before relying on allergens."
            ),
        ],
        models=[],
        timings=Timing(
            validation_ms=validation_ms,
            quality_ms=0,
            preprocessing_ms=0,
            detection_ms=0,
            barcode_qr_ms=0,
            ocr_ms=0,
            extraction_ms=extraction_ms,
            total_ms=validation_ms + extraction_ms,
        ),
        client_evidence_provenance=ClientEvidenceProvenance(
            evidence_sha256=validation.evidence_sha256,
            source_image_sha256=metadata.sha256,
            client_reported_elapsed_ms=evidence.elapsed_ms,
        ),
        insights=insights,
    )
