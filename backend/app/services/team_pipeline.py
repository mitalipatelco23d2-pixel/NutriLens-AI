from __future__ import annotations

from typing import Any
from uuid import uuid4

from ..core.config import Settings, get_settings
from ..ocr.service import execute_ocr
from ..schemas.team import TeamAnalysisResponse, TeamOcrSummary
from ..scoring.predictor import HealthScoreService
from .team_contracts import (
    AnalysisExplainer,
    HealthPredictor,
    LabelTextAnalyzer,
    analyze_label_text,
    analyze_ocr_result,
    explain_analysis,
    predict_health,
)
from .m2 import get_m2_health_predictor
from .m5 import get_m5_explainer


class TeamAnalysisPipeline:
    """Stable M4 orchestration boundary for M1, M2, M3, and M5 integrations."""

    def __init__(
        self,
        text_analyzer: LabelTextAnalyzer | None = None,
        health_predictor: HealthPredictor | None = None,
        explainer: AnalysisExplainer | None = None,
        legacy_scorer: HealthScoreService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.text_analyzer = text_analyzer
        self.health_predictor = health_predictor
        self.explainer = explainer
        self.legacy_scorer = legacy_scorer
        self.settings = settings or get_settings()

    def _finish(
        self,
        analysis: dict[str, Any],
        ocr_summary: TeamOcrSummary | None,
    ) -> TeamAnalysisResponse:
        health = predict_health(analysis, self.health_predictor, self.legacy_scorer)
        explanation = explain_analysis(analysis, health.get("result"), self.explainer)
        warnings = list(analysis.get("warnings") or [])
        warnings.extend(health.get("warnings") or [])
        warnings.extend(explanation.get("warnings") or [])
        if health.get("warning"):
            warnings.append(health["warning"])
        if explanation.get("warning"):
            warnings.append(explanation["warning"])
        elif not explanation["available"]:
            warnings.append("Member 5 explanation is not configured.")
        complete = (
            health["integration"]["status"] == "available"
            and explanation["integration"]["status"] == "available"
        )
        return TeamAnalysisResponse(
            request_id=str(uuid4()),
            status="success" if complete else "partial_success",
            ocr=ocr_summary,
            analysis={key: value for key, value in analysis.items() if key != "warnings"},
            health=health.get("result"),
            explanation=explanation.get("result"),
            integrations={
                "nlp": analysis["integration"],
                "health": health["integration"],
                "explanation": explanation["integration"],
            },
            warnings=list(dict.fromkeys(warnings)),
        )

    def analyze_image(
        self,
        image_bytes: bytes,
        content_type: str | None,
        engine: str | None = None,
    ) -> TeamAnalysisResponse:
        execution = execute_ocr(
            image_bytes, engine=engine, content_type=content_type, settings=self.settings
        )
        contract = execution.normalized_contract(include_raw_text=True)
        analysis = analyze_ocr_result(execution.result, contract, self.text_analyzer)
        return self._finish(
            analysis,
            TeamOcrSummary(
                engine=execution.result.engine,
                confidence=contract["mean_confidence"],
                rotation=execution.result.selected_rotation,
            ),
        )

    def analyze_text(self, ocr_result: dict[str, Any]) -> TeamAnalysisResponse:
        return self._finish(analyze_label_text(ocr_result, self.text_analyzer), None)


_team_pipeline: TeamAnalysisPipeline | None = None


def get_team_analysis_pipeline() -> TeamAnalysisPipeline:
    global _team_pipeline
    if _team_pipeline is None:
        m2_predictor = get_m2_health_predictor()
        _team_pipeline = TeamAnalysisPipeline(
            health_predictor=m2_predictor,
            explainer=get_m5_explainer(m2_predictor.risk_service),
        )
    return _team_pipeline
