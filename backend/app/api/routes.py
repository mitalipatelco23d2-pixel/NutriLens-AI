from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.nlp import process_text
from app.models.health_risk import predict_health_risk
from app.models.scoring import predict_score
from app.ocr.easyocr_service import EasyOCRService
from app.rag import query_knowledge_base
from app.xai import explain_result

router = APIRouter(prefix="/api")


ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


@router.post("/analyze")
async def analyze_food_label(file: UploadFile = File(...)) -> dict[str, Any]:
    """Analyze an uploaded food label image end-to-end.

    The pipeline is intentionally modular and mockable so each team can plug in
    their components without changing the API contract.

    Args:
        file: Uploaded food label image (PNG, JPG, JPEG, or WEBP)

    Returns:
        dict with OCR text, NLP results, scoring, health risk prediction,
        RAG knowledge base results, XAI explanations, and final summary

    Raises:
        HTTPException: If file type is unsupported, OCR fails, or processing fails
    """
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file type. Please upload an image file (PNG, JPG, JPEG, or WEBP).",
        )

    try:
        contents = await file.read()
        ocr_service = EasyOCRService()
        ocr_text = ocr_service.extract_text(contents, filename=file.filename or "label.png")
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid image file: {str(e)}",
        )
    except ImportError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OCR service is not properly configured. Please contact support.",
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OCR processing failed: {str(e)}",
        )

    nlp_result = process_text(ocr_text)
    score_prediction = predict_score(nlp_result["cleaned_text"])
    health_risk_prediction = predict_health_risk(nlp_result["cleaned_text"])
    rag_result = query_knowledge_base(
        nlp_result["cleaned_text"],
        score_prediction,
        health_risk_prediction,
    )
    xai_result = explain_result(score_prediction, health_risk_prediction, rag_result)

    response = {
        "status": "success",
        "message": "Food label analyzed successfully.",
        "ocr_text": ocr_text,
        "nlp": nlp_result,
        "score_prediction": score_prediction,
        "health_risk_prediction": health_risk_prediction,
        "rag": rag_result,
        "xai": xai_result,
        "final_result": {
            "score": score_prediction["score"],
            "risk_level": health_risk_prediction["risk_level"],
            "risk_score": health_risk_prediction["risk_score"],
            "summary": xai_result["interpretation"],
            "ingredients": nlp_result["ingredients"],
        },
    }
    return response
