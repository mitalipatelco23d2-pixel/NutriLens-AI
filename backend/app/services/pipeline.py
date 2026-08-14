from __future__ import annotations

import logging
from dataclasses import asdict

from ..core.config import Settings, get_settings
from ..core.errors import InvalidModelInputError, ModelInferenceError, ModelUnavailableError
from ..nlp.parser import (
    FallbackIngredientExtractor,
    IngredientExtractor,
    extract_explicit_allergens,
)
from ..ocr.nutrition_parser import MODEL_FIELDS
from ..ocr.service import execute_ocr
from ..schemas.common import IntegrationStatus, OcrMetadata
from ..schemas.nutrition import HealthScoreResult, ImageAnalysisResponse, NutrientValue
from ..scoring.predictor import HealthScoreService, get_health_score_service
from .integrations import AnalysisContext, PipelineExtension
from .team_contracts import parse_ocr_nutrition

logger = logging.getLogger(__name__)


class ImageAnalysisPipeline:
    """Coordinates backend-owned steps and exposes stable team integration seams."""

    def __init__(
        self,
        scorer: HealthScoreService | None = None,
        ingredient_extractor: IngredientExtractor | None = None,
        extensions: tuple[PipelineExtension, ...] = (),
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.scorer = scorer or get_health_score_service()
        self.ingredient_extractor = ingredient_extractor or FallbackIngredientExtractor()
        self.extensions = extensions

    def analyze(
        self,
        image_bytes: bytes,
        content_type: str | None,
        include_raw_text: bool = False,
    ) -> ImageAnalysisResponse:
        execution = execute_ocr(
            image_bytes,
            engine=self.settings.ocr_engine,
            content_type=content_type,
            settings=self.settings,
        )
        prepared = execution.prepared
        ocr_result = execution.result
        parsed = parse_ocr_nutrition(ocr_result)
        ingredients = self.ingredient_extractor.extract(ocr_result.text)
        allergens = extract_explicit_allergens(ocr_result.text)
        normalized = parsed.normalized_model_values
        missing = [field for field in MODEL_FIELDS if field not in normalized]
        warnings = list(dict.fromkeys(parsed.warnings))

        score = HealthScoreResult(
            performed=False,
            detail="Scoring requires all model fields normalized per 100 g.",
        )
        if not missing and parsed.basis == "per_100g":
            try:
                score = HealthScoreResult(
                    performed=True,
                    value=self.scorer.predict(normalized),
                )
            except (ModelUnavailableError, ModelInferenceError, InvalidModelInputError):
                warnings.append("Nutrition was extracted, but the health-score model is unavailable.")
                score = HealthScoreResult(
                    performed=False,
                    detail="Health scoring is currently unavailable.",
                )
        elif missing:
            warnings.append("Health scoring was skipped because required nutrients are missing.")

        extracted = {
            name: NutrientValue(**asdict(value))
            for name, value in parsed.nutrients.items()
        }
        integrations = {
            "ingredient_nlp": IntegrationStatus(
                status="fallback",
                provider="basic_backend_parser",
                detail="Replace through the IngredientExtractor interface.",
            ),
            "health_risk": IntegrationStatus(
                status="not_configured", provider="member_2_adapter"
            ),
            "rag": IntegrationStatus(
                status="not_configured", provider="member_5_adapter"
            ),
            "xai": IntegrationStatus(
                status="not_configured", provider="member_5_adapter"
            ),
        }
        extension_outputs: dict[str, dict] = {}
        context = AnalysisContext(
            nutrition=normalized,
            ingredients=ingredients,
            allergens=allergens,
            health_score=score.value,
            basis=parsed.basis,
        )
        for extension in self.extensions:
            try:
                extension_outputs[extension.key] = extension.analyze(context)
                integrations[extension.key] = IntegrationStatus(
                    status="available", provider=extension.provider
                )
            except Exception:
                logger.exception("Optional pipeline extension failed: %s", extension.key)
                integrations[extension.key] = IntegrationStatus(
                    status="error",
                    provider=extension.provider,
                    detail="The optional integration failed without interrupting base analysis.",
                )
                warnings.append(f"Optional {extension.key} integration was unavailable.")

        complete = score.performed
        return ImageAnalysisResponse(
            status="success" if complete else "partial",
            basis=parsed.basis,
            extracted_nutrition=extracted,
            normalized_nutrition=normalized,
            ingredients=ingredients,
            allergens=allergens,
            missing_required_fields=missing,
            warnings=list(dict.fromkeys(warnings)),
            health_score=score,
            ocr=OcrMetadata(
                engine=ocr_result.engine,
                language=ocr_result.language,
                preprocessing_applied=prepared.preprocessing_applied,
                mean_confidence=ocr_result.mean_confidence,
                selected_rotation=ocr_result.selected_rotation,
                selected_psm=ocr_result.selected_psm,
                attempted_psms=list(ocr_result.attempted_psms),
                candidate_count=ocr_result.candidate_count,
                selected_region=ocr_result.selected_region,
                image_width=prepared.original_width,
                image_height=prepared.original_height,
            ),
            integrations=integrations,
            extensions=extension_outputs,
            raw_text=ocr_result.text if include_raw_text else None,
        )


_pipeline: ImageAnalysisPipeline | None = None


def get_image_analysis_pipeline() -> ImageAnalysisPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = ImageAnalysisPipeline()
    return _pipeline
