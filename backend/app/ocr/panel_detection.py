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


def _ordered_quad(points: np.ndarray) -> np.ndarray:
    """Return quadrilateral points as top-left, top-right, bottom-right, bottom-left."""
    points = points.reshape(4, 2).astype("float32")
    ordered = np.zeros((4, 2), dtype="float32")
    coordinate_sum = points.sum(axis=1)
    coordinate_difference = np.diff(points, axis=1).reshape(-1)
    ordered[0] = points[np.argmin(coordinate_sum)]
    ordered[2] = points[np.argmax(coordinate_sum)]
    ordered[1] = points[np.argmin(coordinate_difference)]
    ordered[3] = points[np.argmax(coordinate_difference)]
    return ordered


def _foreground_binary(image: Image.Image) -> np.ndarray:
    gray = np.asarray(ImageOps.grayscale(image))
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if cv2.countNonZero(binary) > binary.size / 2:
        binary = cv2.bitwise_not(binary)
    return binary


def _horizontal_line_centers(image: Image.Image) -> list[int]:
    """Find long table separators after a candidate has been rectified."""
    foreground = _foreground_binary(image)
    height, width = foreground.shape
    kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (max(30, width // 6), 1)
    )
    horizontal = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, kernel)
    projection = np.count_nonzero(horizontal, axis=1)
    rows = np.flatnonzero(projection >= max(40, round(width * 0.6)))
    if not len(rows):
        return []

    bands: list[tuple[int, int]] = []
    start = previous = int(rows[0])
    for raw_row in rows[1:]:
        row = int(raw_row)
        if row > previous + 2:
            bands.append((start, previous))
            start = row
        previous = row
    bands.append((start, previous))
    return [round((top + bottom) / 2) for top, bottom in bands]


def table_row_bounds(image: Image.Image) -> list[tuple[int, int]]:
    """Return plausible row bands bounded by long, repeated table separators."""
    centers = _horizontal_line_centers(image)
    minimum_gap = max(14, round(image.height * 0.035))
    maximum_gap = max(minimum_gap + 1, round(image.height * 0.2))
    return [
        (top, bottom)
        for top, bottom in zip(centers, centers[1:])
        if minimum_gap <= bottom - top <= maximum_gap
    ]


def _perspective_panel_candidates(
    image: Image.Image,
    words: Iterable[PositionedWord],
) -> list[PanelCandidate]:
    """Rectify closed quadrilateral tables before OCRing their individual rows."""
    gray = np.asarray(ImageOps.grayscale(image))
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 12
    )
    contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = gray.size
    candidates: list[PanelCandidate] = []
    for contour in contours:
        contour_area = cv2.contourArea(contour)
        area_ratio = contour_area / image_area
        if not (0.008 <= area_ratio <= 0.45):
            continue
        x, y, width, height = cv2.boundingRect(contour)
        if width < 180 or height < 180:
            continue
        extent = contour_area / max(width * height, 1)
        if extent < 0.6:
            continue
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue

        source = _ordered_quad(polygon)
        target_width = round(
            max(
                np.linalg.norm(source[1] - source[0]),
                np.linalg.norm(source[2] - source[3]),
            )
        )
        target_height = round(
            max(
                np.linalg.norm(source[3] - source[0]),
                np.linalg.norm(source[2] - source[1]),
            )
        )
        if target_width < 180 or target_height < 180:
            continue
        aspect = target_width / target_height
        if not (0.35 <= aspect <= 4.0):
            continue
        destination = np.float32(
            [
                [0, 0],
                [target_width - 1, 0],
                [target_width - 1, target_height - 1],
                [0, target_height - 1],
            ]
        )
        border = int(np.median(gray[[0, 0, -1, -1], [0, -1, -1, 0]]))
        rectified = cv2.warpPerspective(
            gray,
            cv2.getPerspectiveTransform(source, destination),
            (target_width, target_height),
            borderValue=border,
        )
        panel = Image.fromarray(rectified)
        row_bounds = table_row_bounds(panel)
        if len(row_bounds) < 4:
            continue
        bounds = (x, y, x + width, y + height)
        keywords = _keyword_count(words, bounds)
        density = cv2.countNonZero(binary[y : y + height, x : x + width]) / max(
            width * height, 1
        )
        score = len(row_bounds) * 30 + keywords * 28 + extent * 50
        candidates.append(
            PanelCandidate(
                panel,
                bounds,
                round(score, 3),
                keywords,
                round(density, 4),
            )
        )
    return candidates


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
    candidates: list[PanelCandidate] = _perspective_panel_candidates(image, words)
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
