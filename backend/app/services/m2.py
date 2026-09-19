"""Explicit adapter from the stable M1 contract to both M2 components."""

from __future__ import annotations

import math
from typing import Any

from ..core.config import get_settings
from ..core.errors import (
    InvalidModelInputError,
    ModelInferenceError,
    ModelUnavailableError,
)
from ..models.health_risk import IngredientRiskService
from ..models.scoring import calculate_nutrition_health_score


class M2HealthPredictor:
    provider = "member_2_nutrition_and_ingredient_risk"

    # M1 stores sodium in grams. The M2 source rules use milligrams.
    _nutrition_mapping = {
        "sugars_100g": ("sugar_g", 1.0),
        "saturated_fat_100g": ("saturated_fat_g", 1.0),
        "trans_fat_100g": ("trans_fat_g", 1.0),
        "sodium_100g": ("sodium_mg", 1000.0),
    }

    def __init__(self, risk_service: IngredientRiskService) -> None:
        self.risk_service = risk_service

    @staticmethod
    def _finite_non_negative(value: Any) -> bool:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return False
        return math.isfinite(number) and number >= 0

    def _nutrition_result(self, nlp_result: dict[str, Any]) -> dict[str, Any]:
        basis = str(nlp_result.get("basis") or "unknown")
        if basis != "per_100g":
            return {
                "available": False,
                "basis": basis,
                "health_score": None,
                "score_level": None,
                "missing_nutrients": [],
                "detail": (
                    "M2 nutrition scoring requires a per_100g basis; "
                    "no basis conversion was attempted."
                ),
            }

        source = nlp_result.get("nutrition") or {}
        missing = [
            field
            for field in self._nutrition_mapping
            if field not in source or source[field] is None
        ]
        invalid = [
            field
            for field in self._nutrition_mapping
            if field in source
            and source[field] is not None
            and not self._finite_non_negative(source[field])
        ]
        if missing or invalid:
            detail = "Required nutrition measurements are missing."
            if invalid:
                detail = "Required nutrition measurements contain invalid values."
            return {
                "available": False,
                "basis": basis,
                "health_score": None,
                "score_level": None,
                "missing_nutrients": missing,
                "invalid_nutrients": invalid,
                "detail": detail,
            }

        mapped = {
            target: float(source[source_field]) * multiplier
            for source_field, (target, multiplier) in self._nutrition_mapping.items()
        }
        score = calculate_nutrition_health_score(
            mapped,
            additives=list(nlp_result.get("additives") or []),
            allergens=list(nlp_result.get("allergens") or []),
        )
        return {"available": True, "basis": basis, **score}

    def _risk_result(self, nlp_result: dict[str, Any]) -> dict[str, Any]:
        raw_ingredients = nlp_result.get("ingredients")
        if raw_ingredients is not None and not isinstance(
            raw_ingredients, (list, tuple)
        ):
            return {
                "available": False,
                "risk_level": None,
                "probabilities": {},
                "detail": "Parsed ingredients must be a list of strings.",
            }
        ingredients = list(raw_ingredients or [])
        if not ingredients:
            return {
                "available": False,
                "risk_level": None,
                "probabilities": {},
                "detail": "Ingredient-risk classification requires parsed ingredients.",
            }
        try:
            result = self.risk_service.predict(ingredients)
        except (
            InvalidModelInputError,
            ModelInferenceError,
            ModelUnavailableError,
        ) as exc:
            return {
                "available": False,
                "risk_level": None,
                "probabilities": {},
                "detail": str(exc),
            }
        return {"available": True, **result}

    def predict(self, nlp_result: dict[str, Any]) -> dict[str, Any]:
        nutrition_score = self._nutrition_result(nlp_result)
        ingredient_risk = self._risk_result(nlp_result)
        available_count = sum(
            (nutrition_score["available"], ingredient_risk["available"])
        )
        if available_count == 2:
            status = "available"
        elif available_count == 1:
            status = "partial"
        else:
            status = "unavailable"

        warnings: list[str] = []
        if not nutrition_score["available"]:
            warnings.append(nutrition_score["detail"])
        warnings.extend(nutrition_score.get("warnings") or [])
        if not ingredient_risk["available"]:
            warnings.append(ingredient_risk["detail"])

        return {
            "status": status,
            "health_score": nutrition_score.get("health_score"),
            "score_level": nutrition_score.get("score_level"),
            "risk_level": ingredient_risk.get("risk_level"),
            "basis": nutrition_score["basis"],
            "nutrition_score": nutrition_score,
            "ingredient_risk": ingredient_risk,
            "model_version": "m2_combined_v1",
            "warnings": list(dict.fromkeys(warnings)),
        }


_m2_health_predictor: M2HealthPredictor | None = None


def get_m2_health_predictor() -> M2HealthPredictor:
    global _m2_health_predictor
    if _m2_health_predictor is None:
        settings = get_settings()
        _m2_health_predictor = M2HealthPredictor(
            IngredientRiskService(
                model_path=settings.risk_model_path,
                vectorizer_path=settings.risk_vectorizer_path,
                expected_model_sha256=settings.risk_model_sha256,
                expected_vectorizer_sha256=settings.risk_vectorizer_sha256,
                expected_sklearn_version=settings.risk_sklearn_version,
            )
        )
    return _m2_health_predictor
