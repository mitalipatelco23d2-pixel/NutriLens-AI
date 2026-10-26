"""Governed R15 model-registry inspection for authorized administrators."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from hashlib import sha256
from importlib.util import find_spec
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ai.features.scan_features import ScanFeatureVector, build_scan_features
from ai.food_understanding.store import ScanNotFoundError
from backend.ai_worker_client import (
    is_azure_worker_configuration,
    is_oci_worker_configuration,
    is_supported_worker_configuration,
)
from backend.auth import User, current_user
from backend.entitlements import resolve_entitlements
from backend.r3_api import get_owned_scan_result
from backend.r4_api import get_r4_service
from backend.service_health import collect_service_health
from backend.settings import settings

router = APIRouter(prefix="/api/v1/system/models", tags=["R15 Model Registry"])
REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / "ai/model-registry/r3-models.json"


class RegistryModel(BaseModel):
    model_id: str
    name: str
    version: str
    task: str
    framework: str
    training_status: str
    license: str
    required: bool
    artifact_status: Literal["BUILT_IN", "NOT_INSTALLED", "PRESENT", "CHECKSUM_VERIFIED"]
    checksum: str | None
    dataset_version: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class ModelRegistryResponse(BaseModel):
    registry_version: str
    release: str
    download_policy: str
    models: list[RegistryModel]
    claims_boundary: str = (
        "Registry presence is not deployment readiness; only recorded held-out metrics support "
        "quality claims."
    )


RuntimeState = Literal[
    "READY_PUBLIC",
    "READY_LOCAL_ONLY",
    "DEGRADED",
    "FAILED",
    "BLOCKED_EXTERNAL",
]


class AIRuntimeComponent(BaseModel):
    state: RuntimeState
    detail: str


class AIRuntimeStatus(BaseModel):
    environment: str
    components: dict[str, AIRuntimeComponent]
    disclosure: str = (
        "Readiness labels expose capability state only; infrastructure addresses, credentials, "
        "and user data are never returned."
    )


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _identifier(model: dict[str, Any]) -> str:
    explicit = model.get("model_id")
    if isinstance(explicit, str) and explicit:
        return explicit
    name = str(model.get("name", "model")).casefold()
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")


def _artifact_status(
    model: dict[str, Any],
) -> Literal["BUILT_IN", "NOT_INSTALLED", "PRESENT", "CHECKSUM_VERIFIED"]:
    local_file = model.get("local_file")
    if not local_file:
        return "BUILT_IN"
    artifact = REPO_ROOT / str(local_file)
    if not artifact.exists():
        return "NOT_INSTALLED"
    checksum = model.get("checksum")
    if artifact.is_file() and isinstance(checksum, str) and _file_sha256(artifact) == checksum:
        return "CHECKSUM_VERIFIED"
    return "PRESENT"


@lru_cache(maxsize=1)
def load_model_registry() -> ModelRegistryResponse:
    payload: dict[str, Any] = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    raw_models = payload.get("models")
    if not isinstance(raw_models, list) or not raw_models:
        raise RuntimeError("Model registry must contain at least one model.")
    models: list[RegistryModel] = []
    for raw in raw_models:
        if not isinstance(raw, dict):
            raise RuntimeError("Model registry entries must be objects.")
        for required in ("name", "version", "task", "framework", "training_status", "license"):
            if not isinstance(raw.get(required), str) or not raw[required]:
                raise RuntimeError(f"Model registry entry is missing {required}.")
        metrics = raw.get("metrics", {})
        if not isinstance(metrics, dict):
            raise RuntimeError("Model metrics must be an object.")
        models.append(
            RegistryModel(
                model_id=_identifier(raw),
                name=str(raw["name"]),
                version=str(raw["version"]),
                task=str(raw["task"]),
                framework=str(raw["framework"]),
                training_status=str(raw["training_status"]),
                license=str(raw["license"]),
                required=bool(raw.get("required", False)),
                artifact_status=_artifact_status(raw),
                checksum=str(raw["checksum"]) if raw.get("checksum") else None,
                dataset_version=(
                    str(raw["dataset_version"]) if raw.get("dataset_version") else None
                ),
                metrics=metrics,
            )
        )
    return ModelRegistryResponse(
        registry_version=str(payload["registry_version"]),
        release=str(payload["release"]),
        download_policy=str(payload["download_policy"]),
        models=models,
    )


@router.get("", response_model=ModelRegistryResponse)
def get_model_registry(user: Annotated[User, Depends(current_user)]) -> ModelRegistryResponse:
    entitlements = resolve_entitlements(user.plan, user.subscription_status, set(user.roles)).values
    if not bool(entitlements["admin.enabled"]):
        raise HTTPException(status_code=403, detail="Administrator role required.")
    return load_model_registry()


@router.get("/runtime", response_model=AIRuntimeStatus)
def get_ai_runtime_status(user: Annotated[User, Depends(current_user)]) -> AIRuntimeStatus:
    entitlements = resolve_entitlements(user.plan, user.subscription_status, set(user.roles)).values
    if not bool(entitlements["admin.enabled"]):
        raise HTTPException(status_code=403, detail="Administrator role required.")

    ready_state: RuntimeState = (
        "READY_PUBLIC" if settings.ai_runtime_public_validated else "READY_LOCAL_ONLY"
    )
    opencv_ready = find_spec("cv2") is not None
    yolo_artifact = Path(settings.r3_model_cache) / "custom/nutrition-table-yolo11n-v1.pt"
    yolo_ready = yolo_artifact.is_file() and find_spec("ultralytics") is not None
    paddle_root = Path(settings.r3_model_cache) / "paddle" / "official_models"
    paddle_ready = paddle_root.is_dir() and find_spec("paddleocr") is not None
    easyocr_ready = (Path(settings.r3_model_cache) / "easyocr").is_dir() and find_spec(
        "easyocr"
    ) is not None
    semantic_model_ready = Path(settings.semantic_rag_model_path).is_dir()
    semantic_index_ready = (
        Path(settings.semantic_rag_index_dir) / "knowledge.index"
    ).is_file() and (Path(settings.semantic_rag_index_dir) / "manifest.json").is_file()
    semantic_runtime_candidate = (
        settings.semantic_rag_enabled
        and semantic_model_ready
        and semantic_index_ready
        and find_spec("sentence_transformers") is not None
        and find_spec("faiss") is not None
    )
    semantic_runtime_ready = False
    if semantic_runtime_candidate:
        try:
            from backend.knowledge_api import get_semantic_knowledge_retriever

            get_semantic_knowledge_retriever()
            semantic_runtime_ready = True
        except RuntimeError:
            semantic_runtime_ready = False
    service_health = collect_service_health(settings)
    llm_ready = (
        settings.llm_provider == "ollama"
        and bool(settings.llm_base_url)
        and bool(settings.llm_model)
        and bool(settings.llm_service_token)
    )
    components = {
        "opencv": AIRuntimeComponent(
            state=ready_state if opencv_ready else "FAILED",
            detail="CPU image validation and preprocessing are available."
            if opencv_ready
            else "OpenCV runtime is absent.",
        ),
        "yolo11n": AIRuntimeComponent(
            state=ready_state if yolo_ready else "DEGRADED",
            detail="Validated nutrition-table detector is loaded."
            if yolo_ready
            else "Runtime package or verified model artifact is absent.",
        ),
        "paddleocr": AIRuntimeComponent(
            state=ready_state if paddle_ready else "DEGRADED",
            detail="Cached PaddleOCR models are available."
            if paddle_ready
            else "PaddleOCR runtime or cached models are absent.",
        ),
        "easyocr": AIRuntimeComponent(
            state=ready_state if easyocr_ready else "DEGRADED",
            detail="Cached EasyOCR fallback models are available."
            if easyocr_ready
            else "EasyOCR fallback is not packaged or validated.",
        ),
        "r3": AIRuntimeComponent(
            state=ready_state if opencv_ready and yolo_ready and paddle_ready else "DEGRADED",
            detail="Structured scanning remains fail-safe; heavy OCR may be unavailable.",
        ),
        "r4": AIRuntimeComponent(
            state=ready_state,
            detail="Bundled deterministic ingredient intelligence is available.",
        ),
        "sentence_bert": AIRuntimeComponent(
            state="READY_LOCAL_ONLY" if semantic_runtime_ready else "DEGRADED",
            detail=(
                "Local-only governed embedding model is configured."
                if semantic_runtime_ready
                else "Optional embedding runtime is disabled or its local artifacts are absent."
            ),
        ),
        "faiss": AIRuntimeComponent(
            state="READY_LOCAL_ONLY" if semantic_runtime_ready else "DEGRADED",
            detail=(
                "Checksum-bound governed FAISS index is configured."
                if semantic_runtime_ready
                else "Optional governed FAISS index is disabled or absent."
            ),
        ),
        "neo4j": AIRuntimeComponent(
            state=(ready_state if service_health.get("neo4j") == "healthy" else "DEGRADED"),
            detail="Hosted graph service is reachable."
            if service_health.get("neo4j") == "healthy"
            else "Bounded in-process observed-scan graph fallback is active.",
        ),
        "rag": AIRuntimeComponent(
            state="READY_LOCAL_ONLY" if semantic_runtime_ready else "DEGRADED",
            detail=(
                "Authenticated semantic retrieval preserves governed records and citations."
                if semantic_runtime_ready
                else "Governed lexical retrieval with citations remains the deterministic fallback."
            ),
        ),
        "llm": AIRuntimeComponent(
            state=ready_state if llm_ready else "DEGRADED",
            detail="Authenticated internal synthesis provider is configured."
            if llm_ready
            else "Deterministic evidence explanation fallback is active.",
        ),
        "server_ai_worker": AIRuntimeComponent(
            state=(
                ready_state
                if is_supported_worker_configuration(
                    settings.ai_worker_provider, settings.ai_worker_url
                )
                and settings.ai_worker_token
                else "BLOCKED_EXTERNAL"
            ),
            detail=(
                "Authenticated OCI AI worker is configured."
                if is_oci_worker_configuration(settings.ai_worker_provider, settings.ai_worker_url)
                and settings.ai_worker_token
                else "Authenticated Azure AI worker fallback bridge is configured."
                if is_azure_worker_configuration(
                    settings.ai_worker_provider, settings.ai_worker_url
                )
                and settings.ai_worker_token
                else "Fallback AI worker is not configured or blocked."
            ),
        ),
        "usage_quotas": AIRuntimeComponent(
            state=ready_state,
            detail="Entitlement checks and durable assistant/scan reservations are enforced.",
        ),
    }
    return AIRuntimeStatus(environment=settings.app_environment, components=components)


@router.get("/features/scans/{scan_id}", response_model=ScanFeatureVector)
def get_scan_feature_vector(
    scan_id: str,
    user: Annotated[User, Depends(current_user)],
) -> ScanFeatureVector:
    """Inspect a de-identified deterministic feature vector as an administrator."""

    entitlements = resolve_entitlements(user.plan, user.subscription_status, set(user.roles)).values
    if not bool(entitlements["admin.enabled"]):
        raise HTTPException(status_code=403, detail="Administrator role required.")
    try:
        scan = get_owned_scan_result(scan_id, user)
    except ScanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scan not found.") from exc
    intelligence = get_r4_service().analyze(scan.ingredients, scan.nutrition)
    return build_scan_features(scan, intelligence)
