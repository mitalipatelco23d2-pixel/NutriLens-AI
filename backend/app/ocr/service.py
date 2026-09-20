from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, Literal

from PIL import Image, UnidentifiedImageError

from ..core.config import Settings, get_settings
from ..core.errors import InvalidImageError, InvalidOcrEngineError
from .extractor import OcrResult, extract_text_from_image
from .preprocessing import PreparedImage, validate_and_preprocess_image


OcrEngineName = Literal["tesseract"]
SUPPORTED_OCR_ENGINES = ("tesseract",)


@dataclass(frozen=True)
class OcrExecution:
    result: OcrResult
    prepared: PreparedImage

    def normalized_contract(self, include_raw_text: bool = True) -> dict[str, Any]:
        grouped: dict[tuple[int, int, int], list] = {}
        for word in self.result.table_words:
            grouped.setdefault((word.block, word.paragraph, word.line), []).append(word)
        lines = []
        for words in grouped.values():
            ordered = sorted(words, key=lambda word: word.left)
            confidences = [word.confidence for word in ordered if word.confidence >= 0]
            lines.append(
                {
                    "text": " ".join(word.text for word in ordered),
                    "confidence": round(sum(confidences) / len(confidences) / 100, 4)
                    if confidences
                    else None,
                }
            )
        if not lines:
            fallback_confidence = (
                round(self.result.mean_confidence / 100, 4)
                if self.result.mean_confidence is not None
                else None
            )
            lines = [
                {"text": line.strip(), "confidence": fallback_confidence}
                for line in self.result.text.splitlines()
                if line.strip()
            ]
        return {
            "engine": self.result.engine,
            "raw_text": self.result.text if include_raw_text else None,
            "lines": lines,
            "mean_confidence": round(self.result.mean_confidence / 100, 4)
            if self.result.mean_confidence is not None
            else None,
            "selected_rotation": self.result.selected_rotation,
            "metadata": {
                "language": self.result.language,
                "selected_region": self.result.selected_region,
                "candidate_count": self.result.candidate_count,
                "image_width": self.prepared.original_width,
                "image_height": self.prepared.original_height,
                "preprocessing_applied": self.prepared.preprocessing_applied,
            },
        }


def resolve_ocr_engine(engine: str | None, settings: Settings | None = None) -> OcrEngineName:
    selected = (engine or (settings or get_settings()).ocr_engine).strip().casefold()
    if selected not in SUPPORTED_OCR_ENGINES:
        raise InvalidOcrEngineError()
    return selected  # type: ignore[return-value]


def _infer_content_type(image_bytes: bytes) -> str:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image_format = image.format
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise InvalidImageError() from exc
    media_types = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
    if image_format not in media_types:
        raise InvalidImageError()
    return media_types[image_format]


def execute_ocr(
    image_bytes: bytes,
    engine: str | None = None,
    content_type: str | None = None,
    settings: Settings | None = None,
) -> OcrExecution:
    active = settings or get_settings()
    selected = resolve_ocr_engine(engine, active)
    prepared = validate_and_preprocess_image(
        image_bytes, content_type or _infer_content_type(image_bytes), active
    )
    result = extract_text_from_image(
        prepared.image, language=active.ocr_language, settings=active
    )
    return OcrExecution(result=result, prepared=prepared)


def run_ocr(image_bytes: bytes, engine: str | None = None) -> dict[str, Any]:
    """Stable Member 4 OCR contract used by team-owned downstream modules."""
    return execute_ocr(image_bytes, engine=engine).normalized_contract()
