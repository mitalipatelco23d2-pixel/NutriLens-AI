from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


@dataclass(frozen=True)
class NormalizedBounds:
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min

    @property
    def center_x(self) -> float:
        return (self.x_min + self.x_max) / 2

    @property
    def center_y(self) -> float:
        return (self.y_min + self.y_max) / 2


@dataclass(frozen=True)
class NormalizedToken:
    """Engine-independent OCR token in its active image/crop coordinate space."""

    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int
    block: int = 0
    paragraph: int = 0
    line: int = 0

    @property
    def x_min(self) -> int:
        return self.left

    @property
    def y_min(self) -> int:
        return self.top

    @property
    def x_max(self) -> int:
        return self.left + self.width

    @property
    def y_max(self) -> int:
        return self.top + self.height

    @property
    def center_x(self) -> float:
        return (self.x_min + self.x_max) / 2

    @property
    def center_y(self) -> float:
        return (self.y_min + self.y_max) / 2


def normalize_polygon(
    polygon: Iterable[Sequence[float]],
    *,
    scale_x: float = 1.0,
    scale_y: float = 1.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> NormalizedBounds:
    """Convert an OCR quadrilateral into one explicit coordinate space."""
    points = list(polygon)
    if len(points) < 2 or scale_x <= 0 or scale_y <= 0:
        raise ValueError("invalid OCR polygon transform")
    try:
        xs = [float(point[0]) * scale_x + offset_x for point in points]
        ys = [float(point[1]) * scale_y + offset_y for point in points]
    except (IndexError, TypeError, ValueError) as exc:
        raise ValueError("invalid OCR polygon") from exc
    bounds = NormalizedBounds(min(xs), min(ys), max(xs), max(ys))
    if bounds.width <= 0 or bounds.height <= 0:
        raise ValueError("OCR polygon has no area")
    return bounds
