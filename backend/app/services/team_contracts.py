from __future__ import annotations

import logging
from typing import Any, Protocol

from ..core.errors import InvalidModelInputError, ModelInferenceError, ModelUnavailableError
from ..nlp.parser import (
    PackagedFoodNlpAnalyzer,
    canonical_nutrition as _canonical_nutrition,
)
from ..ocr.extractor import OcrResult
from ..ocr.nutrition_parser import MODEL_FIELDS, NutritionParseResult, parse_nutrition_text
from ..scoring.predictor import HealthScoreService, get_health_score_service


logger = logging.getLogger(__name__)
_default_nlp_analyzer = PackagedFoodNlpAnalyzer()


class LabelTextAnalyzer(Protocol):
    provider: str

    def analyze(self, ocr_result: dict[str, Any]) -> dict[str, Any]: ...


class HealthPredictor(Protocol):
    provider: str

    def predict(self, nlp_result: dict[str, Any]) -> dict[str, Any]: ...


class AnalysisExplainer(Protocol):
    provider: str

    def explain(
        self, nlp_result: dict[str, Any], health_result: dict[str, Any] | None
    ) -> dict[str, Any]: ...


def canonical_nutrition(parsed: NutritionParseResult) -> dict[str, float]:
    """Backward-compatible import used by development benchmark reporting."""
    return _canonical_nutrition(parsed)


def parse_ocr_nutrition(result: OcrResult) -> NutritionParseResult:
    """Choose the strongest structured parse among independent same-engine passes."""
    global_basis = parse_nutrition_text(result.text).basis
    if not result.candidate_evidence:
        return parse_nutrition_text(
            result.text, spatial_words=result.table_words, basis_override=global_basis
        )
    contextual_table_bases = {
        parsed.basis
        for evidence in result.candidate_evidence
        if evidence.region == "nutrition_table"
        for parsed in [
            parse_nutrition_text("Nutritional Information\n" + evidence.text)
        ]
        if parsed.basis != "unknown"
    }
    table_basis = (
        next(iter(contextual_table_bases))
        if len(contextual_table_bases) == 1
        else None
    )
    candidates: list[tuple[float, NutritionParseResult]] = []
    for evidence in result.candidate_evidence:
        evidence_basis = global_basis if global_basis != "unknown" else None
        if evidence_basis is None and evidence.region == "nutrition_table":
            evidence_basis = table_basis
        parsed = parse_nutrition_text(
            evidence.text,
            spatial_words=evidence.words,
            basis_override=evidence_basis,
        )
        rejected = sum(
            warning.startswith(("Rejected ", "Omitted "))
            for warning in parsed.warnings
        )
        score = (
            len(parsed.nutrients) * 100
            + (30 if parsed.basis != "unknown" else 0)
            + (10 if evidence.region == "nutrition_table" else 0)
            - rejected * 40
        )
        candidates.append((score, parsed))
    selected = max(candidates, key=lambda item: item[0])[1]
    # Do not mix arbitrary values between OCR passes. A missing field may only
    # be recovered when independent same-engine passes agree exactly. Energy is
    # additionally safe from one spatial pass when it carries an explicit kcal
    # or kJ unit inside the already-detected nutrition table.
    for field_name in {
        name for _, parsed in candidates for name in parsed.nutrients
    } - set(selected.nutrients):
        proposals = [
            parsed.nutrients[field_name]
            for _, parsed in candidates
            if field_name in parsed.nutrients
        ]
        signatures = {
            (item.source_value, item.source_unit, item.qualifier) for item in proposals
        }
        safe_consensus = len(proposals) >= 2 and len(signatures) == 1
        safe_energy = (
            field_name == "energy_100g"
            and len(proposals) == 1
            and proposals[0].source_unit in {"kcal", "kj"}
        )
        if safe_consensus or safe_energy:
            selected.nutrients[field_name] = proposals[0]
            selected.warnings.append(
                f"Recovered {field_name} from consistent same-engine OCR evidence."
            )
    selected.warnings = list(dict.fromkeys(selected.warnings))
    return selected


def analyze_label_text(
    ocr_result: dict[str, Any],
    analyzer: LabelTextAnalyzer | None = None,
    *,
    parsed_nutrition: NutritionParseResult | None = None,
) -> dict[str, Any]:
    """Stable Member 1 boundary backed by the lightweight packaged-food NLP."""
    if analyzer is None:
        result = _default_nlp_analyzer.analyze(
            ocr_result,
            parsed_nutrition=parsed_nutrition,
        )
        result["integration"] = {
            "status": "available",
            "provider": _default_nlp_analyzer.provider,
        }
        return result
    try:
        result = analyzer.analyze(ocr_result)
        return {**result, "integration": {"status": "available", "provider": analyzer.provider}}
    except Exception:
        logger.exception("Configured Member 1 analyzer failed; using built-in NLP")
    result = _default_nlp_analyzer.analyze(
        ocr_result,
        parsed_nutrition=parsed_nutrition,
    )
    result["integration"] = {
        "status": "fallback",
        "provider": _default_nlp_analyzer.provider,
    }
    result["warnings"].append(
        "The configured Member 1 analyzer was unavailable; built-in NLP was used."
    )
    return result


def analyze_ocr_result(
    result: OcrResult,
    normalized_contract: dict[str, Any],
    analyzer: LabelTextAnalyzer | None = None,
) -> dict[str, Any]:
    """Map M4's OCR object to its stable contract, then enter the M1 adapter."""
    parsed = parse_ocr_nutrition(result)
    return analyze_label_text(
        normalized_contract,
        analyzer,
        parsed_nutrition=parsed,
    )


def _legacy_features(nlp_result: dict[str, Any]) -> dict[str, float] | None:
    if nlp_result.get("basis") != "per_100g":
        return None
    nutrition = nlp_result.get("nutrition") or {}
    mapping = {"energy_100g": "energy_kj_100g", **{key: key for key in MODEL_FIELDS if key != "energy_100g"}}
    if any(source not in nutrition for source in mapping.values()):
        return None
    return {target: float(nutrition[source]) for target, source in mapping.items()}


def predict_health(
    nlp_result: dict[str, Any],
    predictor: HealthPredictor | None = None,
    legacy_scorer: HealthScoreService | None = None,
) -> dict[str, Any]:
    """Stable Member 2 boundary; current joblib output is legacy/development only."""
    if predictor is not None:
        try:
            result = predictor.predict(nlp_result)
            status = result.get("status", "available")
            warnings = list(result.get("warnings") or [])
            return {
                "available": status in {"available", "partial"},
                "result": result,
                "integration": {"status": status, "provider": predictor.provider},
                "warnings": warnings,
            }
        except Exception:
            logger.exception("Configured Member 2 predictor failed")
            return {
                "available": False,
                "result": None,
                "integration": {"status": "error", "provider": predictor.provider},
                "warning": "Member 2 health prediction was unavailable.",
            }
    features = _legacy_features(nlp_result)
    if features is None:
        return {
            "available": False,
            "result": None,
            "integration": {"status": "fallback", "provider": "legacy_development_scorer"},
            "warning": "Legacy health scoring requires all configured per-100-g model fields.",
        }
    try:
        value = (legacy_scorer or get_health_score_service()).predict(features)
    except (InvalidModelInputError, ModelInferenceError, ModelUnavailableError):
        return {
            "available": False,
            "result": None,
            "integration": {"status": "fallback", "provider": "legacy_development_scorer"},
            "warning": "The legacy development scorer is unavailable.",
        }
    return {
        "available": True,
        "result": {"legacy_score": value, "model_id": "legacy_development_health_score_model"},
        "integration": {"status": "fallback", "provider": "legacy_development_scorer"},
        "warning": "This is a legacy development score, not the final NutriLens 0-100 health score.",
    }


def explain_analysis(
    nlp_result: dict[str, Any],
    health_result: dict[str, Any] | None,
    explainer: AnalysisExplainer | None = None,
) -> dict[str, Any]:
    """Stable Member 5 boundary; unavailable output is explicit and never fabricated."""
    if explainer is None:
        return {
            "available": False,
            "result": None,
            "integration": {"status": "not_configured", "provider": "member_5_adapter"},
        }
    try:
        result = explainer.explain(nlp_result, health_result)
        status = str(result.get("status") or "available")
        if status not in {"available", "partial", "unavailable"}:
            status = "available"
        return {
            "available": status in {"available", "partial"},
            "result": result,
            "integration": {"status": status, "provider": explainer.provider},
            "warnings": list(result.get("warnings") or []),
        }
    except Exception:
        logger.exception("Configured Member 5 explainer failed")
        return {
            "available": False,
            "result": None,
            "integration": {"status": "error", "provider": explainer.provider},
            "warning": "Member 5 explanation was unavailable.",
        }
