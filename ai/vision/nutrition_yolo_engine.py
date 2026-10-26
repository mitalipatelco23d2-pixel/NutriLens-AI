"""Custom fine-tuned nutrition-table detector with bounded cardinal fallback."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ai.food_understanding.config import R3Config
from ai.food_understanding.schemas import Box, ModelMetadata
from ai.vision.preprocessing import rotate_cardinal
from ai.vision.yolo_engine import YOLODetection


@dataclass(frozen=True)
class NutritionYOLOInference:
    detections: list[YOLODetection]
    elapsed_ms: float
    error_code: str | None
    metadata: ModelMetadata
    rotation_degrees: int


class NutritionYOLOEngine:
    """Run the R3 custom model first and try cardinal rotations only on a miss."""

    def __init__(self, config: R3Config) -> None:
        self.config = config
        self._model: Any = None
        self._load_error: str | None = None
        self._device = "cpu"
        self._resolved_path: Path | None = None
        self._checksum: str | None = None

    def _resolve_model(self) -> Path | None:
        configured = Path(self.config.nutrition_yolo_model)
        candidates = (configured, self.config.model_cache / configured.name)
        return next((candidate for candidate in candidates if candidate.is_file()), None)

    def _load(self) -> None:
        if self._model is not None or self._load_error is not None:
            return
        model_path = self._resolve_model()
        if model_path is None:
            self._load_error = "MODEL_NOT_CACHED"
            return
        try:
            registry_path = (
                Path(__file__).resolve().parents[1] / "model-registry" / "r3-models.json"
            )
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            model_record = next(
                record
                for record in registry["models"]
                if record.get("model_id") == "nutrilens-r3-nutrition-yolo11n-v1"
            )
            expected_bytes = int(model_record["weights_bytes"])
            expected_digest = str(model_record["checksum"])
            if model_path.stat().st_size != expected_bytes:
                raise ValueError("MODEL_SIZE_MISMATCH")
            actual_digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
            if not hmac.compare_digest(actual_digest, expected_digest):
                raise ValueError("MODEL_DIGEST_MISMATCH")

            import torch
            from ultralytics import YOLO

            requested = self.config.validated_device()
            cuda_available = bool(torch.cuda.is_available())
            self._device = "cuda" if requested in {"auto", "cuda"} and cuda_available else "cpu"
            self._model = YOLO(str(model_path))
            self._resolved_path = model_path
            self._checksum = actual_digest
        except Exception as exc:  # pragma: no cover - optional runtime boundary
            self._load_error = type(exc).__name__

    def infer(self, image: np.ndarray) -> NutritionYOLOInference:
        started = time.perf_counter()
        self._load()
        if self._model is None:
            return NutritionYOLOInference(
                detections=[],
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error_code=f"NUTRITION_YOLO_UNAVAILABLE:{self._load_error or 'not_loaded'}",
                metadata=self.metadata(loaded=False),
                rotation_degrees=0,
            )
        try:
            detections = self._predict(image, rotation=0)
            selected_rotation = 0
            # Cardinal retries are bounded and only paid when the upright pass misses.
            if not detections:
                candidates = [
                    (rotation, self._predict(image, rotation=rotation))
                    for rotation in (90, 180, 270)
                ]
                selected_rotation, detections = max(
                    candidates,
                    key=lambda item: max(
                        (detection.confidence for detection in item[1]), default=-1.0
                    ),
                )
            return NutritionYOLOInference(
                detections=detections,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error_code=None,
                metadata=self.metadata(loaded=True),
                rotation_degrees=selected_rotation,
            )
        except Exception as exc:  # pragma: no cover - optional runtime boundary
            return NutritionYOLOInference(
                detections=[],
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error_code=f"NUTRITION_YOLO_RUNTIME_ERROR:{type(exc).__name__}",
                metadata=self.metadata(loaded=True),
                rotation_degrees=0,
            )

    def _predict(self, image: np.ndarray, *, rotation: int) -> list[YOLODetection]:
        source = rotate_cardinal(image, rotation) if rotation else image
        result = self._model.predict(
            source=source,
            conf=self.config.nutrition_yolo_confidence,
            iou=self.config.nutrition_yolo_nms_iou,
            max_det=self.config.nutrition_yolo_max_detections,
            imgsz=self.config.nutrition_yolo_image_size,
            device=self._device,
            verbose=False,
        )[0]
        detections: list[YOLODetection] = []
        height, width = image.shape[:2]
        for xyxy, confidence, class_id in zip(
            result.boxes.xyxy.cpu().numpy(),
            result.boxes.conf.cpu().numpy(),
            result.boxes.cls.cpu().numpy(),
            strict=True,
        ):
            source_box = (
                float(xyxy[0]),
                float(xyxy[1]),
                float(xyxy[2]),
                float(xyxy[3]),
            )
            x1, y1, x2, y2 = _map_box_to_original(
                source_box,
                rotation=rotation,
                original_width=width,
                original_height=height,
            )
            detections.append(
                YOLODetection(
                    label="nutrition_table",
                    confidence=float(confidence),
                    bounding_box=Box(x=x1, y=y1, width=x2 - x1, height=y2 - y1),
                    class_id=int(class_id),
                )
            )
        return detections

    def metadata(self, *, loaded: bool) -> ModelMetadata:
        path = self._resolved_path or self._resolve_model()
        return ModelMetadata(
            model_name="NutriLens nutrition-table YOLO11n v1",
            model_version="r3-nutrition-yolo11n-v1",
            source="Custom fine-tune on reviewed Open Food Facts nutrition-table boxes",
            task="nutrition-table region detection",
            framework="Ultralytics/PyTorch",
            local_file=str(path) if path is not None else None,
            checksum=self._checksum,
            device=self._device,
            license="AGPL-3.0 model runtime; dataset records retain Open Food Facts source terms",
            training_status="CUSTOM_FINE_TUNED",
            loaded=loaded,
        )


def _map_box_to_original(
    box: tuple[float, float, float, float],
    *,
    rotation: int,
    original_width: int,
    original_height: int,
) -> tuple[float, float, float, float]:
    """Map continuous xyxy bounds from a cardinally rotated image to the original."""
    x1, y1, x2, y2 = box
    normalized = rotation % 360
    if normalized == 0:
        mapped = (x1, y1, x2, y2)
    elif normalized == 90:
        mapped = (y1, original_height - x2, y2, original_height - x1)
    elif normalized == 180:
        mapped = (
            original_width - x2,
            original_height - y2,
            original_width - x1,
            original_height - y1,
        )
    elif normalized == 270:
        mapped = (original_width - y2, x1, original_width - y1, x2)
    else:
        raise ValueError("Cardinal rotation must be 0, 90, 180, or 270 degrees.")
    mx1, my1, mx2, my2 = mapped
    return (
        max(0.0, min(float(original_width), mx1)),
        max(0.0, min(float(original_height), my1)),
        max(0.0, min(float(original_width), mx2)),
        max(0.0, min(float(original_height), my2)),
    )
