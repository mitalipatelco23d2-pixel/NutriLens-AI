"""Execute frozen PaddleOCR on source-annotated real OFF nutrition panels."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import cv2

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ai.food_understanding.schemas import PreprocessProfile
from ai.ocr.paddle_engine import (
    PADDLE_DETECTION_MODEL,
    PADDLE_RECOGNITION_MODEL,
    PaddleOCREngine,
)
from ai.vision.preprocessing import preprocess
from scripts.data.r3.common import (
    REPO_ROOT,
    artifact_rows,
    read_jsonl,
    sha256_file,
    tree_digest,
    utc_now,
    write_json,
)

DEFAULT_MANIFEST = (
    REPO_ROOT
    / "data/external/r3/openfoodfacts/nutrition-table-detection/manifests/source-images.jsonl"
)
DEFAULT_MODEL_ROOT = REPO_ROOT / ".model-cache/r3/paddle"


def _crop_panel(image: Any, row: dict[str, Any]) -> Any:
    source_boxes = row.get("source_boxes", [])
    if not source_boxes:
        raise RuntimeError("source row has no nutrition-table box")
    box = source_boxes[0]["pixels_xywh"]
    height, width = image.shape[:2]
    x1 = max(0, min(width - 1, int(box["x"])))
    y1 = max(0, min(height - 1, int(box["y"])))
    x2 = max(x1 + 1, min(width, int(box["x"] + box["width"])))
    y2 = max(y1 + 1, min(height, int(box["y"] + box["height"])))
    return image[y1:y2, x1:x2].copy()


def run(
    *,
    manifest: Path,
    model_root: Path,
    output: Path,
    count: int,
) -> dict[str, Any]:
    rows = [row for row in read_jsonl(manifest) if row["source_split"] == "val"][:count]
    if len(rows) != count:
        raise RuntimeError(f"only {len(rows)} of {count} requested validation images available")

    model_artifacts = artifact_rows(model_root, exclude_parts={".cache"})
    if not model_artifacts:
        raise RuntimeError(f"PaddleOCR model cache is empty: {model_root}")
    initialized = time.perf_counter()
    engine = PaddleOCREngine(
        device="cpu",
        allow_downloads=False,
        model_storage_directory=model_root,
    )
    constructor_ms = (time.perf_counter() - initialized) * 1000
    results: list[dict[str, Any]] = []
    for row in rows:
        image_path = REPO_ROOT / row["local_path"]
        if sha256_file(image_path) != row["sha256"]:
            raise RuntimeError(f"source checksum mismatch: {image_path}")
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"OpenCV could not decode: {image_path}")
        crop = _crop_panel(image, row)
        processed = preprocess(crop, PreprocessProfile.NUTRITION_TABLE)
        attempt = engine.recognize(processed.image, ["en"])
        results.append(
            {
                "confidence": attempt.confidence,
                "elapsed_ms": attempt.elapsed_ms,
                "engine": attempt.engine,
                "error_code": attempt.error_code,
                "image_id": row["image_id"],
                "image_sha256": row["sha256"],
                "language": "en",
                "line_count": len(attempt.lines),
                "preprocessing_ms": processed.metadata.elapsed_ms,
                "source_dataset": row["source_dataset"],
                "source_revision": row["source_revision"],
                "source_split": row["source_split"],
                "status": attempt.status,
                "text": "\n".join(line.text for line in attempt.lines),
            }
        )
    payload = {
        "completed_at": utc_now(),
        "constructor_ms": constructor_ms,
        "device": "cpu",
        "hardware": {
            "machine": platform.machine(),
            "operating_system": platform.platform(),
            "processor": platform.processor(),
            "python": platform.python_version(),
        },
        "image_count": len(results),
        "language": "en",
        "manifest": manifest.relative_to(REPO_ROOT).as_posix(),
        "manifest_sha256": sha256_file(manifest),
        "model_artifact_count": len(model_artifacts),
        "model_cache": model_root.relative_to(REPO_ROOT).as_posix(),
        "model_names": {
            "detection": PADDLE_DETECTION_MODEL,
            "recognition": PADDLE_RECOGNITION_MODEL,
        },
        "runtime_configuration": {
            "document_orientation": False,
            "document_unwarping": False,
            "enable_mkldnn": False,
            "textline_orientation": False,
        },
        "model_tree_sha256": tree_digest(model_artifacts),
        "paddle_version": importlib.metadata.version("paddlepaddle"),
        "paddleocr_version": importlib.metadata.version("paddleocr"),
        "results": results,
        "successful_images": sum(row["status"] == "SUCCESS" for row in results),
        "warm_inference_timing_ms": {
            "count": max(0, len(results) - 1),
            "mean": statistics.fmean(row["elapsed_ms"] for row in results[1:])
            if len(results) > 1
            else None,
            "median": statistics.median(row["elapsed_ms"] for row in results[1:])
            if len(results) > 1
            else None,
        },
    }
    write_json(output, payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "reports/r3-real-evaluation/paddleocr-smoke.json",
    )
    parser.add_argument("--count", type=int, default=5)
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count must be positive")
    payload = run(
        manifest=args.manifest.resolve(),
        model_root=args.model_root.resolve(),
        output=args.output.resolve(),
        count=args.count,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["successful_images"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
