"""NutriLens AI
Complete AI Analysis Pipeline

Flow:
OCR text
    ↓
M1 + M2 NLP
    ↓
Health Risk ML
    ↓
XAI
    ↓
Health Score
    ↓
Recommendations
"""

from app.nlp.nlp_service import analyze_label_text
from app.models.health_risk.risk_service import predict_from_nlp_result
from app.xai.xai_service import analyze_with_xai
from app.models.scoring.health_score_service import calculate_health_score
from app.models.scoring.recommendation_service import generate_recommendations

def analyze_food_label(ocr_text, user_goal="general_health"):
    """
    Run the complete NutriLens AI analysis pipeline.
    """

    if not ocr_text or not isinstance(ocr_text, str):
        raise ValueError("OCR text must be a non-empty string.")

    # --------------------------------------------------
    # STEP 1: M1 + M2 NLP
    # --------------------------------------------------
    nlp_result = analyze_label_text(ocr_text)

    # --------------------------------------------------
    # STEP 2: Health Risk ML
    # --------------------------------------------------
    risk_result = predict_from_nlp_result(nlp_result)

    # --------------------------------------------------
    # STEP 3: XAI
    # --------------------------------------------------
    ingredient_text = ", ".join(
        nlp_result.get("normalized_ingredients", [])
    )

    xai_result = analyze_with_xai(
        ingredient_text,
        top_n=5
    )

    # --------------------------------------------------
    # STEP 4: Health Score
    # --------------------------------------------------
    health_score_result = calculate_health_score(
        risk_prediction=risk_result,
        nutrition=nlp_result.get("nutrition", {}),
        allergens=nlp_result.get("allergens", []),
        additives=nlp_result.get("additives", [])
    )

    # --------------------------------------------------
    # STEP 5: Recommendations
    # --------------------------------------------------
    recommendation_result = generate_recommendations(
        health_score=health_score_result["health_score"],
        risk_level=risk_result["risk_level"],
        nutrition=nlp_result.get("nutrition", {}),
        allergens=nlp_result.get("allergens", []),
        additives=nlp_result.get("additives", []),
        user_goal=user_goal
    )

    # --------------------------------------------------
    # FINAL RESULT
    # --------------------------------------------------
    return {
        "nlp": nlp_result,
        "health_risk": risk_result,
        "xai": xai_result,
        "health_score": health_score_result,
        "recommendations": recommendation_result
    }
