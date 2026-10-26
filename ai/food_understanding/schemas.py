"""Versioned response contracts for the R3 Food Understanding Engine."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class InputKind(StrEnum):
    IMAGE = "IMAGE"
    PRODUCT = "PRODUCT"
    MEAL = "MEAL"
    BARCODE = "BARCODE"
    OCR = "OCR"


class ViewType(StrEnum):
    GENERAL = "GENERAL"
    FRONT = "FRONT"
    BACK = "BACK"
    NUTRITION = "NUTRITION"
    INGREDIENTS = "INGREDIENTS"
    MEAL_ALTERNATE = "MEAL_ALTERNATE"


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNRELIABLE = "UNRELIABLE"


class DetectionMethod(StrEnum):
    CUSTOM_MODEL = "CUSTOM_MODEL"
    MODEL = "MODEL"
    HEURISTIC = "HEURISTIC"
    BARCODE_DETECTOR = "BARCODE_DETECTOR"
    OCR_LAYOUT = "OCR_LAYOUT"
    MANUAL = "MANUAL"


class PreprocessProfile(StrEnum):
    OCR_LABEL = "OCR_LABEL"
    NUTRITION_TABLE = "NUTRITION_TABLE"
    INGREDIENT_LIST = "INGREDIENT_LIST"
    BARCODE = "BARCODE"
    GENERAL_PRODUCT = "GENERAL_PRODUCT"
    MEAL = "MEAL"


class PortionMethod(StrEnum):
    KNOWN_SERVING = "KNOWN_SERVING"
    REFERENCE_OBJECT = "REFERENCE_OBJECT"
    PLATE_ESTIMATE = "PLATE_ESTIMATE"
    USER_ENTERED = "USER_ENTERED"
    UNKNOWN = "UNKNOWN"


class Box(ContractModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(ge=0)
    height: float = Field(ge=0)


class ImageMetadata(ContractModel):
    view_id: str
    view_type: ViewType
    original_filename: str
    safe_filename: str
    mime_type: str
    detected_format: Literal["JPEG", "PNG", "WEBP"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    byte_size: int = Field(gt=0)
    sha256: str
    exif_orientation_applied: bool = False
    retained: bool = False


class ImageQuality(ContractModel):
    blur_score: float = Field(ge=0)
    blur_status: Literal["BLURRY", "ACCEPTABLE"]
    brightness_score: float = Field(ge=0, le=255)
    brightness_status: Literal["UNDEREXPOSED", "ACCEPTABLE", "OVEREXPOSED"]
    contrast_score: float = Field(ge=0)
    contrast_status: Literal["LOW", "ACCEPTABLE"]
    resolution_ok: bool
    quality_status: ConfidenceLevel
    retry_recommended: bool
    warnings: list[str] = Field(default_factory=list)


class ProcessingStep(ContractModel):
    name: str
    applied: bool
    reason: str
    parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)


class PreprocessingResult(ContractModel):
    profile: PreprocessProfile
    width: int
    height: int
    steps: list[ProcessingStep]
    elapsed_ms: float = Field(ge=0)


class OCRWord(ContractModel):
    text: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    bounding_box: Box | None = None


class OCRLine(ContractModel):
    text: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    bounding_box: Box | None = None
    words: list[OCRWord] = Field(default_factory=list)


class OCRAttempt(ContractModel):
    engine: Literal["PaddleOCR", "EasyOCR", "TrOCR"]
    status: Literal["SUCCESS", "NO_TEXT", "UNAVAILABLE", "FAILED", "DISABLED"]
    lines: list[OCRLine] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    elapsed_ms: float = Field(ge=0)
    language_configuration: list[str] = Field(default_factory=list)
    error_code: str | None = None


class OCRResult(ContractModel):
    selected_engine: str | None = None
    attempts: list[OCRAttempt] = Field(default_factory=list)
    lines: list[OCRLine] = Field(default_factory=list)
    text: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)
    confidence_level: ConfidenceLevel = ConfidenceLevel.UNRELIABLE
    fallback_reason: str | None = None
    preprocessing_profile: PreprocessProfile


class Region(ContractModel):
    region_id: str
    region_type: Literal[
        "product",
        "nutrition_table",
        "ingredient_list",
        "barcode",
        "qr_code",
        "brand_logo",
        "date",
        "food_item",
        "plate_or_container",
    ]
    bounding_box: Box
    method: DetectionMethod
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_view_id: str


class BarcodeResult(ContractModel):
    symbology: str
    value: str
    checksum_valid: bool | None = None
    bounding_box: Box | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_view_id: str


class QRResult(ContractModel):
    value: str
    bounding_box: Box | None = None
    decoded: bool
    safety_status: Literal["UNTRUSTED", "EMPTY", "REJECTED"]
    source_view_id: str


class TextCandidate(ContractModel):
    value: str
    confidence: float = Field(ge=0, le=1)
    method: DetectionMethod
    source_view_id: str


class DateCandidate(ContractModel):
    date_type: Literal["MFG", "PACKED_ON", "BEST_BEFORE", "USE_BY", "EXPIRY", "UNKNOWN"]
    raw_text: str
    parsed_date: str | None = None
    confidence: float = Field(ge=0, le=1)
    ambiguous: bool
    source_view_id: str


class NutritionValue(ContractModel):
    value: str
    unit: str
    basis: Literal[
        "PER_100_G",
        "PER_100_ML",
        "PER_SERVING",
        "PERCENT_RDA",
        "PERCENT_DV",
        "UNKNOWN",
    ] = "UNKNOWN"
    resolved_serving: str | None = None
    source_basis_text: str | None = None
    is_reference_intake: bool = False


class OCRNormalizationTrace(ContractModel):
    observed_token: str
    normalized_value: str
    normalization_type: str
    confidence: float = Field(default=0.85, ge=0, le=1)


class NutritionRow(ContractModel):
    label: str
    raw_label: str = ""
    canonical_label: str | None = None
    match_confidence: float | None = Field(default=None, ge=0, le=1)
    parsed_values: list[NutritionValue] = Field(default_factory=list)
    # Legacy fields to preserve API compatibility during transition if needed
    values: list[str] = Field(default_factory=list)
    raw_values: list[str] = Field(default_factory=list)
    units: list[str] = Field(default_factory=list)
    normalization_traces: list[OCRNormalizationTrace] = Field(default_factory=list)
    source_rows: list[int] = Field(default_factory=list)
    source_boxes: list[Box] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class NutritionExtraction(ContractModel):
    region: Region | None = None
    raw_table_text: str = ""
    table_rows: list[NutritionRow] = Field(default_factory=list)
    table_columns: list[str] = Field(default_factory=list)
    basis: Literal["PER_100_G", "PER_100_ML", "PER_SERVING", "UNKNOWN"] = "UNKNOWN"
    serving_size_value: str | None = None
    serving_size_unit: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    method: DetectionMethod = DetectionMethod.OCR_LAYOUT


class IngredientExtraction(ContractModel):
    region: Region | None = None
    raw_text: str = ""
    allergen_text: str = ""
    allergen_confidence: float | None = Field(default=None, ge=0, le=1)
    source_rows: list[int] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    method: DetectionMethod = DetectionMethod.OCR_LAYOUT


class CategoryCandidate(ContractModel):
    value: str
    confidence: float = Field(ge=0, le=1)
    method: Literal["PRETRAINED_COCO", "OCR_CONTEXT", "BARCODE_LOCAL", "MANUAL"]
    source_view_id: str


class MealItem(ContractModel):
    item_id: str
    bounding_box: Box | None = None
    food_candidates: list[CategoryCandidate] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    method: DetectionMethod


class PortionEstimate(ContractModel):
    item_id: str | None = None
    method: PortionMethod
    estimated_amount: float | None = Field(default=None, gt=0)
    unit: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    assumptions: list[str] = Field(default_factory=list)


class ConfidenceSummary(ContractModel):
    level: ConfidenceLevel
    numeric_score: float | None = Field(default=None, ge=0, le=1)
    sources: dict[str, float] = Field(default_factory=dict)
    explanation: list[str] = Field(default_factory=list)
    medical_certainty: Literal[False] = False


class Timing(ContractModel):
    validation_ms: float = Field(ge=0)
    quality_ms: float = Field(ge=0)
    preprocessing_ms: float = Field(ge=0)
    detection_ms: float = Field(ge=0)
    barcode_qr_ms: float = Field(ge=0)
    ocr_ms: float = Field(ge=0)
    extraction_ms: float = Field(ge=0)
    total_ms: float = Field(ge=0)


class ManualReviewField(ContractModel):
    field: str
    reason: str
    current_value: Any = None


class Correction(ContractModel):
    field: Literal[
        "product_name",
        "brand",
        "barcode",
        "nutrition_text",
        "ingredient_text",
        "detected_region",
        "food_category",
        "meal_item",
        "serving_amount",
    ]
    corrected_value: str | float | dict[str, Any] | list[Any]


class StoredCorrection(Correction):
    original_prediction: Any = None
    corrected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    confidence_before: float | None = Field(default=None, ge=0, le=1)
    training_label: Literal[False] = False


class CorrectionRequest(ContractModel):
    corrections: list[Correction] = Field(min_length=1, max_length=25)


class ModelMetadata(ContractModel):
    model_name: str
    model_version: str
    source: str
    task: str
    framework: str
    local_file: str | None = None
    checksum: str | None = None
    device: str
    license: str
    training_status: Literal["PRETRAINED", "CUSTOM_TRAINED", "CUSTOM_FINE_TUNED", "NOT_APPLICABLE"]
    loaded: bool


class ClientEvidenceProvenance(ContractModel):
    """Bytes are bound by the server; OCR origin and content remain client-reported."""

    source: Literal["CLIENT_ANDROID_MLKIT"] = "CLIENT_ANDROID_MLKIT"
    ocr_provider: Literal["ML_KIT_TEXT_RECOGNITION_V2"] = "ML_KIT_TEXT_RECOGNITION_V2"
    ocr_provider_version: Literal["16.0.1"] = "16.0.1"
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_image_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    image_binding_verified: Literal[True] = True
    dimensions_binding_verified: Literal[True] = True
    ocr_content_independently_verified: Literal[False] = False
    provider_execution_attested: Literal[False] = False
    structured_by: Literal["SERVER_GOVERNED_PARSER"] = "SERVER_GOVERNED_PARSER"
    client_reported_elapsed_ms: int = Field(ge=0, le=300_000)


class ScanInsightHighlight(ContractModel):
    title: str
    description: str
    category: Literal["positive", "watch", "neutral", "allergen", "serving"]
    icon: str | None = None


class ScanInsights(ContractModel):
    highlights: list[str] = Field(default_factory=list)
    positive_signals: list[str] = Field(default_factory=list)
    things_to_watch: list[str] = Field(default_factory=list)
    allergen_summary: str | None = None
    serving_context: str | None = None
    structured_highlights: list[ScanInsightHighlight] = Field(default_factory=list)
    ask_nutri_suggestions: list[str] = Field(default_factory=list)


class R3ScanResult(ContractModel):
    contract_version: Literal["3.0.0"] = "3.0.0"
    pipeline_version: Literal["0.3.0"] = "0.3.0"
    scan_id: str
    trace_id: str
    status: Literal["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"]
    input_kind: InputKind
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    input_metadata: list[ImageMetadata]
    image_quality: dict[str, ImageQuality]
    preprocessing: dict[str, PreprocessingResult]
    regions: list[Region] = Field(default_factory=list)
    barcode_results: list[BarcodeResult] = Field(default_factory=list)
    qr_results: list[QRResult] = Field(default_factory=list)
    ocr_results: dict[str, OCRResult] = Field(default_factory=dict)
    nutrition: NutritionExtraction = Field(default_factory=NutritionExtraction)
    ingredients: IngredientExtraction = Field(default_factory=IngredientExtraction)
    brand_candidates: list[TextCandidate] = Field(default_factory=list)
    product_name_candidates: list[TextCandidate] = Field(default_factory=list)
    date_candidates: list[DateCandidate] = Field(default_factory=list)
    category_candidates: list[CategoryCandidate] = Field(default_factory=list)
    meal_items: list[MealItem] = Field(default_factory=list)
    portion_estimates: list[PortionEstimate] = Field(default_factory=list)
    local_product_lookup_status: Literal["FOUND", "NOT_FOUND", "DISABLED"] = "NOT_FOUND"
    confidence_summary: ConfidenceSummary
    warnings: list[str] = Field(default_factory=list)
    manual_review_fields: list[ManualReviewField] = Field(default_factory=list)
    corrections: list[StoredCorrection] = Field(default_factory=list)
    models: list[ModelMetadata] = Field(default_factory=list)
    timings: Timing
    images_retained: Literal[False] = False
    eligible_for_training: Literal[False] = False
    client_evidence_provenance: ClientEvidenceProvenance | None = None
    insights: ScanInsights | None = None


class ErrorResponse(ContractModel):
    error_code: str
    message: str
    trace_id: str
    retryable: bool = False
