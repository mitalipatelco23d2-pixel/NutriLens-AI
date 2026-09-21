from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.ocr.easyocr_service import EasyOCRService
from app.pipeline.analysis_pipeline import analyze_food_label


router = APIRouter(prefix="/api")

ALLOWED_IMAGE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
}


@router.get("/health")
def api_health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "NutriLens AI API",
    }


@router.post("/analyze")
async def analyze_food_label_image(
    file: UploadFile = File(...)
) -> dict[str, Any]:
    """Analyze a food-label image end-to-end."""

    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Unsupported file type. Please upload "
                "PNG, JPG, JPEG, or WEBP."
            ),
        )

    try:
        contents = await file.read()

        if not contents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded image is empty.",
            )

        # 1. OCR
        ocr_service = EasyOCRService()
        ocr_text = ocr_service.extract_text(
            contents,
            filename=file.filename or "label.png",
        )

        if not ocr_text.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No readable text was detected in the image.",
            )

        # 2. Complete NutriLens AI analysis
        analysis_result = analyze_food_label(ocr_text)

        # 3. API response
        return {
            "status": "success",
            "message": "Food label analyzed successfully.",
            "filename": file.filename,
            "ocr_text": ocr_text,
            "analysis": analysis_result,
        }

    except HTTPException:
        raise

    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Required dependency is missing: {str(e)}",
        ) from e

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Food-label analysis failed: {str(e)}",
        ) from e
