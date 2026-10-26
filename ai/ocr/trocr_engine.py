"""Optional, disabled-by-default TrOCR text-region adapter."""

from __future__ import annotations

import math
import time
from typing import Any

import cv2
import numpy as np
from PIL import Image

from ai.food_understanding.schemas import OCRAttempt, OCRLine


class TrOCREngine:
    name = "TrOCR"

    def __init__(self, *, enabled: bool = False, allow_downloads: bool = False) -> None:
        self.enabled = enabled
        self.allow_downloads = allow_downloads
        self._processor: Any = None
        self._model: Any = None
        self._load_error: str | None = None

    def _load(self) -> None:
        if self._model is not None or self._load_error is not None:
            return
        try:
            from transformers import TrOCRProcessor, VisionEncoderDecoderModel

            model_name = "microsoft/trocr-small-printed"
            self._processor = TrOCRProcessor.from_pretrained(
                model_name, local_files_only=not self.allow_downloads
            )
            self._model = VisionEncoderDecoderModel.from_pretrained(
                model_name, local_files_only=not self.allow_downloads
            )
            self._model.eval()
        except Exception as exc:
            self._load_error = type(exc).__name__

    def recognize(self, image: np.ndarray, languages: list[str]) -> OCRAttempt:
        started = time.perf_counter()
        if not self.enabled:
            return OCRAttempt(
                engine="TrOCR",
                status="DISABLED",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                language_configuration=languages,
                error_code="EXPERIMENTAL_DISABLED",
            )
        self._load()
        if self._model is None or self._processor is None:
            return OCRAttempt(
                engine="TrOCR",
                status="UNAVAILABLE",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                language_configuration=languages,
                error_code=f"TROCR_UNAVAILABLE:{self._load_error or 'not_loaded'}",
            )
        try:
            import torch

            rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            pixels = self._processor(images=Image.fromarray(rgb), return_tensors="pt").pixel_values
            with torch.inference_mode():
                generated = self._model.generate(
                    pixels,
                    return_dict_in_generate=True,
                    output_scores=True,
                    max_new_tokens=64,
                )
            text = self._processor.batch_decode(generated.sequences, skip_special_tokens=True)[0]
            confidence = _token_confidence(generated, torch)
            lines = [OCRLine(text=text, confidence=confidence)] if text.strip() else []
            return OCRAttempt(
                engine="TrOCR",
                status="SUCCESS" if lines else "NO_TEXT",
                lines=lines,
                confidence=confidence if lines else None,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                language_configuration=languages,
            )
        except Exception as exc:
            return OCRAttempt(
                engine="TrOCR",
                status="FAILED",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                language_configuration=languages,
                error_code=f"TROCR_RUNTIME_ERROR:{type(exc).__name__}",
            )


def _token_confidence(generated: Any, torch_module: Any) -> float | None:
    scores = list(generated.scores)
    if not scores:
        return None
    token_ids = generated.sequences[0, -len(scores) :]
    log_probabilities: list[float] = []
    for score, token_id in zip(scores, token_ids, strict=True):
        log_probs = torch_module.log_softmax(score[0], dim=-1)
        log_probabilities.append(float(log_probs[int(token_id)].item()))
    return float(math.exp(sum(log_probabilities) / len(log_probabilities)))
