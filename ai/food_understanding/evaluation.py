"""R3 evaluation helpers; metrics require externally supplied real ground truth."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ErrorRates:
    character_error_rate: float
    word_error_rate: float


def levenshtein(reference: list[str], prediction: list[str]) -> int:
    previous = list(range(len(prediction) + 1))
    for row, reference_item in enumerate(reference, start=1):
        current = [row]
        for column, prediction_item in enumerate(prediction, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[column] + 1,
                    previous[column - 1] + (reference_item != prediction_item),
                )
            )
        previous = current
    return previous[-1]


def ocr_error_rates(reference: str, prediction: str) -> ErrorRates:
    reference_characters = list(reference)
    reference_words = reference.split()
    return ErrorRates(
        character_error_rate=levenshtein(reference_characters, list(prediction))
        / max(1, len(reference_characters)),
        word_error_rate=levenshtein(reference_words, prediction.split())
        / max(1, len(reference_words)),
    )


def intersection_over_union(
    reference: tuple[float, float, float, float],
    prediction: tuple[float, float, float, float],
) -> float:
    ref_x, ref_y, ref_width, ref_height = reference
    pred_x, pred_y, pred_width, pred_height = prediction
    x1 = max(ref_x, pred_x)
    y1 = max(ref_y, pred_y)
    x2 = min(ref_x + ref_width, pred_x + pred_width)
    y2 = min(ref_y + ref_height, pred_y + pred_height)
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = ref_width * ref_height + pred_width * pred_height - intersection
    return intersection / union if union > 0 else 0.0
