from __future__ import annotations

import math
import platform
import re
import time
from typing import Any

from ..core.config import Settings, get_settings
from ..core.errors import InvalidOcrEngineError, NutriLensError
from ..nlp.parser import FallbackIngredientExtractor, extract_explicit_allergens
from ..ocr.extractor import configure_tesseract
from ..ocr.nutrition_parser import MODEL_FIELDS, _group_spatial_rows, basis_candidate_lines, parse_nutrition_text
from ..ocr.service import OcrExecution, execute_ocr
from .team_contracts import canonical_nutrition, parse_ocr_nutrition


def evaluate_nutrition_result(
    extracted: dict[str, float],
    ground_truth: dict[str, float],
    *,
    relative_tolerance: float = 0.01,
    absolute_tolerance: float = 1e-4,
) -> dict[str, Any]:
    correct: list[str] = []
    incorrect: dict[str, dict[str, float]] = {}
    missing: list[str] = []
    for field, expected in ground_truth.items():
        if field not in extracted:
            missing.append(field)
        elif math.isclose(float(extracted[field]), float(expected), rel_tol=relative_tolerance, abs_tol=absolute_tolerance):
            correct.append(field)
        else:
            incorrect[field] = {"expected": float(expected), "actual": float(extracted[field])}
    return {
        "correct_fields": sorted(correct),
        "incorrect_fields": incorrect,
        "missing_fields": sorted(missing),
        "extra_fields": sorted(set(extracted) - set(ground_truth)),
        "correct_count": len(correct),
        "incorrect_count": len(incorrect),
        "missing_count": len(missing),
        "ground_truth_count": len(ground_truth),
    }


def benchmark_environment(engine: str = "tesseract", settings: Settings | None = None) -> dict[str, Any]:
    if engine.casefold() != "tesseract":
        raise InvalidOcrEngineError()
    version: str | None = None
    try:
        pytesseract = configure_tesseract(settings or get_settings())
        version = str(pytesseract.get_tesseract_version())
    except Exception:
        pass
    return {
        "operating_system": platform.platform(),
        "python_version": platform.python_version(),
        "device": "cpu",
        "tesseract_version": version,
    }


def _ocr_debug(execution: OcrExecution, parsed) -> dict[str, Any]:
    result = execution.result
    normalized_lines = [line.strip() for line in result.text.splitlines() if line.strip()]
    keyword_pattern = re.compile(
        r"\b(?:nutrition(?:al)?|energy|calories?|proteins?|carbohydrates?|"
        r"sugars?|saturated\s+fat|trans\s+fat|total\s+fat|sodium|calcium)\b",
        re.I,
    )
    keyword_lines = [
        line for line in normalized_lines
        if keyword_pattern.search(line)
    ]
    numeric_rows = [
        line for line in normalized_lines
        if re.search(r"\d(?:[.,]\d+)?\s*(?:kcal|kj|mg|g|%)\b", line, re.I)
        and keyword_pattern.search(line)
    ]
    candidate_parses = []
    for evidence in result.candidate_evidence:
        candidate = parse_nutrition_text(
            evidence.text,
            evidence.words,
            basis_override=parsed.basis if parsed.basis != "unknown" else None,
        )
        candidate_parses.append({
            "region": evidence.region,
            "basis": candidate.basis,
            "structured_fields": sorted(candidate.nutrients),
            "warnings": candidate.warnings,
        })
    return {
        "raw_text": result.text,
        "normalized_lines": normalized_lines,
        "spatial_rows": [
            " ".join(word.text for word in row)
            for row in _group_spatial_rows(result.table_words)
        ],
        "candidate_basis_text": basis_candidate_lines(result.text),
        "nutrition_keyword_recognized": bool(keyword_lines),
        "nutrition_keyword_lines": keyword_lines,
        "basis_phrase_recognized": parsed.basis != "unknown",
        "numeric_nutrition_rows_recognized": bool(numeric_rows),
        "numeric_nutrition_rows": numeric_rows,
        "structured_field_count": len(parsed.nutrients),
        "diagnosis": (
            "structured parsing succeeded"
            if parsed.nutrients
            else "parser/integration failure"
            if numeric_rows or parsed.basis != "unknown"
            else "OCR recognition failure"
        ),
        "candidate_parses": candidate_parses,
    }


def _structured_result(
    execution: OcrExecution,
    processing_seconds: float,
    ground_truth: dict[str, float] | None,
) -> dict[str, Any]:
    parsed = parse_ocr_nutrition(execution.result)
    nutrition = canonical_nutrition(parsed)
    payload: dict[str, Any] = {
        "environment": benchmark_environment("tesseract"),
        "runtime": {
            "initialization_seconds": 0.0,
            "processing_seconds": round(processing_seconds, 3),
            "total_seconds": round(processing_seconds, 3),
        },
        "ocr": {
            "rotation": execution.result.selected_rotation,
            "confidence": round(execution.result.mean_confidence / 100, 3)
            if execution.result.mean_confidence is not None else None,
            "line_count": len([line for line in execution.result.text.splitlines() if line.strip()]),
        },
        "analysis": {
            "basis": parsed.basis,
            "nutrition": nutrition,
            "qualifiers": {
                field: item.qualifier for field, item in parsed.nutrients.items() if item.qualifier
            },
            "ingredients": FallbackIngredientExtractor().extract(execution.result.text),
            "allergens": extract_explicit_allergens(execution.result.text),
            "warnings": parsed.warnings,
            "missing_model_fields": sorted(set(MODEL_FIELDS) - set(parsed.normalized_model_values)),
        },
        "ocr_debug": _ocr_debug(execution, parsed),
    }
    if ground_truth is not None:
        payload["evaluation"] = evaluate_nutrition_result(nutrition, ground_truth)
    return payload


def benchmark_ocr_engine(
    image_bytes: bytes,
    engine: str = "tesseract",
    content_type: str | None = None,
    *,
    ground_truth: dict[str, float] | None = None,
    warm_runs: int = 0,
    settings: Settings | None = None,
) -> dict[str, Any]:
    if engine.casefold() != "tesseract" or warm_runs:
        raise InvalidOcrEngineError()
    started = time.perf_counter()
    try:
        execution = execute_ocr(image_bytes, "tesseract", content_type, settings)
    except NutriLensError as exc:
        return {"error": {"code": exc.code, "message": exc.public_message}}
    return _structured_result(execution, time.perf_counter() - started, ground_truth)
