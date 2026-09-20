"""Readiness checks for required and optional NutriLens components."""

from __future__ import annotations

from importlib.util import find_spec
from typing import Any

from sklearn import __version__ as sklearn_version

from ..core.config import Settings
from ..knowledge_base import KnowledgeBaseService
from ..models.scoring import calculate_nutrition_health_score
from ..ocr.extractor import tesseract_readiness
from ..rag.corpus import CorpusUnavailableError, LoadedCorpus
from ..schemas.common import DependencyStatus
from .m2 import get_m2_health_predictor


REQUIRED_COMPONENTS = (
    "backend_api",
    "tesseract",
    "nutrition_scoring",
    "ingredient_risk",
)


def _dependency(
    *,
    ready: bool,
    detail: str,
    required: bool,
    enabled: bool = True,
    metadata: dict[str, Any] | None = None,
) -> DependencyStatus:
    return DependencyStatus(
        ready=ready,
        detail=detail,
        metadata={
            "required": required,
            "enabled": enabled,
            **(metadata or {}),
        },
    )


def nutrition_scoring_readiness() -> tuple[bool, str]:
    """Exercise the deterministic M2 rules without relying on a model artifact."""

    try:
        result = calculate_nutrition_health_score(
            {
                "sugar_g": 0.0,
                "saturated_fat_g": 0.0,
                "trans_fat_g": 0.0,
                "sodium_mg": 0.0,
            }
        )
    except Exception:
        return False, "M2 deterministic nutrition scoring is unavailable."
    if result.get("model_version") != "m2_nutrition_rules_v1":
        return False, "M2 deterministic nutrition scoring returned an unexpected contract."
    return True, "M2 deterministic per-100-g nutrition scoring is available."


def knowledge_base_readiness(settings: Settings) -> DependencyStatus:
    result = KnowledgeBaseService(
        settings.m5_knowledge_base_path,
        expected_sha256=settings.m5_knowledge_base_sha256,
    ).lookup([])
    dataset = result.get("dataset") or {}
    verified = bool(dataset.get("hash_matches_reviewed_file"))
    ready = result.get("status") == "available" and verified
    detail = (
        "Verified optional M5 knowledge-base CSV is available."
        if ready
        else (result.get("warnings") or ["Optional M5 knowledge base is unavailable."])[0]
    )
    if result.get("status") == "available" and not verified:
        detail = "Optional M5 knowledge-base identity is not verified."
    return _dependency(
        ready=ready,
        detail=detail,
        required=False,
        metadata={
            "row_count": dataset.get("row_count"),
            "hash_verified": verified,
        },
    )


def shap_readiness(
    settings: Settings,
    *,
    ingredient_risk_ready: bool,
) -> DependencyStatus:
    installed = find_spec("shap") is not None
    if not settings.m5_shap_enabled:
        return _dependency(
            ready=False,
            detail="Optional SHAP attribution is disabled by configuration.",
            required=False,
            enabled=False,
            metadata={"dependency_installed": installed},
        )
    if not ingredient_risk_ready:
        detail = "Optional SHAP attribution requires the ingredient-risk classifier."
        ready = False
    elif not installed:
        detail = "Optional SHAP dependency is unavailable."
        ready = False
    else:
        detail = "Optional SHAP attribution is configured and locally available."
        ready = True
    return _dependency(
        ready=ready,
        detail=detail,
        required=False,
        metadata={"dependency_installed": installed},
    )


def rag_readiness(settings: Settings) -> DependencyStatus:
    corpus_metadata: dict[str, Any] = {"corpus_available": False}
    corpus_detail = "The optional source-backed RAG corpus is unavailable."
    try:
        corpus = LoadedCorpus.load(
            settings.m5_rag_corpus_dir,
            jurisdiction=settings.m5_rag_jurisdiction,
        )
    except CorpusUnavailableError as exc:
        corpus_ready = False
        corpus_detail = str(exc)
    else:
        corpus_ready = True
        corpus_metadata = {"corpus_available": True, **corpus.public_metadata()}

    credentials_configured = bool(
        settings.cloudflare_account_id and settings.cloudflare_api_token
    )
    metadata = {**corpus_metadata, "live_request_performed": False}
    if not settings.m5_rag_enabled:
        return _dependency(
            ready=False,
            detail="Optional source-backed RAG is disabled by configuration.",
            required=False,
            enabled=False,
            metadata=metadata,
        )
    if not corpus_ready:
        return _dependency(
            ready=False,
            detail=corpus_detail,
            required=False,
            metadata=metadata,
        )
    if not credentials_configured:
        return _dependency(
            ready=False,
            detail="Optional source-backed RAG credentials are not configured.",
            required=False,
            metadata=metadata,
        )
    return _dependency(
        ready=True,
        detail=(
            "Optional source-backed RAG is locally configured; "
            "provider connectivity was not tested."
        ),
        required=False,
        metadata=metadata,
    )


def build_readiness_dependencies(settings: Settings) -> dict[str, DependencyStatus]:
    tesseract_ready, tesseract_detail = tesseract_readiness(settings)
    nutrition_ready, nutrition_detail = nutrition_scoring_readiness()
    risk_ready, risk_detail = get_m2_health_predictor().risk_service.readiness()
    frontend_ready = (settings.frontend_dir / "index.html").is_file()

    dependencies = {
        "backend_api": _dependency(
            ready=True,
            detail="Backend API is available.",
            required=True,
        ),
        "tesseract": _dependency(
            ready=tesseract_ready,
            detail=tesseract_detail,
            required=True,
        ),
        "selected_ocr": _dependency(
            ready=tesseract_ready,
            detail="Configured OCR engine: tesseract.",
            required=False,
        ),
        "nutrition_scoring": _dependency(
            ready=nutrition_ready,
            detail=nutrition_detail,
            required=True,
            metadata={"model_version": "m2_nutrition_rules_v1"},
        ),
        "ingredient_risk": _dependency(
            ready=risk_ready,
            detail=risk_detail,
            required=True,
            metadata={
                "expected_sklearn_version": settings.risk_sklearn_version,
                "runtime_sklearn_version": sklearn_version,
            },
        ),
        "knowledge_base": knowledge_base_readiness(settings),
        "shap": shap_readiness(
            settings,
            ingredient_risk_ready=risk_ready,
        ),
        "rag": rag_readiness(settings),
        "frontend": _dependency(
            ready=frontend_ready,
            detail=(
                "Demo frontend is available."
                if frontend_ready
                else "Demo frontend is unavailable."
            ),
            required=False,
        ),
    }
    return dependencies


def required_dependencies_ready(
    dependencies: dict[str, DependencyStatus],
) -> bool:
    return all(
        component in dependencies and dependencies[component].ready
        for component in REQUIRED_COMPONENTS
    )
