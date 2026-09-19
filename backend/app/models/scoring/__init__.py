from __future__ import annotations


def predict_score(ingredients_text: str) -> dict:
    """Placeholder score-model interface.

    Member 2 will plug in the trained score prediction model here.
    """
    score = 72
    return {
        "score": score,
        "label": "moderate",
        "details": "Mock score prediction. Replace with trained score model output.",
        "ingredients_text": ingredients_text,
    }
