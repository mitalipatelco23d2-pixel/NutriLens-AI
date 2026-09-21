from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.ocr.easyocr_service import EasyOCRService
from app.pipeline.analysis_pipeline import analyze_food_label
from app.knowledge_base.knowledge_base_service import load_knowledge_base
from app.models.health_risk.risk_service import model, vectorizer


# ============================================================
# API ROUTER
# ============================================================

router = APIRouter(
    prefix="/api/v1"
)


# ============================================================
# ALLOWED IMAGE TYPES
# ============================================================

ALLOWED_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}


# ============================================================
# HEALTH CHECK
# ============================================================

@router.get("/health")
def api_health() -> dict[str, str]:
    """
    Basic API health check.

    Endpoint:
        GET /api/v1/health
    """

    return {
        "status": "ok",
        "service": "NutriLens AI API",
    }


# ============================================================
# READINESS CHECK
# ============================================================

@router.get("/ready")
def api_ready() -> dict[str, Any]:
    """
    Check whether the required local NutriLens services
    are available.

    Endpoint:
        GET /api/v1/ready
    """

    checks: dict[str, bool] = {}

    # --------------------------------------------------------
    # TESSERACT OCR
    # --------------------------------------------------------

    try:
        ocr_service = EasyOCRService()

        checks["tesseract"] = bool(
            getattr(
                ocr_service,
                "tesseract_cmd",
                None,
            )
        )

    except Exception:
        checks["tesseract"] = False

    # --------------------------------------------------------
    # M2 MODEL
    # --------------------------------------------------------

    checks["m2_model"] = (
        model is not None
    )

    # --------------------------------------------------------
    # TF-IDF VECTORIZER
    # --------------------------------------------------------

    checks["tfidf_vectorizer"] = (
        vectorizer is not None
    )

    # --------------------------------------------------------
    # M5 KNOWLEDGE BASE
    # --------------------------------------------------------

    try:
        knowledge_base = load_knowledge_base()

        checks["knowledge_base"] = (
            len(knowledge_base) > 0
        )

    except Exception:
        checks["knowledge_base"] = False

    # --------------------------------------------------------
    # OVERALL STATUS
    # --------------------------------------------------------

    ready = all(
        checks.values()
    )

    return {
        "status": (
            "ready"
            if ready
            else "not_ready"
        ),
        "checks": checks,
    }


# ============================================================
# FOOD LABEL ANALYSIS
# ============================================================

@router.post("/analyze")
async def analyze_food_label_image(
    file: UploadFile = File(...)
) -> dict[str, Any]:
    """
    Analyze an uploaded food-label image.

    Endpoint:
        POST /api/v1/analyze
    """

    # --------------------------------------------------------
    # VALIDATE FILE TYPE
    # --------------------------------------------------------

    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unsupported file type. "
                "Please upload PNG, JPG, JPEG, or WEBP."
            ),
        )

    try:
        # ----------------------------------------------------
        # READ UPLOADED FILE
        # ----------------------------------------------------

        contents = await file.read()

        if not contents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded image is empty.",
            )

        # ----------------------------------------------------
        # OCR
        # ----------------------------------------------------

        ocr_service = EasyOCRService()

        ocr_text = ocr_service.extract_text(
            contents,
            filename=(
                file.filename
                or "label.png"
            ),
        )

        if not ocr_text.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "No readable text was detected "
                    "in the image."
                ),
            )

        # ----------------------------------------------------
        # COMPLETE NUTRILENS ANALYSIS
        # ----------------------------------------------------

        analysis_result = analyze_food_label(
            ocr_text
        )

        # ----------------------------------------------------
        # API RESPONSE
        # ----------------------------------------------------

        return {
            "status": "success",
            "message": (
                "Food label analyzed successfully."
            ),
            "filename": file.filename,
            "ocr_text": ocr_text,
            "analysis": analysis_result,
        }

    # --------------------------------------------------------
    # EXPECTED HTTP ERRORS
    # --------------------------------------------------------

    except HTTPException:
        raise

    # --------------------------------------------------------
    # MISSING DEPENDENCY
    # --------------------------------------------------------

    except ImportError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Required dependency is missing: "
                f"{error}"
            ),
        ) from error

    # --------------------------------------------------------
    # INVALID INPUT / SERVICE DATA
    # --------------------------------------------------------

    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from error

    # --------------------------------------------------------
    # TESSERACT / MODEL / OTHER SERVICE FAILURE
    # --------------------------------------------------------

    except FileNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
