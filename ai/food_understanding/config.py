"""Environment-backed, CPU-first R3 configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class R3Config:
    max_upload_bytes: int = int(os.getenv("R3_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    min_image_dimension: int = int(os.getenv("R3_MIN_IMAGE_DIMENSION", "64"))
    max_image_dimension: int = int(os.getenv("R3_MAX_IMAGE_DIMENSION", "12000"))
    max_image_pixels: int = int(os.getenv("R3_MAX_IMAGE_PIXELS", "20000000"))
    max_product_pixels: int = int(os.getenv("R3_MAX_PRODUCT_PIXELS", "40000000"))
    scan_timeout_seconds: float = float(os.getenv("R3_SCAN_TIMEOUT_SECONDS", "120"))

    blur_threshold: float = float(os.getenv("R3_BLUR_THRESHOLD", "80"))
    dark_threshold: float = float(os.getenv("R3_DARK_THRESHOLD", "45"))
    bright_threshold: float = float(os.getenv("R3_BRIGHT_THRESHOLD", "225"))
    contrast_threshold: float = float(os.getenv("R3_CONTRAST_THRESHOLD", "28"))
    ocr_min_confidence: float = float(os.getenv("R3_OCR_MIN_CONFIDENCE", "0.55"))
    ocr_min_characters: int = int(os.getenv("R3_OCR_MIN_CHARACTERS", "4"))

    device: Literal["auto", "cpu", "cuda"] = os.getenv(  # type: ignore[assignment]
        "R3_DEVICE", "auto"
    ).lower()
    allow_model_downloads: bool = _bool_env("R3_ALLOW_MODEL_DOWNLOADS")
    trocr_enabled: bool = _bool_env("R3_TROCR_ENABLED")
    model_cache: Path = Path(os.getenv("R3_MODEL_CACHE", ".model-cache/r3"))
    yolo_model: str = os.getenv("R3_YOLO_MODEL", "yolo11n.pt")
    yolo_confidence: float = float(os.getenv("R3_YOLO_CONFIDENCE", "0.25"))
    yolo_image_size: int = int(os.getenv("R3_YOLO_IMAGE_SIZE", "640"))
    nutrition_yolo_model: str = os.getenv(
        "R3_NUTRITION_YOLO_MODEL",
        ".model-cache/r3/custom/nutrition-table-yolo11n-v1.pt",
    )
    nutrition_yolo_confidence: float = float(os.getenv("R3_NUTRITION_YOLO_CONFIDENCE", "0.30"))
    nutrition_yolo_image_size: int = int(os.getenv("R3_NUTRITION_YOLO_IMAGE_SIZE", "640"))
    nutrition_yolo_nms_iou: float = float(os.getenv("R3_NUTRITION_YOLO_NMS_IOU", "0.50"))
    nutrition_yolo_max_detections: int = int(os.getenv("R3_NUTRITION_YOLO_MAX_DETECTIONS", "3"))
    ocr_max_image_side: int = int(os.getenv("R3_OCR_MAX_IMAGE_SIDE", "1800"))

    def validated_device(self) -> Literal["auto", "cpu", "cuda"]:
        if self.device not in {"auto", "cpu", "cuda"}:
            return "cpu"
        return self.device


DEFAULT_CONFIG = R3Config()
