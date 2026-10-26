"""EasyOCR fallback adapter."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import numpy as np

from ai.food_understanding.schemas import OCRAttempt, OCRLine
from ai.ocr.base import aggregate_confidence, polygon_to_box


class EasyOCREngine:
    name = "EasyOCR"

    def __init__(
        self,
        *,
        gpu: bool = False,
        allow_downloads: bool = False,
        model_storage_directory: Path | None = None,
    ) -> None:
        self.gpu = gpu
        self.allow_downloads = allow_downloads
        self.model_storage_directory = model_storage_directory
        self._reader: Any = None
        self._reader_languages: tuple[str, ...] = ()
        self._load_error: str | None = None

    def _load(self, languages: list[str]) -> None:
        mapped = tuple(_easy_languages(languages))
        if self._reader is not None and self._reader_languages == mapped:
            return
        try:
            import easyocr

            options: dict[str, Any] = {
                "gpu": self.gpu,
                "download_enabled": self.allow_downloads,
                "verbose": False,
            }
            if self.model_storage_directory is not None:
                options["model_storage_directory"] = str(self.model_storage_directory)
            self._reader = easyocr.Reader(list(mapped), **options)
            self._reader_languages = mapped
            self._load_error = None
        except Exception as exc:
            self._reader = None
            self._load_error = type(exc).__name__

    def recognize(self, image: np.ndarray, languages: list[str]) -> OCRAttempt:
        started = time.perf_counter()
        self._load(languages)
        if self._reader is None:
            return OCRAttempt(
                engine="EasyOCR",
                status="UNAVAILABLE",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                language_configuration=languages,
                error_code=f"EASYOCR_UNAVAILABLE:{self._load_error or 'not_loaded'}",
            )
        try:
            raw = self._reader.readtext(image, detail=1, paragraph=False)
            lines = [
                OCRLine(
                    text=str(text), confidence=float(confidence), bounding_box=polygon_to_box(box)
                )
                for box, text, confidence in raw
                if str(text).strip()
            ]
            return OCRAttempt(
                engine="EasyOCR",
                status="SUCCESS" if lines else "NO_TEXT",
                lines=lines,
                confidence=aggregate_confidence(lines),
                elapsed_ms=(time.perf_counter() - started) * 1000,
                language_configuration=languages,
            )
        except Exception as exc:
            return OCRAttempt(
                engine="EasyOCR",
                status="FAILED",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                language_configuration=languages,
                error_code=f"EASYOCR_RUNTIME_ERROR:{type(exc).__name__}",
            )


def _easy_languages(languages: list[str]) -> list[str]:
    supported = {
        "en",
        "hi",
        "bn",
        "ta",
        "te",
        "kn",
        "ml",
        "gu",
        "pa",
        "ur",
        "or",
        "as",
    }
    mapped = [value.lower().split("-", maxsplit=1)[0] for value in languages]
    selected = [value for value in mapped if value in supported]
    if "en" not in selected:
        selected.insert(0, "en")
    return list(dict.fromkeys(selected))
