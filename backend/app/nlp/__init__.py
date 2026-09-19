from __future__ import annotations


def process_text(ocr_text: str) -> dict:
    """Mock NLP layer interface.

    Member 1 will replace this with the real NLP preprocessing and ingredient
    extraction pipeline.
    """
    cleaned_text = " ".join(ocr_text.split())
    return {
        "raw_text": ocr_text,
        "cleaned_text": cleaned_text,
        "normalized_text": cleaned_text.lower(),
        "ingredients": cleaned_text[:200] if cleaned_text else "",
    }
