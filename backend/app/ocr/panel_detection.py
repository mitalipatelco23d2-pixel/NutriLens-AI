from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


PANEL_KEYWORDS = {
    "nutrition", "energy", "fat", "saturated", "trans", "cholesterol",
    "sodium", "carbohydrate", "sugar", "fibre", "fiber", "protein",
}


class PositionedWord(Protocol):
    text: str
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class PanelCandidate:
    image: Image.Image
    bounds: tuple[int, int, int, int]
    score: float
    keyword_count: int
    grid_density: float


def _keyword_count(words: Iterable[PositionedWord], bounds: tuple[int, int, int, int]) -> int:
    left, top, right, bottom = bounds
    found: set[str] = set()
    for word in words:
        center_x = word.left + word.width / 2
        center_y = word.top + word.height / 2
        normalized = "".join(character for character in word.text.casefold() if character.isalpha())
        if left <= center_x <= right and top <= center_y <= bottom:
            for keyword in PANEL_KEYWORDS:
                if normalized == keyword or (
                    len(keyword) >= 5 and len(normalized) >= 5 and normalized[:5] == keyword[:5]
                ):
                    found.add(keyword)
    return len(found)


def detect_nutrition_panels(
    image: Image.Image,
    words: Iterable[PositionedWord] = (),
    limit: int = 3,
) -> list[PanelCandidate]:
    """Detect light grid-like rectangular regions using scale-relative morphology."""
    gray = np.asarray(ImageOps.grayscale(image))
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12
    )
    height, width = gray.shape
    horizontal_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(20, width // 35), 1)
    )
    vertical_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, max(20, height // 60))
    )
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, horizontal_kernel)
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vertical_kernel)
    grid = cv2.bitwise_or(horizontal, vertical)
    grid = cv2.dilate(
        grid, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)), iterations=2
    )
    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = width * height
    candidates: list[PanelCandidate] = []
    for contour in contours:
        x, y, crop_width, crop_height = cv2.boundingRect(contour)
        area = crop_width * crop_height
        area_ratio = area / image_area
        aspect = crop_width / crop_height
        if not (0.012 <= area_ratio <= 0.45):
            continue
        if crop_width < 180 or crop_height < 180 or not (0.25 <= aspect <= 4.0):
            continue
        region = grid[y : y + crop_height, x : x + crop_width]
        density = cv2.countNonZero(region) / area
        if density < 0.035:
            continue
        padding_x = max(8, round(crop_width * 0.035))
        padding_y = max(8, round(crop_height * 0.035))
        bounds = (
            max(0, x - padding_x),
            max(0, y - padding_y),
            min(width, x + crop_width + padding_x),
            min(height, y + crop_height + padding_y),
        )
        keywords = _keyword_count(words, bounds)
        aspect_bonus = 12 if 0.5 <= aspect <= 2.0 else 0
        compactness = keywords / max(area_ratio, 0.01)
        score = keywords * 28 + density * 100 + compactness * 0.35 + aspect_bonus
        if keywords < 2 and density < 0.12:
            continue
        crop = image.crop(bounds)
        candidates.append(
            PanelCandidate(crop, bounds, round(score, 3), keywords, round(density, 4))
        )
    return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)[:limit]


def table_preprocessing_variants(
    panel: Image.Image,
    max_pixels: int,
) -> list[tuple[str, Image.Image, int]]:
    """Return three bounded variants: enhanced gray, Otsu, and adaptive threshold."""
    gray = ImageOps.grayscale(panel)
    safe_scale = (max_pixels / max(gray.width * gray.height, 1)) ** 0.5
    scale = max(1.0, min(3.0, 1500 / min(gray.size), safe_scale))
    if scale > 1:
        gray = gray.resize(
            (round(gray.width * scale), round(gray.height * scale)), Image.Resampling.LANCZOS
        )
    enhanced = ImageOps.autocontrast(gray, cutoff=1)
    enhanced = ImageEnhance.Contrast(enhanced).enhance(1.2).filter(ImageFilter.SHARPEN)
    array = np.asarray(enhanced)
    _, otsu = cv2.threshold(array, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        array, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 11
    )
    return [
        ("panel_gray", enhanced, 6),
        ("panel_otsu", Image.fromarray(otsu), 6),
        ("panel_adaptive", Image.fromarray(adaptive), 11),
    ]
