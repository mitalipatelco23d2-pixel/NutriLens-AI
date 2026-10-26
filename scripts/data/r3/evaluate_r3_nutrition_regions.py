"""Evaluate R3 OCR-layout nutrition regions against official OFF boxes."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import statistics
import sys
from pathlib import Path
from typing import Any

import cv2

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ai.food_understanding.extraction import extract_nutrition
from ai.food_understanding.schemas import Box
from ai.ocr.paddle_engine import (
    PADDLE_DETECTION_MODEL,
    PADDLE_RECOGNITION_MODEL,
    PaddleOCREngine,
)
from ai.vision.regions import NUTRITION_TERMS, text_region
from scripts.data.r3.common import REPO_ROOT, read_jsonl, sha256_file, utc_now, write_json
from scripts.data.r3.evaluate_r3_real_pipeline import _box_iou, detection_counts, timing_summary


def _reference_boxes(row: dict[str, Any]) -> list[Box]:
    return [Box.model_validate(box["pixels_xywh"]) for box in row["ground_truth"].get("boxes", [])]


def _resize(image: Any, *, max_side: int) -> tuple[Any, float]:
    height, width = image.shape[:2]
    scale = min(1.0, max_side / max(height, width))
    if scale == 1.0:
        return image, scale
    return (
        cv2.resize(
            image,
            (max(1, round(width * scale)), max(1, round(height * scale))),
            interpolation=cv2.INTER_AREA,
        ),
        scale,
    )


def run(
    *,
    manifest: Path,
    model_root: Path,
    output: Path,
    count: int,
    max_side: int,
) -> dict[str, Any]:
    rows = [row for row in read_jsonl(manifest) if row["dataset_role"] == "NUTRITION_PANEL"][:count]
    if len(rows) != count:
        raise RuntimeError(f"only {len(rows)} of {count} nutrition rows available")
    engine = PaddleOCREngine(
        device="cpu",
        allow_downloads=False,
        model_storage_directory=model_root,
    )
    results: list[dict[str, Any]] = []
    all_ious: list[float] = []
    true_positive = false_positive = false_negative = 0
    partial_detections = 0
    successful_images = 0
    for index, row in enumerate(rows, start=1):
        image_path = REPO_ROOT / row["local_path"]
        if sha256_file(image_path) != row["sha256"]:
            raise RuntimeError(f"checksum mismatch: {image_path}")
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"OpenCV could not decode: {image_path}")
        resized, scale = _resize(image, max_side=max_side)
        attempt = engine.recognize(resized, ["en"])
        prediction_region = text_region(
            attempt.lines,
            terms=NUTRITION_TERMS,
            region_type="nutrition_table",
            view_id=str(row["evaluation_id"]),
        )
        predictions: list[Box] = []
        if prediction_region is not None:
            predicted = prediction_region.bounding_box
            predictions.append(
                Box(
                    x=predicted.x / scale,
                    y=predicted.y / scale,
                    width=predicted.width / scale,
                    height=predicted.height / scale,
                )
            )
        references = _reference_boxes(row)
        tp, fp, fn, matched_ious = detection_counts(references, predictions)
        best_ious = [
            max(
                (_box_iou(reference, prediction) for prediction in predictions),
                default=0.0,
            )
            for reference in references
        ]
        true_positive += tp
        false_positive += fp
        false_negative += fn
        all_ious.extend(matched_ious)
        partial_detections += sum(0 < iou < 0.5 for iou in best_ious)
        successful_images += int(tp > 0)
        extraction = (
            extract_nutrition(attempt.lines, prediction_region)
            if prediction_region is not None
            else None
        )
        results.append(
            {
                "confidence": attempt.confidence,
                "elapsed_ms": attempt.elapsed_ms,
                "error_code": attempt.error_code,
                "evaluation_id": row["evaluation_id"],
                "false_negative": fn,
                "false_positive": fp,
                "ground_truth_box_count": len(references),
                "image_id": row["image_id"],
                "matched_ious": matched_ious,
                "method": prediction_region.method.value if prediction_region is not None else None,
                "ocr_line_count": len(attempt.lines),
                "per_reference_best_ious": best_ious,
                "predicted_box_count": len(predictions),
                "resize_scale": scale,
                "status": attempt.status,
                "structured_nutrition_row_count": len(extraction.table_rows)
                if extraction is not None
                else 0,
                "true_positive": tp,
            }
        )
        if index == 1 or index % 5 == 0 or index == len(rows):
            print(f"Evaluated {index}/{len(rows)} nutrition images", flush=True)

    payload = {
        "completed_at": utc_now(),
        "count": len(results),
        "device": "cpu",
        "ground_truth_type": "OFF_MANUALLY_REVIEWED_BOUNDING_BOX",
        "iou_threshold": 0.5,
        "language": "en",
        "manifest": manifest.relative_to(REPO_ROOT).as_posix(),
        "manifest_sha256": sha256_file(manifest),
        "max_input_side": max_side,
        "method": "R3_PADDLEOCR_KEYWORD_LAYOUT_REGION",
        "model_names": {
            "detection": PADDLE_DETECTION_MODEL,
            "recognition": PADDLE_RECOGNITION_MODEL,
        },
        "ocr_error_rates": {
            "cer": None,
            "wer": None,
            "reason": "OFF region annotations do not include OCR transcriptions.",
        },
        "paddle_version": importlib.metadata.version("paddlepaddle"),
        "paddleocr_version": importlib.metadata.version("paddleocr"),
        "precision": true_positive / (true_positive + false_positive)
        if true_positive + false_positive
        else None,
        "recall": true_positive / (true_positive + false_negative)
        if true_positive + false_negative
        else None,
        "mean_matched_iou": statistics.fmean(all_ious) if all_ious else None,
        "detection_success_images": successful_images,
        "detection_success_rate": successful_images / len(results) if results else None,
        "method_counts": {
            "HEURISTIC": 0,
            "MANUAL": 0,
            "MODEL": 0,
            "OCR_LAYOUT": sum(row["predicted_box_count"] for row in results),
        },
        "partial_detections": partial_detections,
        "results": results,
        "timing": timing_summary([float(row["elapsed_ms"]) for row in results]),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
    }
    write_json(output, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "data/splits/r3_real_evaluation.jsonl",
    )
    parser.add_argument(
        "--model-root",
        type=Path,
        default=REPO_ROOT / ".model-cache/r3/paddle",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "reports/r3-real-evaluation/nutrition-regions.json",
    )
    parser.add_argument("--count", type=int, default=25)
    parser.add_argument("--max-side", type=int, default=1600)
    args = parser.parse_args()
    if args.count < 1 or args.max_side < 64:
        parser.error("--count must be positive and --max-side must be at least 64")
    payload = run(
        manifest=args.manifest.resolve(),
        model_root=args.model_root.resolve(),
        output=args.output.resolve(),
        count=args.count,
        max_side=args.max_side,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
