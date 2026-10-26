"""Bounded real-image cardinal-orientation evaluation of the production wrapper."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2

from ai.food_understanding.config import R3Config
from ai.vision.nutrition_yolo_engine import NutritionYOLOEngine
from ai.vision.preprocessing import rotate_cardinal

BoxTuple = tuple[float, float, float, float]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def iou(a: BoxTuple, b: BoxTuple) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def ground_truth(path: Path, width: int, height: int) -> list[BoxTuple]:
    boxes: list[BoxTuple] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        _, cx, cy, bw, bh = map(float, line.split())
        boxes.append(
            (
                (cx - bw / 2) * width,
                (cy - bh / 2) * height,
                (cx + bw / 2) * width,
                (cy + bh / 2) * height,
            )
        )
    return boxes


def rotate_box(box: BoxTuple, rotation: int, width: int, height: int) -> BoxTuple:
    x1, y1, x2, y2 = box
    if rotation == 0:
        return box
    if rotation == 90:
        return (height - y2, x1, height - y1, x2)
    if rotation == 180:
        return (width - x2, height - y2, width - x1, height - y1)
    if rotation == 270:
        return (y1, width - x2, y2, width - x1)
    raise ValueError(rotation)


def main() -> None:
    args = parse_args()
    image_dir = args.data_root / "images" / "val"
    label_dir = args.data_root / "labels" / "val"
    candidates = []
    for image_path in sorted(image_dir.iterdir()):
        label_path = label_dir / f"{image_path.stem}.txt"
        if len(label_path.read_text(encoding="utf-8").splitlines()) == 1:
            candidates.append((image_path, label_path))
        if len(candidates) == args.samples:
            break
    engine = NutritionYOLOEngine(R3Config(device="cpu"))
    records = []
    started = time.perf_counter()
    for image_path, label_path in candidates:
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"Cannot decode {image_path}")
        height, width = image.shape[:2]
        original_gt = ground_truth(label_path, width, height)[0]
        for rotation in (0, 90, 180, 270):
            oriented = rotate_cardinal(image, rotation)
            expected = rotate_box(original_gt, rotation, width, height)
            inference = engine.infer(oriented)
            overlaps = [
                iou(
                    (
                        detection.bounding_box.x,
                        detection.bounding_box.y,
                        detection.bounding_box.x + detection.bounding_box.width,
                        detection.bounding_box.y + detection.bounding_box.height,
                    ),
                    expected,
                )
                for detection in inference.detections
            ]
            records.append(
                {
                    "image": image_path.name,
                    "input_rotation": rotation,
                    "wrapper_retry_rotation": inference.rotation_degrees,
                    "detections": len(inference.detections),
                    "best_iou": max(overlaps, default=0.0),
                    "success_iou_0_5": max(overlaps, default=0.0) >= 0.5,
                    "max_confidence": max(
                        (item.confidence for item in inference.detections), default=None
                    ),
                    "elapsed_ms": inference.elapsed_ms,
                    "error_code": inference.error_code,
                }
            )
    payload = {
        "images": len(candidates),
        "orientation_cases": len(records),
        "successful_cases": sum(row["success_iou_0_5"] for row in records),
        "elapsed_seconds": time.perf_counter() - started,
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
