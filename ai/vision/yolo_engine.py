"""Lazy YOLO11 wrapper for pretrained COCO inference only."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ai.food_understanding.config import R3Config
from ai.food_understanding.schemas import Box, ModelMetadata


@dataclass(frozen=True)
class YOLODetection:
    label: str
    confidence: float
    bounding_box: Box
    class_id: int


@dataclass(frozen=True)
class YOLOInference:
    detections: list[YOLODetection]
    elapsed_ms: float
    error_code: str | None
    metadata: ModelMetadata


class YOLO11Engine:
    """Uses Ultralytics YOLO11n; it is PRETRAINED, never NutriLens fine-tuned."""

    def __init__(self, config: R3Config) -> None:
        self.config = config
        self._model: Any = None
        self._load_error: str | None = None
        self._device = "cpu"

    def _resolve_model(self) -> str | None:
        configured = Path(self.config.yolo_model)
        cache_candidate = self.config.model_cache / configured.name
        if configured.is_file():
            return str(configured)
        if cache_candidate.is_file():
            return str(cache_candidate)
        return self.config.yolo_model if self.config.allow_model_downloads else None

    def _load(self) -> None:
        if self._model is not None or self._load_error is not None:
            return
        model_source = self._resolve_model()
        if model_source is None:
            self._load_error = "MODEL_NOT_CACHED"
            return
        try:
            import torch
            from ultralytics import YOLO

            requested = self.config.validated_device()
            cuda_available = bool(torch.cuda.is_available())
            self._device = "cuda" if requested in {"auto", "cuda"} and cuda_available else "cpu"
            self._model = YOLO(model_source)
        except Exception as exc:
            self._load_error = type(exc).__name__

    def infer(self, image: np.ndarray) -> YOLOInference:
        started = time.perf_counter()
        self._load()
        if self._model is None:
            return YOLOInference(
                detections=[],
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error_code=f"YOLO_UNAVAILABLE:{self._load_error or 'not_loaded'}",
                metadata=self.metadata(loaded=False),
            )
        try:
            results = self._model.predict(
                source=image,
                conf=self.config.yolo_confidence,
                imgsz=self.config.yolo_image_size,
                device=self._device,
                verbose=False,
            )
            detections: list[YOLODetection] = []
            for result in results:
                names = result.names
                boxes = result.boxes
                for xyxy, confidence, class_id in zip(
                    boxes.xyxy.cpu().numpy(),
                    boxes.conf.cpu().numpy(),
                    boxes.cls.cpu().numpy(),
                    strict=True,
                ):
                    x1, y1, x2, y2 = (float(value) for value in xyxy)
                    index = int(class_id)
                    label = str(names[index] if isinstance(names, dict) else names[index])
                    detections.append(
                        YOLODetection(
                            label=label,
                            confidence=float(confidence),
                            bounding_box=Box(x=x1, y=y1, width=x2 - x1, height=y2 - y1),
                            class_id=index,
                        )
                    )
            return YOLOInference(
                detections=detections,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error_code=None,
                metadata=self.metadata(loaded=True),
            )
        except Exception as exc:
            return YOLOInference(
                detections=[],
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error_code=f"YOLO_RUNTIME_ERROR:{type(exc).__name__}",
                metadata=self.metadata(loaded=True),
            )

    def metadata(self, *, loaded: bool) -> ModelMetadata:
        local_candidate = self.config.model_cache / Path(self.config.yolo_model).name
        return ModelMetadata(
            model_name="YOLO11n",
            model_version="Ultralytics YOLO11",
            source="Ultralytics pretrained COCO checkpoint",
            task="general object detection",
            framework="Ultralytics/PyTorch",
            local_file=str(local_candidate) if local_candidate.is_file() else None,
            device=self._device,
            license="AGPL-3.0 (Ultralytics open-source distribution)",
            training_status="PRETRAINED",
            loaded=loaded,
        )
