from __future__ import annotations


def explain_result(score_prediction: dict, risk_prediction: dict, rag_context: dict) -> dict:
    """Placeholder XAI interface.

    Member 5 will replace this with the explainability module output.
    """
    return {
        "feature_importance": {
            "score_model": [
                {"feature": "ingredients", "importance": 0.75},
                {"feature": "nutrition_profile", "importance": 0.25},
            ],
            "risk_model": [
                {"feature": "sugar", "importance": 0.7},
                {"feature": "sodium", "importance": 0.3},
            ],
        },
        "interpretation": "Mock explanation generated for the result pipeline.",
        "score_prediction": score_prediction,
        "risk_prediction": risk_prediction,
        "rag_context": rag_context,
    }
