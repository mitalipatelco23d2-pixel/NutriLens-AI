from __future__ import annotations

from fastapi import APIRouter, File, Query, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..core.config import get_settings
from ..ocr.extractor import tesseract_readiness
from ..ocr.preprocessing import read_upload_limited
from ..ocr.service import execute_ocr, resolve_ocr_engine
from ..schemas.common import DependencyStatus, LivenessResponse, ReadinessResponse
from ..schemas.nutrition import ImageAnalysisResponse, ManualNutritionRequest, ManualScoreResponse, HealthScoreResult
from ..schemas.team import AnalyzeTextRequest, TeamAnalysisResponse
from ..scoring.predictor import get_health_score_service
from ..services.pipeline import get_image_analysis_pipeline
from ..services.team_pipeline import get_team_analysis_pipeline


router = APIRouter(prefix="/api/v1")


@router.get("/health", response_model=LivenessResponse, tags=["system"])
def health() -> LivenessResponse:
    return LivenessResponse()


@router.get("/ready", response_model=ReadinessResponse, tags=["system"])
def readiness() -> ReadinessResponse | JSONResponse:
    settings = get_settings()
    model_ready, model_detail = get_health_score_service().readiness()
    tesseract_ready, tesseract_detail = tesseract_readiness(settings)
    frontend_ready = (settings.frontend_dir / "index.html").is_file()
    dependencies = {
        "model": DependencyStatus(ready=model_ready, detail=model_detail),
        "tesseract": DependencyStatus(ready=tesseract_ready, detail=tesseract_detail),
        "selected_ocr": DependencyStatus(
            ready=tesseract_ready,
            detail="Configured OCR engine: tesseract.",
        ),
        "frontend": DependencyStatus(
            ready=frontend_ready,
            detail="Demo frontend is available." if frontend_ready else "Demo frontend is unavailable.",
        ),
    }
    response = ReadinessResponse(
        status="ready" if model_ready and tesseract_ready else "not_ready",
        dependencies=dependencies,
    )
    if response.status == "not_ready":
        return JSONResponse(status_code=503, content=response.model_dump())
    return response


@router.post("/score/manual", response_model=ManualScoreResponse, tags=["analysis"])
def score_manual(request: ManualNutritionRequest) -> ManualScoreResponse:
    score = get_health_score_service().predict(request.model_features())
    return ManualScoreResponse(
        health_score=HealthScoreResult(performed=True, value=score)
    )


@router.post("/analyze/image", response_model=ImageAnalysisResponse, tags=["analysis"])
async def analyze_image(
    image: UploadFile = File(...),
    include_raw_text: bool = Query(default=False),
) -> ImageAnalysisResponse:
    settings = get_settings()
    content = await read_upload_limited(image, settings.max_upload_bytes)
    return await run_in_threadpool(
        get_image_analysis_pipeline().analyze,
        content,
        image.content_type,
        include_raw_text,
    )


@router.post("/ocr", tags=["integration"])
async def ocr_only(
    image: UploadFile = File(...),
    engine: str | None = Query(default=None, description="tesseract"),
):
    settings = get_settings()
    content = await read_upload_limited(image, settings.max_upload_bytes)
    selected = resolve_ocr_engine(engine, settings)
    execution = await run_in_threadpool(
        execute_ocr, content, selected, image.content_type, settings
    )
    return execution.normalized_contract(include_raw_text=True)


@router.post("/analyze-text", response_model=TeamAnalysisResponse, tags=["integration"])
async def analyze_text(request: AnalyzeTextRequest) -> TeamAnalysisResponse:
    contract = {
        "raw_text": request.raw_text,
        "lines": [line.model_dump() for line in request.lines],
    }
    return await run_in_threadpool(get_team_analysis_pipeline().analyze_text, contract)


@router.post("/analyze", response_model=TeamAnalysisResponse, tags=["integration"])
async def analyze(image: UploadFile = File(...)) -> TeamAnalysisResponse:
    settings = get_settings()
    content = await read_upload_limited(image, settings.max_upload_bytes)
    return await run_in_threadpool(
        get_team_analysis_pipeline().analyze_image,
        content,
        image.content_type,
        None,
    )


legacy_router = APIRouter(include_in_schema=False)


@legacy_router.get("/health", response_model=LivenessResponse)
def legacy_health() -> LivenessResponse:
    return health()


@legacy_router.get("/ready", response_model=ReadinessResponse)
def legacy_readiness() -> ReadinessResponse | JSONResponse:
    return readiness()


@legacy_router.post("/predict/health_score", response_model=ManualScoreResponse)
def legacy_score_manual(request: ManualNutritionRequest) -> ManualScoreResponse:
    return score_manual(request)


@legacy_router.post("/predict/health_score_from_image", response_model=ImageAnalysisResponse)
async def legacy_analyze_image(
    image: UploadFile = File(...),
    include_raw_text: bool = Query(default=False),
) -> ImageAnalysisResponse:
    return await analyze_image(image, include_raw_text)
