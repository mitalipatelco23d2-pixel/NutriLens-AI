"""Paddle-first OCR with explicit, non-merging fallbacks."""

from __future__ import annotations

import numpy as np

from ai.food_understanding.config import R3Config
from ai.food_understanding.schemas import ConfidenceLevel, OCRAttempt, OCRResult, PreprocessProfile
from ai.ocr.base import OCREngine
from ai.ocr.easy_engine import EasyOCREngine
from ai.ocr.paddle_engine import PaddleOCREngine
from ai.ocr.trocr_engine import TrOCREngine


class OCROrchestrator:
    def __init__(
        self,
        config: R3Config,
        *,
        primary: OCREngine | None = None,
        fallback: OCREngine | None = None,
        experimental: OCREngine | None = None,
    ) -> None:
        device = "gpu" if config.validated_device() == "cuda" else "cpu"
        self.config = config
        self.primary = primary or PaddleOCREngine(
            device=device,
            allow_downloads=config.allow_model_downloads,
            model_storage_directory=config.model_cache / "paddle",
        )
        self.fallback = fallback or EasyOCREngine(
            gpu=device == "gpu",
            allow_downloads=config.allow_model_downloads,
            model_storage_directory=config.model_cache / "easyocr",
        )
        self.experimental = experimental or TrOCREngine(
            enabled=config.trocr_enabled,
            allow_downloads=config.allow_model_downloads,
        )

    def run(
        self,
        image: np.ndarray,
        *,
        languages: list[str],
        profile: PreprocessProfile,
    ) -> OCRResult:
        primary = self.primary.recognize(image, languages)
        attempts = [primary]
        selected: OCRAttempt | None = primary if _is_sufficient(primary, self.config) else None
        fallback_reason: str | None = None

        if selected is None:
            fallback_reason = _fallback_reason(primary, self.config)
            second = self.fallback.recognize(image, languages)
            attempts.append(second)
            if _is_sufficient(second, self.config):
                selected = second
            elif self.config.trocr_enabled:
                third = self.experimental.recognize(image, languages)
                attempts.append(third)
                if _is_sufficient(third, self.config):
                    selected = third

        if selected is None:
            successful = [attempt for attempt in attempts if attempt.status == "SUCCESS"]
            selected = max(
                successful,
                key=lambda attempt: attempt.confidence if attempt.confidence is not None else -1,
                default=None,
            )
        confidence = selected.confidence if selected is not None else None
        lines = selected.lines if selected is not None else []
        return OCRResult(
            selected_engine=selected.engine if selected is not None else None,
            attempts=attempts,
            lines=lines,
            text="\n".join(line.text for line in lines),
            confidence=confidence,
            confidence_level=_level(confidence),
            fallback_reason=fallback_reason,
            preprocessing_profile=profile,
        )


def _is_sufficient(attempt: OCRAttempt, config: R3Config) -> bool:
    characters = len("".join(line.text for line in attempt.lines).strip())
    return (
        attempt.status == "SUCCESS"
        and attempt.confidence is not None
        and attempt.confidence >= config.ocr_min_confidence
        and characters >= config.ocr_min_characters
    )


def _fallback_reason(attempt: OCRAttempt, config: R3Config) -> str:
    if attempt.status != "SUCCESS":
        return f"Primary OCR status was {attempt.status}."
    characters = len("".join(line.text for line in attempt.lines).strip())
    if characters < config.ocr_min_characters:
        return "Primary OCR returned insufficient text."
    return "Primary OCR confidence was below the configured threshold."


def _level(confidence: float | None) -> ConfidenceLevel:
    if confidence is None:
        return ConfidenceLevel.UNRELIABLE
    if confidence >= 0.85:
        return ConfidenceLevel.HIGH
    if confidence >= 0.65:
        return ConfidenceLevel.MEDIUM
    if confidence >= 0.4:
        return ConfidenceLevel.LOW
    return ConfidenceLevel.UNRELIABLE
