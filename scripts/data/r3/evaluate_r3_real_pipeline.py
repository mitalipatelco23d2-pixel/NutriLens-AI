"""Run a governed real-image R3 evaluation without inventing ground truth."""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Literal

import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ai.food_understanding.config import R3Config
from ai.food_understanding.image_input import validate_image_bytes
from ai.food_understanding.pipeline import FoodUnderstandingPipeline, ImagePayload
from ai.food_understanding.quality import assess_image_quality
from ai.food_understanding.schemas import (
    Box,
    InputKind,
    OCRAttempt,
    PreprocessProfile,
    R3ScanResult,
    ViewType,
)
from ai.ocr.orchestrator import OCROrchestrator
from ai.vision.preprocessing import preprocess
from scripts.data.r3.common import (
    REPO_ROOT,
    read_jsonl,
    sha256_file,
    utc_now,
    write_json,
    write_jsonl,
)

ROLE_CONFIG: dict[str, tuple[InputKind, ViewType, PreprocessProfile]] = {
    "NUTRITION_PANEL": (
        InputKind.PRODUCT,
        ViewType.NUTRITION,
        PreprocessProfile.NUTRITION_TABLE,
    ),
    "PACKAGE_FRONT": (InputKind.PRODUCT, ViewType.FRONT, PreprocessProfile.GENERAL_PRODUCT),
    "DIFFICULT_PACKAGE": (
        InputKind.PRODUCT,
        ViewType.GENERAL,
        PreprocessProfile.GENERAL_PRODUCT,
    ),
    "INGREDIENT_PANEL": (
        InputKind.PRODUCT,
        ViewType.INGREDIENTS,
        PreprocessProfile.INGREDIENT_LIST,
    ),
    "BARCODE_CANDIDATE": (
        InputKind.BARCODE,
        ViewType.GENERAL,
        PreprocessProfile.BARCODE,
    ),
    "GROCERY_ITEM": (InputKind.IMAGE, ViewType.GENERAL, PreprocessProfile.GENERAL_PRODUCT),
    "PREPARED_MEAL": (InputKind.MEAL, ViewType.GENERAL, PreprocessProfile.MEAL),
}
IOU_THRESHOLD = 0.5


def hardware_summary() -> dict[str, Any]:
    summary: dict[str, Any] = {
        "logical_cpu_count": os.cpu_count(),
        "machine": platform.machine(),
        "operating_system": platform.platform(),
        "processor": platform.processor(),
        "python": platform.python_version(),
    }
    try:
        import psutil

        summary["physical_cpu_count"] = psutil.cpu_count(logical=False)
        summary["system_memory_bytes"] = psutil.virtual_memory().total
    except ImportError:
        summary["physical_cpu_count"] = None
        summary["system_memory_bytes"] = None
    return summary


class _DisabledOCREngine:
    def __init__(self, name: Literal["PaddleOCR", "EasyOCR", "TrOCR"]) -> None:
        self.name: str = name
        self.engine_name = name

    def recognize(self, image: np.ndarray, languages: list[str]) -> OCRAttempt:
        del image
        return OCRAttempt(
            engine=self.engine_name,
            status="DISABLED",
            elapsed_ms=0,
            language_configuration=languages,
            error_code="DISABLED_FOR_COMPONENT_EVALUATION",
        )


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


def timing_summary(values: Sequence[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "mean_ms": statistics.fmean(values) if values else None,
        "p50_ms": statistics.median(values) if values else None,
        "p95_ms": _percentile(values, 0.95),
        "min_ms": min(values) if values else None,
        "max_ms": max(values) if values else None,
    }


def _box_iou(first: Box, second: Box) -> float:
    x1 = max(first.x, second.x)
    y1 = max(first.y, second.y)
    x2 = min(first.x + first.width, second.x + second.width)
    y2 = min(first.y + first.height, second.y + second.height)
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = first.width * first.height + second.width * second.height - intersection
    return intersection / union if union > 0 else 0.0


def detection_counts(
    references: Sequence[Box], predictions: Sequence[Box], *, threshold: float = IOU_THRESHOLD
) -> tuple[int, int, int, list[float]]:
    """Greedily match predictions to distinct references at the stated IoU threshold."""

    candidates = sorted(
        (
            (_box_iou(reference, prediction), reference_index, prediction_index)
            for reference_index, reference in enumerate(references)
            for prediction_index, prediction in enumerate(predictions)
        ),
        reverse=True,
    )
    matched_references: set[int] = set()
    matched_predictions: set[int] = set()
    matched_ious: list[float] = []
    for iou, reference_index, prediction_index in candidates:
        if iou < threshold:
            break
        if reference_index in matched_references or prediction_index in matched_predictions:
            continue
        matched_references.add(reference_index)
        matched_predictions.add(prediction_index)
        matched_ious.append(iou)
    true_positive = len(matched_references)
    return (
        true_positive,
        len(predictions) - true_positive,
        len(references) - true_positive,
        matched_ious,
    )


def _tokens(value: str | None) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (value or "").lower()))


def token_overlap(reference: str | None, prediction: str | None) -> dict[str, float | int | None]:
    """Compare database reference tokens; this is explicitly not an OCR error rate."""

    reference_tokens = _tokens(reference)
    prediction_tokens = _tokens(prediction)
    overlap = reference_tokens & prediction_tokens
    return {
        "reference_token_count": len(reference_tokens),
        "prediction_token_count": len(prediction_tokens),
        "overlap_token_count": len(overlap),
        "reference_token_recall": len(overlap) / len(reference_tokens)
        if reference_tokens
        else None,
        "prediction_token_precision": len(overlap) / len(prediction_tokens)
        if prediction_tokens
        else None,
    }


def _class_match(reference: str | None, candidates: Iterable[str]) -> bool:
    reference_tokens = _tokens(reference)
    if not reference_tokens:
        return False
    for candidate in candidates:
        candidate_tokens = _tokens(candidate)
        if candidate_tokens and (
            candidate_tokens == reference_tokens
            or candidate_tokens.issubset(reference_tokens)
            or reference_tokens.issubset(candidate_tokens)
        ):
            return True
    return False


def _ground_truth_boxes(row: dict[str, Any]) -> list[Box]:
    boxes = row.get("ground_truth", {}).get("boxes", [])
    return [Box.model_validate(box["pixels_xywh"]) for box in boxes]


def _mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(
        suffix, "image/webp"
    )


def _basic_validation(
    rows: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    role_counts: Counter[str] = Counter()
    quality_counts: Counter[str] = Counter()
    for index, row in enumerate(rows, start=1):
        role = str(row["dataset_role"])
        role_counts[role] += 1
        path = REPO_ROOT / str(row["local_path"])
        try:
            if not path.is_file():
                raise RuntimeError("file is missing")
            checksum = sha256_file(path)
            if checksum != row["sha256"]:
                raise RuntimeError("SHA-256 differs from evaluation manifest")
            content = path.read_bytes()
            validated = validate_image_bytes(
                content,
                filename=path.name,
                mime_type=_mime_type(path),
                view_id=f"validation-{index}",
                view_type=ROLE_CONFIG[role][1],
                config=R3Config(),
            )
            quality, quality_ms = assess_image_quality(validated.original_bgr, R3Config())
            processed = preprocess(validated.original_bgr, ROLE_CONFIG[role][2])
            quality_counts[quality.quality_status.value] += 1
            results.append(
                {
                    "evaluation_id": row["evaluation_id"],
                    "role": role,
                    "sha256_verified": True,
                    "quality_status": quality.quality_status.value,
                    "quality_warnings": quality.warnings,
                    "quality_ms": quality_ms,
                    "preprocessing_ms": processed.metadata.elapsed_ms,
                    "preprocessing_profile": processed.metadata.profile.value,
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "evaluation_id": str(row.get("evaluation_id")),
                    "reason": f"{type(exc).__name__}:{exc}",
                }
            )
    return results, {
        "failed": len(failures),
        "failures": failures,
        "passed": len(results),
        "quality_status_counts": dict(sorted(quality_counts.items())),
        "role_counts": dict(sorted(role_counts.items())),
        "total": len(rows),
    }


def _prediction_row(source: dict[str, Any], result: R3ScanResult) -> dict[str, Any]:
    role = str(source["dataset_role"])
    nutrition_predictions = [
        region.bounding_box for region in result.regions if region.region_type == "nutrition_table"
    ]
    detection: dict[str, Any] | None = None
    if role == "NUTRITION_PANEL":
        references = _ground_truth_boxes(source)
        true_positive, false_positive, false_negative, matched_ious = detection_counts(
            references, nutrition_predictions
        )
        best_ious = [
            max(
                (_box_iou(reference, prediction) for prediction in nutrition_predictions),
                default=0.0,
            )
            for reference in references
        ]
        detection = {
            "false_negative": false_negative,
            "false_positive": false_positive,
            "ground_truth_count": len(references),
            "matched_ious": matched_ious,
            "per_reference_best_ious": best_ious,
            "prediction_count": len(nutrition_predictions),
            "threshold": IOU_THRESHOLD,
            "true_positive": true_positive,
        }

    ground_truth = source.get("ground_truth", {})
    reference_text = ground_truth.get("ingredient_text") if role == "INGREDIENT_PANEL" else None
    category_values = [candidate.value for candidate in result.category_candidates]
    reference_class = None
    if role == "GROCERY_ITEM":
        reference_class = ground_truth.get("fine_name_from_path")
    elif role == "PREPARED_MEAL":
        reference_class = ground_truth.get("class")
    expected_barcode = ground_truth.get("barcode") if role == "BARCODE_CANDIDATE" else None
    decoded_barcodes = [barcode.value for barcode in result.barcode_results]
    attempts = [
        {
            "confidence": attempt.confidence,
            "elapsed_ms": attempt.elapsed_ms,
            "engine": attempt.engine,
            "error_code": attempt.error_code,
            "line_count": len(attempt.lines),
            "status": attempt.status,
        }
        for ocr_result in result.ocr_results.values()
        for attempt in ocr_result.attempts
    ]
    return {
        "evaluation_id": source["evaluation_id"],
        "dataset_role": role,
        "source_dataset": source["source_dataset"],
        "ground_truth_type": ground_truth.get("type"),
        "status": result.status,
        "structured_contract_version": result.contract_version,
        "nutrition_detection": detection,
        "ocr": {
            "attempts": attempts,
            "selected_engines": sorted(
                {
                    ocr_result.selected_engine
                    for ocr_result in result.ocr_results.values()
                    if ocr_result.selected_engine
                }
            ),
            "text_character_count": sum(
                len(ocr_result.text) for ocr_result in result.ocr_results.values()
            ),
        },
        "ingredient_product_reference_overlap": token_overlap(
            str(reference_text) if reference_text is not None else None,
            result.ingredients.raw_text,
        )
        if role == "INGREDIENT_PANEL"
        else None,
        "barcode": {
            "decoded_values": decoded_barcodes,
            "exact_match": str(expected_barcode) in decoded_barcodes
            if expected_barcode is not None
            else None,
            "reference": expected_barcode,
        }
        if role == "BARCODE_CANDIDATE"
        else None,
        "category": {
            "candidate_values": category_values,
            "reference": reference_class,
            "reference_match": _class_match(
                str(reference_class) if reference_class is not None else None,
                category_values,
            ),
        }
        if role in {"GROCERY_ITEM", "PREPARED_MEAL"}
        else None,
        "package_region": {
            "methods": sorted(
                {
                    region.method.value
                    for region in result.regions
                    if region.region_type == "product"
                }
            ),
            "present": any(region.region_type == "product" for region in result.regions),
        }
        if role in {"PACKAGE_FRONT", "DIFFICULT_PACKAGE"}
        else None,
        "timings": result.timings.model_dump(mode="json"),
        "warning_count": len(result.warnings),
        "manual_review_fields": [field.field for field in result.manual_review_fields],
        "models": [model.model_dump(mode="json") for model in result.models],
    }


def _aggregate(predictions: Sequence[dict[str, Any]]) -> dict[str, Any]:
    nutrition = [row["nutrition_detection"] for row in predictions if row["nutrition_detection"]]
    true_positive = sum(row["true_positive"] for row in nutrition)
    false_positive = sum(row["false_positive"] for row in nutrition)
    false_negative = sum(row["false_negative"] for row in nutrition)
    matched_ious = [iou for row in nutrition for iou in row["matched_ious"]]
    all_best_ious = [iou for row in nutrition for iou in row["per_reference_best_ious"]]

    attempts = [attempt for row in predictions for attempt in row["ocr"]["attempts"]]
    by_engine: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for attempt in attempts:
        by_engine[str(attempt["engine"])].append(attempt)

    ingredient_rows = [
        row["ingredient_product_reference_overlap"]
        for row in predictions
        if row["ingredient_product_reference_overlap"] is not None
    ]
    barcode_rows = [row["barcode"] for row in predictions if row["barcode"] is not None]
    category_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in predictions:
        if row["category"] is not None:
            category_rows[str(row["dataset_role"])].append(row["category"])

    timings: dict[str, list[float]] = defaultdict(list)
    for row in predictions:
        for key, value in row["timings"].items():
            timings[key].append(float(value))

    return {
        "nutrition_detection": {
            "evaluated_images": len(nutrition),
            "false_negative": false_negative,
            "false_positive": false_positive,
            "iou_threshold": IOU_THRESHOLD,
            "mean_best_iou_all_references": statistics.fmean(all_best_ious)
            if all_best_ious
            else None,
            "mean_matched_iou": statistics.fmean(matched_ious) if matched_ious else None,
            "precision": true_positive / (true_positive + false_positive)
            if true_positive + false_positive
            else None,
            "recall": true_positive / (true_positive + false_negative)
            if true_positive + false_negative
            else None,
            "true_positive": true_positive,
        },
        "ocr": {
            engine: {
                "attempt_count": len(engine_attempts),
                "status_counts": dict(Counter(item["status"] for item in engine_attempts)),
                "timing": timing_summary([float(item["elapsed_ms"]) for item in engine_attempts]),
            }
            for engine, engine_attempts in sorted(by_engine.items())
        },
        "ocr_error_rates": {
            "cer": None,
            "wer": None,
            "reason": (
                "Evaluation sources do not provide pixel-aligned OCR transcription ground truth."
            ),
        },
        "ingredient_product_database_reference": {
            "evaluated_images": len(ingredient_rows),
            "mean_reference_token_recall": statistics.fmean(
                row["reference_token_recall"]
                for row in ingredient_rows
                if row["reference_token_recall"] is not None
            )
            if any(row["reference_token_recall"] is not None for row in ingredient_rows)
            else None,
            "metric_warning": "Associated product text is not pixel-perfect OCR ground truth.",
        },
        "barcode": {
            "candidate_images": len(barcode_rows),
            "exact_matches": sum(row["exact_match"] is True for row in barcode_rows),
            "metric_warning": (
                "These are decoder-confirmed visible-barcode operational examples selected "
                "from OFF GTIN metadata, not an independent barcode-accuracy sample."
            ),
        },
        "category": {
            role: {
                "evaluated_images": len(rows),
                "reference_matches": sum(row["reference_match"] is True for row in rows),
            }
            for role, rows in sorted(category_rows.items())
        },
        "pipeline_timings": {
            key: timing_summary(values) for key, values in sorted(timings.items())
        },
        "cold_total_ms": float(predictions[0]["timings"]["total_ms"]) if predictions else None,
        "warm_total_ms": timing_summary(
            [float(row["timings"]["total_ms"]) for row in predictions[1:]]
        ),
    }


def evaluate(
    manifest_path: Path,
    output_dir: Path,
    *,
    samples_per_role: int,
    roles: set[str] | None,
    skip_basic_validation: bool,
    disable_ocr: bool,
) -> dict[str, Any]:
    rows = list(read_jsonl(manifest_path))
    if not rows:
        raise RuntimeError("evaluation manifest is empty")
    unknown_roles = set(str(row["dataset_role"]) for row in rows) - set(ROLE_CONFIG)
    if unknown_roles:
        raise RuntimeError(f"unsupported evaluation roles: {sorted(unknown_roles)}")
    output_dir.mkdir(parents=True, exist_ok=True)

    basic_rows: list[dict[str, Any]] = []
    basic_summary: dict[str, Any] = {"status": "SKIPPED"}
    if not skip_basic_validation:
        basic_rows, basic_summary = _basic_validation(rows)
        write_jsonl(output_dir / "validation-results.jsonl", basic_rows)

    selected: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for row in rows:
        role = str(row["dataset_role"])
        if roles is not None and role not in roles:
            continue
        if counts[role] >= samples_per_role:
            continue
        selected.append(row)
        counts[role] += 1

    config = R3Config(allow_model_downloads=False)
    ocr = None
    if disable_ocr:
        ocr = OCROrchestrator(
            config,
            primary=_DisabledOCREngine("PaddleOCR"),
            fallback=_DisabledOCREngine("EasyOCR"),
        )
    pipeline = FoodUnderstandingPipeline(config, ocr=ocr)
    predictions: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, row in enumerate(selected, start=1):
        path = REPO_ROOT / str(row["local_path"])
        input_kind, view_type, _ = ROLE_CONFIG[str(row["dataset_role"])]
        try:
            result = pipeline.scan(
                [
                    ImagePayload(
                        content=path.read_bytes(),
                        filename=path.name,
                        mime_type=_mime_type(path),
                        view_type=view_type,
                    )
                ],
                input_kind=input_kind,
                trace_id=f"r3-real-eval-{row['evaluation_id']}",
            )
            predictions.append(_prediction_row(row, result))
        except Exception as exc:
            failures.append(
                {
                    "evaluation_id": str(row["evaluation_id"]),
                    "reason": f"{type(exc).__name__}:{exc}",
                }
            )
        if index == 1 or index % 10 == 0 or index == len(selected):
            print(f"Processed {index}/{len(selected)} real pipeline images", flush=True)

    write_jsonl(output_dir / "pipeline-results.jsonl", predictions)
    summary = {
        "completed_at": utc_now(),
        "evaluation_manifest": manifest_path.relative_to(REPO_ROOT).as_posix(),
        "evaluation_manifest_sha256": sha256_file(manifest_path),
        "hardware": hardware_summary(),
        "integrity_and_preprocessing": basic_summary,
        "pipeline": {
            "component_evaluation_ocr_disabled": disable_ocr,
            "failed": len(failures),
            "failures": failures,
            "passed": len(predictions),
            "requested_by_role": dict(sorted(counts.items())),
        },
        "results": _aggregate(predictions),
        "source_ground_truth_policy": {
            "ocr_transcriptions_available": False,
            "product_database_text_is_ocr_ground_truth": False,
            "synthetic_or_fabricated_ground_truth_used": False,
        },
    }
    write_json(output_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "data/splits/r3_real_evaluation.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports/r3-real-evaluation",
    )
    parser.add_argument("--samples-per-role", type=int, default=25)
    parser.add_argument(
        "--role",
        action="append",
        choices=sorted(ROLE_CONFIG),
        help="Evaluate only this role; may be repeated.",
    )
    parser.add_argument("--skip-basic-validation", action="store_true")
    parser.add_argument(
        "--disable-ocr",
        action="store_true",
        help="Disable OCR only for isolated detector/barcode component evaluation.",
    )
    args = parser.parse_args()
    if args.samples_per_role < 1:
        parser.error("--samples-per-role must be positive")
    summary = evaluate(
        args.manifest,
        args.output_dir,
        samples_per_role=args.samples_per_role,
        roles=set(args.role) if args.role else None,
        skip_basic_validation=args.skip_basic_validation,
        disable_ocr=args.disable_ocr,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["pipeline"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
