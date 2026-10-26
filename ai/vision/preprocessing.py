"""Selective OpenCV preprocessing; the original image is never modified."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import cv2
import numpy as np

from ai.food_understanding.schemas import (
    PreprocessingResult,
    PreprocessProfile,
    ProcessingStep,
)


@dataclass(frozen=True)
class ProcessedImage:
    image: np.ndarray
    metadata: PreprocessingResult


def rotate_cardinal(image: np.ndarray, degrees: int) -> np.ndarray:
    normalized = degrees % 360
    if normalized == 0:
        return image.copy()
    if normalized == 90:
        return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    if normalized == 180:
        return cv2.rotate(image, cv2.ROTATE_180)
    if normalized == 270:
        return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
    raise ValueError("Cardinal rotation must be 0, 90, 180, or 270 degrees.")


def estimate_skew_angle(image: np.ndarray) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    points = np.column_stack(np.where(binary > 0))
    if len(points) < 25:
        return 0.0
    angle = float(cv2.minAreaRect(points[:, ::-1].astype(np.float32))[-1])
    if angle < -45:
        angle = 90 + angle
    elif angle > 45:
        angle = angle - 90
    return max(-15.0, min(15.0, angle))


def deskew(image: np.ndarray, *, minimum_angle: float = 0.3) -> tuple[np.ndarray, float, bool]:
    angle = estimate_skew_angle(image)
    if abs(angle) < minimum_angle:
        return image.copy(), angle, False
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    corrected = cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )
    return corrected, angle, True


def _order_points(points: np.ndarray) -> np.ndarray:
    ordered = np.zeros((4, 2), dtype=np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(differences)]
    ordered[3] = points[np.argmax(differences)]
    return ordered


def four_point_transform(image: np.ndarray, points: np.ndarray) -> np.ndarray:
    top_left, top_right, bottom_right, bottom_left = _order_points(points)
    width = int(
        max(
            float(np.linalg.norm(bottom_right - bottom_left)),
            float(np.linalg.norm(top_right - top_left)),
        )
    )
    height = int(
        max(
            float(np.linalg.norm(top_right - bottom_right)),
            float(np.linalg.norm(top_left - bottom_left)),
        )
    )
    if width < 2 or height < 2:
        raise ValueError("Perspective quadrilateral is too small.")
    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(
        np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32),
        destination,
    )
    return cv2.warpPerspective(image, matrix, (width, height))


def correct_perspective(
    image: np.ndarray, *, minimum_area_ratio: float = 0.25
) -> tuple[np.ndarray, bool, float, str]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 60, 180)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    image_area = float(image.shape[0] * image.shape[1])
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:10]:
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        area_ratio = cv2.contourArea(contour) / image_area
        if len(polygon) == 4 and area_ratio >= minimum_area_ratio and cv2.isContourConvex(polygon):
            transformed = four_point_transform(image, polygon.reshape(4, 2).astype(np.float32))
            return transformed, True, min(0.9, area_ratio), "plausible rectangular region"
    return image.copy(), False, 0.0, "no sufficiently large rectangular region"


def _resize_max_side(image: np.ndarray, maximum_side: int) -> tuple[np.ndarray, bool]:
    height, width = image.shape[:2]
    long_side = max(height, width)
    if long_side <= maximum_side:
        return image, False
    scale = maximum_side / long_side
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), True


def _resize_for_ocr(
    image: np.ndarray, minimum_short_side: int = 900, maximum_side: int = 1800
) -> tuple[np.ndarray, bool]:
    height, width = image.shape[:2]
    short_side = min(height, width)
    if short_side >= minimum_short_side:
        return image, False
    scale = min(3.0, minimum_short_side / short_side, maximum_side / max(height, width))
    if scale <= 1.0:
        return image, False
    return cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC), True


def preprocess(
    image: np.ndarray, profile: PreprocessProfile, *, maximum_ocr_side: int = 1800
) -> ProcessedImage:
    started = time.perf_counter()
    working = image.copy()
    steps: list[ProcessingStep] = []

    if profile in {
        PreprocessProfile.OCR_LABEL,
        PreprocessProfile.NUTRITION_TABLE,
        PreprocessProfile.INGREDIENT_LIST,
    }:
        working, downscaled = _resize_max_side(working, maximum_ocr_side)
        steps.append(
            ProcessingStep(
                name="bounded_resize",
                applied=downscaled,
                reason="long side exceeded OCR inference bound"
                if downscaled
                else "image already within OCR inference bound",
                parameters={"maximum_side": maximum_ocr_side},
            )
        )
        corrected, applied, confidence, reason = correct_perspective(working)
        working = corrected
        steps.append(
            ProcessingStep(
                name="perspective_correction",
                applied=applied,
                reason=reason,
                parameters={"confidence": round(confidence, 4)},
            )
        )
        working, angle, skew_applied = deskew(working)
        steps.append(
            ProcessingStep(
                name="deskew",
                applied=skew_applied,
                reason="estimated text skew" if skew_applied else "skew below safe threshold",
                parameters={"angle_degrees": round(angle, 3)},
            )
        )
        working, resized = _resize_for_ocr(working, maximum_side=maximum_ocr_side)
        steps.append(
            ProcessingStep(
                name="upscale",
                applied=resized,
                reason="short side below OCR target"
                if resized
                else "resolution already sufficient",
            )
        )
        gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY) if working.ndim == 3 else working.copy()
        denoised = cv2.fastNlMeansDenoising(gray, None, 7, 7, 21)
        steps.append(ProcessingStep(name="denoise", applied=True, reason="OCR text profile"))
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(denoised)
        steps.append(
            ProcessingStep(name="clahe", applied=True, reason="local contrast enhancement")
        )
        if profile == PreprocessProfile.NUTRITION_TABLE:
            working = cv2.adaptiveThreshold(
                clahe, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
            )
            steps.append(
                ProcessingStep(name="adaptive_threshold", applied=True, reason="table text profile")
            )
        else:
            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]], dtype=np.float32)
            working = cv2.filter2D(clahe, -1, kernel)
            steps.append(ProcessingStep(name="sharpen", applied=True, reason="label text profile"))
    elif profile == PreprocessProfile.BARCODE:
        gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
        working = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(gray)
        steps.append(ProcessingStep(name="grayscale_clahe", applied=True, reason="barcode profile"))
    elif profile in {PreprocessProfile.GENERAL_PRODUCT, PreprocessProfile.MEAL}:
        if float(np.mean(cv2.cvtColor(working, cv2.COLOR_BGR2GRAY))) < 65:
            lab = cv2.cvtColor(working, cv2.COLOR_BGR2LAB)
            luminance, channel_a, channel_b = cv2.split(lab)
            luminance = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(luminance)
            working = cv2.cvtColor(cv2.merge((luminance, channel_a, channel_b)), cv2.COLOR_LAB2BGR)
            steps.append(
                ProcessingStep(name="low_light_clahe", applied=True, reason="low mean luminance")
            )
        else:
            steps.append(
                ProcessingStep(name="low_light_clahe", applied=False, reason="lighting acceptable")
            )
    else:  # pragma: no cover - enum exhaustiveness guard
        raise ValueError(f"Unsupported preprocessing profile: {profile}")

    if not math.isfinite(float(np.mean(working))):
        raise ValueError("Preprocessing produced invalid pixel values.")
    height, width = working.shape[:2]
    metadata = PreprocessingResult(
        profile=profile,
        width=width,
        height=height,
        steps=steps,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )
    return ProcessedImage(image=working, metadata=metadata)
