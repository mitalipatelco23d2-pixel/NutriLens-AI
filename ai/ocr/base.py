"""Shared OCR adapter protocol and output helpers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol, cast

import numpy as np

from ai.food_understanding.schemas import Box, OCRAttempt, OCRLine


class OCREngine(Protocol):
    name: str

    def recognize(self, image: np.ndarray, languages: list[str]) -> OCRAttempt: ...


def polygon_to_box(points: object) -> Box | None:
    try:
        rows = list(cast(Iterable[Any], points))
        xs = [float(row[0]) for row in rows]
        ys = [float(row[1]) for row in rows]
    except (TypeError, ValueError, IndexError):
        return None
    if not xs or not ys:
        return None
    return Box(x=min(xs), y=min(ys), width=max(xs) - min(xs), height=max(ys) - min(ys))


def aggregate_confidence(lines: list[OCRLine]) -> float | None:
    confidences = [line.confidence for line in lines if line.confidence is not None]
    if not confidences:
        return None
    weights = [max(1, len(line.text)) for line in lines if line.confidence is not None]
    return sum(value * weight for value, weight in zip(confidences, weights, strict=True)) / sum(
        weights
    )
