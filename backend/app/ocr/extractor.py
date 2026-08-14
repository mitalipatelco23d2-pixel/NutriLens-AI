from __future__ import annotations

import re
import shutil
from collections import Counter
from dataclasses import dataclass, field
from statistics import mean

import cv2
import numpy as np
import pytesseract
from PIL import Image
from pytesseract import Output

from ..core.config import Settings, get_settings
from ..core.errors import OcrProcessingError, OcrUnavailableError
from .nutrition_parser import (
    _detect_basis,
    _field_for_row,
    _group_spatial_rows,
    _row_unit,
    infer_per_100_column,
    parse_nutrition_text,
)
from .geometry import NormalizedToken
from .panel_detection import detect_nutrition_panels, table_preprocessing_variants


ORIENTATIONS = (0, 90, 180, 270)
ORIENTATION_PSM = 11
OCR_PSMS = (6, 11)
NUTRITION_KEYWORDS = {
    "nutrition",
    "energy",
    "calories",
    "kcal",
    "fat",
    "saturated",
    "sodium",
    "salt",
    "carbohydrate",
    "sugar",
    "fibre",
    "fiber",
    "protein",
    "ingredient",
    "ingredients",
}


OcrWord = NormalizedToken  # Backward-compatible name for existing imports.


@dataclass(frozen=True)
class OcrCandidate:
    text: str
    mean_confidence: float | None
    rotation: int
    psm: int
    quality_score: float
    valid_tokens: int
    keyword_hits: int
    words: tuple[OcrWord, ...] = ()
    region: str = "full"
    source_image: Image.Image | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class OcrEvidence:
    text: str
    words: tuple[OcrWord, ...]
    region: str


@dataclass(frozen=True)
class OcrResult:
    text: str
    engine: str
    language: str
    mean_confidence: float | None
    selected_rotation: int = 0
    selected_psm: int = 6
    attempted_psms: tuple[int, ...] = OCR_PSMS
    candidate_count: int = 1
    selected_region: str = "full"
    table_text: str | None = None
    table_words: tuple[OcrWord, ...] = ()
    candidate_evidence: tuple[OcrEvidence, ...] = ()


def configure_tesseract(settings: Settings | None = None) -> None:
    configured = (settings or get_settings()).tesseract_cmd
    # Reset to the platform PATH default when no override is supplied. This also
    # prevents a prior configured Windows path leaking into a later Linux/test run.
    pytesseract.pytesseract.tesseract_cmd = configured or "tesseract"


def tesseract_readiness(settings: Settings | None = None) -> tuple[bool, str]:
    configure_tesseract(settings)
    command = pytesseract.pytesseract.tesseract_cmd
    found = shutil.which(command) if command else None
    if not found:
        return False, "Tesseract executable was not found."
    try:
        version = str(pytesseract.get_tesseract_version()).splitlines()[0]
    except (pytesseract.TesseractError, OSError):
        return False, "Tesseract could not be started."
    return True, f"Tesseract {version} is available."


def score_ocr_text(text: str, confidence: float | None) -> tuple[float, int, int]:
    """Score usable label text without depending on a particular photograph."""
    tokens = re.findall(r"[A-Za-z]+|\d+(?:[.,]\d+)?", text)
    valid_tokens = sum(len(token) >= 2 or token.isdigit() for token in tokens)
    lowered = {token.casefold() for token in tokens}
    keyword_hits = len(lowered & NUTRITION_KEYWORDS)
    coherent_rows = 0
    impossible_rows = 0
    for line in text.splitlines():
        if not re.search(
            r"\b(?:energy|fat|sodium|salt|carbohydrate|sugar|fibre|fiber|protein)\b",
            line,
            re.I,
        ):
            continue
        values = [
            float(value.replace(",", "."))
            for value in re.findall(r"\b\d+(?:[.,]\d+)?\b", line)
        ]
        if values:
            coherent_rows += 1
            if not re.search(r"\benergy\b", line, re.I) and any(value > 100 for value in values):
                impossible_rows += 1
    confidence_score = max(confidence or 0.0, 0.0)
    score = (
        confidence_score
        + min(valid_tokens, 100) * 1.4
        + keyword_hits * 18.0
        + coherent_rows * 12.0
        - impossible_rows * 20.0
        + min(len(text.strip()), 800) * 0.035
    )
    return round(score, 3), valid_tokens, keyword_hits


def select_best_orientation(candidates: list[OcrCandidate]) -> OcrCandidate:
    if not candidates:
        raise OcrProcessingError("OCR produced no orientation candidates")
    return max(
        candidates,
        key=lambda candidate: (
            candidate.quality_score,
            candidate.keyword_hits,
            candidate.valid_tokens,
            -(candidate.rotation != 0),
        ),
    )


def _text_and_words(data: dict) -> tuple[str, list[float], tuple[OcrWord, ...]]:
    words = [str(word).strip() for word in data.get("text", [])]
    line_groups: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []
    spatial_words: list[OcrWord] = []
    for index, word in enumerate(words):
        if not word:
            continue
        try:
            confidence = float(data.get("conf", [])[index])
        except (IndexError, TypeError, ValueError):
            confidence = -1.0
        key = (
            int(data.get("block_num", [0] * len(words))[index]),
            int(data.get("par_num", [0] * len(words))[index]),
            int(data.get("line_num", [index] * len(words))[index]),
        )
        line_groups.setdefault(key, []).append(word)
        if confidence >= 0:
            confidences.append(confidence)
        try:
            spatial_words.append(
                OcrWord(
                    text=word,
                    confidence=confidence,
                    left=int(data["left"][index]),
                    top=int(data["top"][index]),
                    width=int(data["width"][index]),
                    height=int(data["height"][index]),
                    block=key[0],
                    paragraph=key[1],
                    line=key[2],
                )
            )
        except (KeyError, IndexError, TypeError, ValueError):
            pass
    text = "\n".join(" ".join(line) for line in line_groups.values()).strip()
    return text, confidences, tuple(spatial_words)


def _run_tesseract_pass(
    image: Image.Image,
    language: str,
    rotation: int,
    psm: int,
    region: str = "full",
) -> OcrCandidate:
    data = pytesseract.image_to_data(
        image,
        lang=language,
        config=f"--oem 3 --psm {psm} -c preserve_interword_spaces=1",
        output_type=Output.DICT,
    )
    text, confidences, words = _text_and_words(data)
    mean_confidence = round(mean(confidences), 1) if confidences else None
    quality, valid_tokens, keyword_hits = score_ocr_text(text, mean_confidence)
    return OcrCandidate(
        text=text,
        mean_confidence=mean_confidence,
        rotation=rotation,
        psm=psm,
        quality_score=quality,
        valid_tokens=valid_tokens,
        keyword_hits=keyword_hits,
        words=words,
        region=region,
        source_image=image,
    )


def _rotate_clockwise(image: Image.Image, rotation: int) -> Image.Image:
    return image.copy() if rotation == 0 else image.rotate(-rotation, expand=True)


def _dense_text_crop(image: Image.Image, candidate: OcrCandidate) -> Image.Image | None:
    useful = [word for word in candidate.words if word.confidence >= 10 and word.width > 0 and word.height > 0]
    if len(useful) < 4:
        return None
    left = min(word.left for word in useful)
    top = min(word.top for word in useful)
    right = max(word.left + word.width for word in useful)
    bottom = max(word.top + word.height for word in useful)
    padding_x = max(round(image.width * 0.04), 8)
    padding_y = max(round(image.height * 0.04), 8)
    bounds = (
        max(0, left - padding_x),
        max(0, top - padding_y),
        min(image.width, right + padding_x),
        min(image.height, bottom + padding_y),
    )
    crop_width = bounds[2] - bounds[0]
    crop_height = bounds[3] - bounds[1]
    if crop_width < 100 or crop_height < 100:
        return None
    if crop_width * crop_height >= image.width * image.height * 0.92:
        return None
    return image.crop(bounds)


def _nutrition_table_crop(image: Image.Image, candidate: OcrCandidate) -> Image.Image | None:
    """Find a table from nutrition-keyword rows, without image-specific coordinates."""
    keyword_words = [
        word
        for word in candidate.words
        if re.sub(r"\W+", "", word.text).casefold() in NUTRITION_KEYWORDS
    ]
    if len(keyword_words) < 3:
        return None
    top = min(word.top for word in keyword_words)
    bottom = max(word.top + word.height for word in keyword_words)
    row_span = max(bottom - top, int(image.height * 0.15))
    top = max(0, top - int(row_span * 0.25))
    bottom = min(image.height, bottom + int(row_span * 0.35))
    nearby = [
        word
        for word in candidate.words
        if top <= word.center_y <= bottom and word.confidence >= 0
    ]
    if len(nearby) < 6:
        return None
    left = max(0, min(word.left for word in nearby) - int(image.width * 0.04))
    right = min(
        image.width,
        max(word.left + word.width for word in nearby) + int(image.width * 0.04),
    )
    if right - left < 150 or bottom - top < 150:
        return None
    crop = image.crop((left, top, right, bottom))
    if min(crop.size) < 1400:
        scale = min(2.0, 1400 / min(crop.size))
        crop = crop.resize(
            (round(crop.width * scale), round(crop.height * scale)),
            Image.Resampling.LANCZOS,
        )
    return crop


def _merge_candidate_text(candidates: list[OcrCandidate], primary: OcrCandidate) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    minimum_quality = max(20.0, primary.quality_score * 0.45)
    for candidate in sorted(candidates, key=lambda item: item.quality_score, reverse=True):
        if candidate.quality_score < minimum_quality:
            continue
        for line in candidate.text.splitlines():
            clean = " ".join(line.split()).strip()
            key = re.sub(r"\W+", "", clean).casefold()
            if clean and key and key not in seen:
                lines.append(clean)
                seen.add(key)
    return "\n".join(lines).strip()


def _table_candidate_score(candidate: OcrCandidate) -> float:
    parsed = parse_nutrition_text(candidate.text, candidate.words)
    rejected = sum(warning.startswith("Rejected ") for warning in parsed.warnings)
    return (
        candidate.quality_score
        + len(parsed.nutrients) * 45
        + (50 if parsed.basis == "per_100g" else 0)
        - rejected * 30
    )


def _refine_numeric_cells(candidate: OcrCandidate, language: str) -> OcrCandidate:
    """Re-read isolated per-100-g cells and accept only repeated OCR results."""
    if candidate.source_image is None:
        return candidate
    basis = _detect_basis(candidate.text)
    per_100_x = infer_per_100_column(candidate.words, basis)
    if per_100_x is None:
        return candidate

    gray = np.asarray(candidate.source_image.convert("L"))
    half_width = max(70, round(gray.shape[1] * 0.105))
    left = max(0, round(per_100_x - half_width))
    right = min(gray.shape[1], round(per_100_x + half_width))
    additions: list[OcrWord] = []
    replaced_words: set[OcrWord] = set()
    seen_fields: set[str] = set()
    numeric = re.compile(r"\d+(?:[.,]\d+)?")
    for row in _group_spatial_rows(candidate.words):
        row_text = " ".join(word.text for word in row)
        field_name = _field_for_row(row_text)
        if not field_name or field_name in seen_fields or not _row_unit(row_text, field_name):
            continue
        seen_fields.add(field_name)
        anchor = min(row, key=lambda word: abs(word.center_x - per_100_x))
        center_y = round(anchor.center_y)
        readings: list[str] = []
        for half_height in (25, 35):
            top = max(0, center_y - half_height)
            bottom = min(gray.shape[0], center_y + half_height)
            if bottom <= top or right <= left:
                continue
            crop = gray[top:bottom, left:right]
            variants = (
                crop,
                cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
            )
            for variant in variants:
                raw = pytesseract.image_to_string(
                    variant,
                    lang=language,
                    config="--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789.,",
                ).strip().strip(".,")
                if numeric.fullmatch(raw):
                    readings.append(raw.replace(",", "."))
        if not readings:
            continue
        value, count = Counter(readings).most_common(1)[0]
        if count < 2:
            continue
        replaced_words.update(
            word
            for word in row
            if left <= word.center_x <= right
            and abs(word.center_y - center_y) <= 45
            and re.search(r"\d", word.text)
        )
        additions.append(
            OcrWord(
                text=value,
                confidence=100.0,
                left=round(per_100_x) - 1,
                top=center_y - 1,
                width=2,
                height=2,
                block=anchor.block,
                paragraph=anchor.paragraph,
                line=anchor.line,
            )
        )
    if not additions:
        return candidate
    return OcrCandidate(
        text=candidate.text,
        mean_confidence=candidate.mean_confidence,
        rotation=candidate.rotation,
        psm=candidate.psm,
        quality_score=candidate.quality_score,
        valid_tokens=candidate.valid_tokens,
        keyword_hits=candidate.keyword_hits,
        words=(*(word for word in candidate.words if word not in replaced_words), *additions),
        region=candidate.region,
        source_image=candidate.source_image,
    )


def extract_text_from_image(
    image: Image.Image,
    language: str | None = None,
    settings: Settings | None = None,
) -> OcrResult:
    active_settings = settings or get_settings()
    ready, _ = tesseract_readiness(active_settings)
    if not ready:
        raise OcrUnavailableError()
    lang = language or active_settings.ocr_language

    orientation_candidates: list[OcrCandidate] = []
    for rotation in ORIENTATIONS:
        try:
            orientation_candidates.append(
                _run_tesseract_pass(
                    _rotate_clockwise(image, rotation),
                    lang,
                    rotation,
                    ORIENTATION_PSM,
                )
            )
        except (pytesseract.TesseractError, OSError):
            continue

    best_orientation = select_best_orientation(orientation_candidates)
    oriented_image = _rotate_clockwise(image, best_orientation.rotation)
    selected_candidates = [best_orientation]
    try:
        selected_candidates.append(
            _run_tesseract_pass(oriented_image, lang, best_orientation.rotation, 6)
        )
        crop = _dense_text_crop(oriented_image, best_orientation)
        if crop is not None:
            selected_candidates.append(
                _run_tesseract_pass(
                    crop,
                    lang,
                    best_orientation.rotation,
                    6,
                    region="dense_text_crop",
                )
            )
        panels = detect_nutrition_panels(oriented_image, best_orientation.words, limit=1)
        if panels:
            for _, variant, psm in table_preprocessing_variants(
                panels[0].image, active_settings.max_image_pixels
            ):
                selected_candidates.append(
                    _run_tesseract_pass(
                        variant, lang, best_orientation.rotation, psm, region="nutrition_table"
                    )
                )
        else:
            table_crop = _nutrition_table_crop(oriented_image, best_orientation)
            if table_crop is not None:
                selected_candidates.extend(
                    [
                        _run_tesseract_pass(
                            table_crop, lang, best_orientation.rotation, psm, region="nutrition_table"
                        )
                        for psm in OCR_PSMS
                    ]
                )
    except (pytesseract.TesseractError, OSError):
        # The successful orientation pass remains usable if a secondary pass fails.
        pass

    primary = max(selected_candidates, key=lambda candidate: candidate.quality_score)
    table_candidates = [candidate for candidate in selected_candidates if candidate.region == "nutrition_table"]
    best_table = max(table_candidates, key=_table_candidate_score, default=None)
    if best_table is not None:
        try:
            best_table = _refine_numeric_cells(best_table, lang)
        except (pytesseract.TesseractError, OSError, cv2.error):
            # Consensus refinement is optional; retain the full-table OCR result.
            pass
    text = _merge_candidate_text(selected_candidates, primary)
    if not text:
        raise OcrProcessingError("OCR returned no usable text")
    evidence_candidates = ([best_table] if best_table is not None else []) + [
        candidate for candidate in selected_candidates if candidate is not best_table
    ]
    return OcrResult(
        text=text,
        engine="tesseract",
        language=lang,
        mean_confidence=primary.mean_confidence,
        selected_rotation=primary.rotation,
        selected_psm=primary.psm,
        attempted_psms=OCR_PSMS,
        candidate_count=len(orientation_candidates) + len(selected_candidates) - 1,
        selected_region=primary.region,
        table_text=best_table.text if best_table else None,
        table_words=best_table.words if best_table else primary.words,
        candidate_evidence=tuple(
            OcrEvidence(candidate.text, candidate.words, candidate.region)
            for candidate in evidence_candidates
        ),
    )
