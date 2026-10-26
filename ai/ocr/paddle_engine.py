"""PaddleOCR primary adapter with v2/v3-compatible result normalization."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import numpy as np

from ai.food_understanding.schemas import OCRAttempt, OCRLine
from ai.ocr.base import aggregate_confidence, polygon_to_box

PADDLE_DETECTION_MODEL = "PP-OCRv5_mobile_det"
PADDLE_RECOGNITION_MODEL = "PP-OCRv5_mobile_rec"


class PaddleOCREngine:
    name = "PaddleOCR"

    def __init__(
        self,
        *,
        device: str = "cpu",
        allow_downloads: bool = False,
        model_storage_directory: Path = Path(".model-cache/r3/paddle"),
    ) -> None:
        self.device = device
        self.allow_downloads = allow_downloads
        self.model_storage_directory = model_storage_directory
        self._reader: Any = None
        self._load_error: str | None = None

    def _load(self, languages: list[str]) -> None:
        if self._reader is not None or self._load_error is not None:
            return
        model_root = self.model_storage_directory.resolve()
        if not self.allow_downloads and not _models_cached(model_root):
            self._load_error = "MODEL_NOT_CACHED"
            return
        os.environ["PADDLE_PDX_CACHE_HOME"] = str(model_root)
        try:
            from paddleocr import PaddleOCR

            language = _paddle_language(languages)
            kwargs: dict[str, Any] = {
                "enable_mkldnn": False,
                "lang": language,
                "text_detection_model_name": PADDLE_DETECTION_MODEL,
                "text_recognition_model_name": PADDLE_RECOGNITION_MODEL,
                "use_doc_orientation_classify": False,
                "use_doc_unwarping": False,
                "use_textline_orientation": False,
            }
            try:
                self._reader = PaddleOCR(device=self.device, **kwargs)
            except TypeError:
                self._reader = PaddleOCR(
                    use_angle_cls=True, use_gpu=self.device == "gpu", lang=language
                )
        except Exception as exc:  # optional runtime/model availability boundary
            self._load_error = type(exc).__name__

    def recognize(self, image: np.ndarray, languages: list[str]) -> OCRAttempt:
        started = time.perf_counter()
        self._load(languages)
        if self._reader is None:
            return OCRAttempt(
                engine="PaddleOCR",
                status="UNAVAILABLE",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                language_configuration=languages,
                error_code=f"PADDLE_UNAVAILABLE:{self._load_error or 'not_loaded'}",
            )
        try:
            prepared = image
            if prepared.ndim == 2:
                prepared = np.repeat(prepared[:, :, np.newaxis], 3, axis=2)
            if hasattr(self._reader, "predict"):
                raw = self._reader.predict(prepared)
            else:
                raw = self._reader.ocr(prepared, cls=True)
            lines = _normalize_paddle(raw)
            return OCRAttempt(
                engine="PaddleOCR",
                status="SUCCESS" if lines else "NO_TEXT",
                lines=lines,
                confidence=aggregate_confidence(lines),
                elapsed_ms=(time.perf_counter() - started) * 1000,
                language_configuration=languages,
            )
        except Exception as exc:  # engine-specific failures are data, not API crashes
            return OCRAttempt(
                engine="PaddleOCR",
                status="FAILED",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                language_configuration=languages,
                error_code=f"PADDLE_RUNTIME_ERROR:{type(exc).__name__}",
            )


def _models_cached(root: Path) -> bool:
    official = root / "official_models"
    if not official.is_dir():
        return False
    names = {path.name.lower() for path in official.iterdir() if path.is_dir()}
    return {
        PADDLE_DETECTION_MODEL.lower(),
        PADDLE_RECOGNITION_MODEL.lower(),
    }.issubset(names)


def _paddle_language(languages: list[str]) -> str:
    normalized = {value.lower().split("-", maxsplit=1)[0] for value in languages}
    if normalized & {"hi", "mr", "ne"}:
        return "devanagari"
    if "bn" in normalized or "as" in normalized:
        return "bengali"
    if "ta" in normalized:
        return "ta"
    if "te" in normalized:
        return "te"
    if "kn" in normalized:
        return "kannada"
    if "ml" in normalized:
        return "malayalam"
    return "en"


def _normalize_paddle(raw: Any) -> list[OCRLine]:
    lines: list[OCRLine] = []
    if not raw:
        return lines

    # PaddleOCR 3.x result objects expose a JSON-like payload.
    for result in raw if isinstance(raw, list) else [raw]:
        payload = getattr(result, "json", None)
        if callable(payload):
            payload = payload()
        if isinstance(payload, dict):
            data = payload.get("res", payload)
            texts = data.get("rec_texts", [])
            scores = data.get("rec_scores", [])
            polygons = data.get("rec_polys", data.get("dt_polys", []))
            for index, text in enumerate(texts):
                confidence = float(scores[index]) if index < len(scores) else None
                box = polygon_to_box(polygons[index]) if index < len(polygons) else None
                if str(text).strip():
                    lines.append(OCRLine(text=str(text), confidence=confidence, bounding_box=box))
            continue

        # PaddleOCR 2.x: page -> [polygon, (text, confidence)].
        page = result or []
        for entry in page:
            try:
                polygon, recognition = entry
                text, confidence = recognition
                if str(text).strip():
                    lines.append(
                        OCRLine(
                            text=str(text),
                            confidence=float(confidence),
                            bounding_box=polygon_to_box(polygon),
                        )
                    )
            except (TypeError, ValueError, IndexError):
                continue
    return lines
