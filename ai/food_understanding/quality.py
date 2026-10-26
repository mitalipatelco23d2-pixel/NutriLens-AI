"""Documented deterministic image-quality measurements."""

from __future__ import annotations

import time
from typing import Literal

import cv2
import numpy as np

from ai.food_understanding.config import R3Config
from ai.food_understanding.schemas import ConfidenceLevel, ImageQuality


def assess_image_quality(image: np.ndarray, config: R3Config) -> tuple[ImageQuality, float]:
    started = time.perf_counter()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    contrast = float(gray.std())
    height, width = gray.shape

    warnings: list[str] = []
    blurry = blur_score < config.blur_threshold
    if blurry:
        warnings.append("Image may be too blurry for reliable text recognition.")
    if brightness < config.dark_threshold:
        brightness_status: Literal["UNDEREXPOSED", "ACCEPTABLE", "OVEREXPOSED"] = "UNDEREXPOSED"
        warnings.append("Image is underexposed; use brighter, even lighting.")
    elif brightness > config.bright_threshold:
        brightness_status = "OVEREXPOSED"
        warnings.append("Image is overexposed; reduce glare or direct light.")
    else:
        brightness_status = "ACCEPTABLE"
    low_contrast = contrast < config.contrast_threshold
    if low_contrast:
        warnings.append("Image has low contrast; keep label text in focus.")
    resolution_ok = min(height, width) >= max(config.min_image_dimension, 300)
    if not resolution_ok:
        warnings.append("Resolution is valid but below the recommended OCR size.")

    failed_checks = sum(
        (blurry, brightness_status != "ACCEPTABLE", low_contrast, not resolution_ok)
    )
    level = (
        ConfidenceLevel.HIGH
        if failed_checks == 0
        else ConfidenceLevel.MEDIUM
        if failed_checks == 1
        else ConfidenceLevel.LOW
        if failed_checks == 2
        else ConfidenceLevel.UNRELIABLE
    )
    result = ImageQuality(
        blur_score=blur_score,
        blur_status="BLURRY" if blurry else "ACCEPTABLE",
        brightness_score=brightness,
        brightness_status=brightness_status,
        contrast_score=contrast,
        contrast_status="LOW" if low_contrast else "ACCEPTABLE",
        resolution_ok=resolution_ok,
        quality_status=level,
        retry_recommended=failed_checks >= 2,
        warnings=warnings,
    )
    return result, (time.perf_counter() - started) * 1000
