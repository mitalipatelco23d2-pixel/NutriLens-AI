"""Compare the custom YOLO11n PyTorch checkpoint with its static ONNX export."""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

import psutil
from ultralytics import YOLO


def _digest(path: Path) -> str:
    value = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def _boxes(result: Any) -> list[dict[str, Any]]:
    if result.boxes is None:
        return []
    coordinates = result.boxes.xyxy.cpu().numpy().tolist()
    confidences = result.boxes.conf.cpu().numpy().tolist()
    classes = result.boxes.cls.cpu().numpy().tolist()
    values = [
        {"xyxy": box, "confidence": float(confidence), "class_id": int(class_id)}
        for box, confidence, class_id in zip(coordinates, confidences, classes, strict=True)
    ]
    return sorted(values, key=lambda item: item["confidence"], reverse=True)


def _iou(first: list[float], second: list[float]) -> float:
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(round((len(ordered) - 1) * percentile), len(ordered) - 1)
    return ordered[index]


def _predict(model: YOLO, image: Path) -> tuple[list[dict[str, Any]], float, int]:
    started = time.perf_counter()
    result = model.predict(source=str(image), imgsz=640, conf=0.30, device="cpu", verbose=False)[0]
    elapsed_ms = (time.perf_counter() - started) * 1000
    rss = psutil.Process(os.getpid()).memory_info().rss
    return _boxes(result), elapsed_ms, rss


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pt", type=Path, required=True)
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--milk", type=Path)
    parser.add_argument("--sample-size", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    dataset_images = sorted(
        path
        for path in args.images.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )[: args.sample_size]
    images = ([args.milk] if args.milk and args.milk.exists() else []) + dataset_images
    if not images:
        raise SystemExit("No benchmark images found.")

    pt_model = YOLO(str(args.pt), task="detect")
    onnx_model = YOLO(str(args.onnx), task="detect")
    comparisons: list[dict[str, Any]] = []
    pt_latencies: list[float] = []
    onnx_latencies: list[float] = []
    peak_rss = psutil.Process(os.getpid()).memory_info().rss

    for index, image in enumerate(images):
        pt_boxes, pt_ms, pt_rss = _predict(pt_model, image)
        onnx_boxes, onnx_ms, onnx_rss = _predict(onnx_model, image)
        pt_latencies.append(pt_ms)
        onnx_latencies.append(onnx_ms)
        peak_rss = max(peak_rss, pt_rss, onnx_rss)
        paired = list(zip(pt_boxes, onnx_boxes, strict=False))
        ious = [_iou(pt["xyxy"], onnx["xyxy"]) for pt, onnx in paired]
        confidence_deltas = [abs(pt["confidence"] - onnx["confidence"]) for pt, onnx in paired]
        comparisons.append(
            {
                "image": image.name,
                "fixture": (
                    "milk_public_fixture" if index == 0 and image == args.milk else "held_out"
                ),
                "pt_detections": len(pt_boxes),
                "onnx_detections": len(onnx_boxes),
                "count_equal": len(pt_boxes) == len(onnx_boxes),
                "minimum_paired_iou": min(ious) if ious else None,
                "maximum_confidence_delta": max(confidence_deltas) if confidence_deltas else None,
                "pt_ms": pt_ms,
                "onnx_ms": onnx_ms,
            }
        )

    warm_pt = pt_latencies[1:] if len(pt_latencies) > 1 else pt_latencies
    warm_onnx = onnx_latencies[1:] if len(onnx_latencies) > 1 else onnx_latencies
    report = {
        "schema_version": 1,
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "purpose": (
            "Android ONNX export equivalence and CPU feasibility; "
            "not a production acceptance claim."
        ),
        "machine": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
        },
        "models": {
            "pytorch": {
                "path": str(args.pt),
                "bytes": args.pt.stat().st_size,
                "sha256": _digest(args.pt),
            },
            "onnx": {
                "path": str(args.onnx),
                "bytes": args.onnx.stat().st_size,
                "sha256": _digest(args.onnx),
                "opset": 17,
                "input_shape": [1, 3, 640, 640],
                "dynamic": False,
                "quantized": False,
            },
        },
        "sample_count": len(images),
        "cold_ms": {"pytorch": pt_latencies[0], "onnx": onnx_latencies[0]},
        "warm_ms": {
            "pytorch_p50": statistics.median(warm_pt),
            "pytorch_p95": _percentile(warm_pt, 0.95),
            "onnx_p50": statistics.median(warm_onnx),
            "onnx_p95": _percentile(warm_onnx, 0.95),
        },
        "peak_process_rss_bytes_sampled": peak_rss,
        "equivalence": {
            "equal_detection_count_images": sum(item["count_equal"] for item in comparisons),
            "all_detection_counts_equal": all(item["count_equal"] for item in comparisons),
            "minimum_paired_iou": min(
                item["minimum_paired_iou"]
                for item in comparisons
                if item["minimum_paired_iou"] is not None
            ),
            "maximum_confidence_delta": max(
                item["maximum_confidence_delta"]
                for item in comparisons
                if item["maximum_confidence_delta"] is not None
            ),
        },
        "comparisons": comparisons,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["warm_ms"], indent=2))
    print(json.dumps(report["equivalence"], indent=2))
    print(args.output)


if __name__ == "__main__":
    main()
