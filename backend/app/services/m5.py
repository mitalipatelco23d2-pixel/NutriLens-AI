"""M5 Phase 1: deterministic context, M2 pass-through explanations, and rules."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..core.config import get_settings
from ..knowledge_base import KnowledgeBaseService
from .recommendations import generate_recommendations


class M5Phase1Explainer:
    provider = "member_5_phase_1_deterministic"

    def __init__(self, knowledge_base: KnowledgeBaseService) -> None:
        self.knowledge_base = knowledge_base

    @staticmethod
    def _nutrition_explanation(
        health_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        health = health_result if isinstance(health_result, dict) else {}
        source = health.get("nutrition_score")
        source = source if isinstance(source, dict) else {}
        return {
            "available": source.get("available") is True,
            "health_score": health.get("health_score"),
            "score_level": health.get("score_level"),
            "basis": source.get("basis", health.get("basis", "unknown")),
            "reasons": deepcopy(source.get("reasons") or []),
            "breakdown": deepcopy(source.get("breakdown") or {}),
            "nutrition_breakdown": deepcopy(
                source.get("nutrition_breakdown") or {}
            ),
            "missing_nutrients": deepcopy(source.get("missing_nutrients") or []),
            "invalid_nutrients": deepcopy(source.get("invalid_nutrients") or []),
            "warnings": deepcopy(source.get("warnings") or []),
            "detail": source.get("detail"),
            "model_version": source.get("model_version"),
            "explanation_method": "existing_m2_rule_output_passthrough",
        }

    @staticmethod
    def _risk_explanation(
        health_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        health = health_result if isinstance(health_result, dict) else {}
        source = health.get("ingredient_risk")
        source = source if isinstance(source, dict) else {}
        return {
            "available": source.get("available") is True,
            "risk_level": source.get("risk_level", health.get("risk_level")),
            "probabilities": deepcopy(source.get("probabilities") or {}),
            "ingredient_text": source.get("ingredient_text"),
            "detail": source.get("detail"),
            "model_version": source.get("model_version"),
            "explanation_method": "existing_m2_prediction_summary_only",
            "model_rerun": False,
            "attribution_performed": False,
            "knowledge_base_causality_claimed": False,
        }

    def explain(
        self,
        nlp_result: dict[str, Any],
        health_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        health_snapshot = deepcopy(health_result)
        ingredients = nlp_result.get("ingredients")
        knowledge = self.knowledge_base.lookup(ingredients)
        nutrition = self._nutrition_explanation(health_snapshot)
        ingredient_risk = self._risk_explanation(health_snapshot)
        recommendations = generate_recommendations(nlp_result, health_snapshot)

        warnings = list(knowledge.get("warnings") or [])
        health_status = (
            health_snapshot.get("status")
            if isinstance(health_snapshot, dict)
            else "unavailable"
        )
        if health_status != "available":
            warnings.append(
                "M5 received a partial or unavailable M2 result; available components were preserved."
            )
        warnings.extend(recommendations.get("omissions") or [])

        complete = knowledge.get("status") == "available" and health_status == "available"
        any_output = bool(
            knowledge.get("matched")
            or knowledge.get("unmatched")
            or nutrition.get("available")
            or ingredient_risk.get("available")
            or recommendations.get("items")
        )
        status = "available" if complete else "partial" if any_output else "unavailable"
        return {
            "status": status,
            "nutrition": nutrition,
            "ingredient_risk": ingredient_risk,
            "knowledge_base": knowledge,
            "recommendations": recommendations,
            "methodology": {
                "knowledge_base": "deterministic_lookup_not_rag",
                "nutrition": "existing_m2_output_not_recalculated",
                "ingredient_risk": "existing_m2_output_not_rerun",
                "dynamic_shap": "not_implemented",
                "generative_rag": "not_implemented",
            },
            "warnings": list(dict.fromkeys(warnings)),
        }


_m5_explainer: M5Phase1Explainer | None = None


def get_m5_explainer() -> M5Phase1Explainer:
    global _m5_explainer
    if _m5_explainer is None:
        settings = get_settings()
        _m5_explainer = M5Phase1Explainer(
            KnowledgeBaseService(
                settings.m5_knowledge_base_path,
                expected_sha256=settings.m5_knowledge_base_sha256,
            )
        )
    return _m5_explainer
