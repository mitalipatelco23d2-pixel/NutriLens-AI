"""Evaluate a frozen nutrition-table model on one explicitly selected split."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import TypedDict

import cv2
import yaml
from ultralytics import YOLO

BoxTuple = tuple[float, float, float, float]


class Prediction(TypedDict):
    box: BoxTuple
    confidence: float


class EvaluationRecord(TypedDict):
    image: str
    ground_truth: list[BoxTuple]
    predictions: list[Prediction]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--split", choices=("val", "test"), required=True)
    parser.add_argument("--thresholds", type=float, nargs="+", required=True)
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--nms-iou", type=float, default=0.50)
    parser.add_argument("--max-detections", type=int, default=3)
    parser.add_argument("--device", default="0")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def iou(a: BoxTuple, b: BoxTuple) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def ground_truth(label_path: Path, width: int, height: int) -> list[BoxTuple]:
    boxes: list[BoxTuple] = []
    for line in label_path.read_text(encoding="utf-8").splitlines():
        class_id, x_center, y_center, box_width, box_height = map(float, line.split())
        if int(class_id) != 0:
            continue
        pixel_width, pixel_height = box_width * width, box_height * height
        center_x, center_y = x_center * width, y_center * height
        boxes.append(
            (
                center_x - pixel_width / 2,
                center_y - pixel_height / 2,
                center_x + pixel_width / 2,
                center_y + pixel_height / 2,
            )
        )
    return boxes


def score(
    records: list[EvaluationRecord], threshold: float, match_iou: float = 0.50
) -> dict[str, int | float]:
    true_positives = false_positives = false_negatives = partial = 0
    matched_ious: list[float] = []
    for record in records:
        gt_boxes = record["ground_truth"]
        predictions = [item for item in record["predictions"] if item["confidence"] >= threshold]
        candidates = sorted(
            (
                (iou(prediction["box"], gt), pred_index, gt_index)
                for pred_index, prediction in enumerate(predictions)
                for gt_index, gt in enumerate(gt_boxes)
            ),
            reverse=True,
        )
        used_predictions: set[int] = set()
        used_ground_truth: set[int] = set()
        for overlap, pred_index, gt_index in candidates:
            if overlap < match_iou:
                break
            if pred_index in used_predictions or gt_index in used_ground_truth:
                continue
            used_predictions.add(pred_index)
            used_ground_truth.add(gt_index)
            matched_ious.append(overlap)
        for gt_index, gt in enumerate(gt_boxes):
            if gt_index in used_ground_truth:
                continue
            best_overlap = max(
                (iou(prediction["box"], gt) for prediction in predictions), default=0.0
            )
            if 0.10 <= best_overlap < match_iou:
                partial += 1
        true_positives += len(used_ground_truth)
        false_positives += len(predictions) - len(used_predictions)
        false_negatives += len(gt_boxes) - len(used_ground_truth)
    precision = true_positives / (true_positives + false_positives or 1)
    recall = true_positives / (true_positives + false_negatives or 1)
    return {
        "threshold": threshold,
        "true_positives": true_positives,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall or 1),
        "mean_matched_iou": sum(matched_ious) / len(matched_ious) if matched_ious else 0.0,
        "correct_detections": true_positives,
        "missed_boxes": false_negatives,
        "partial_detections": partial,
    }


def main() -> None:
    args = parse_args()
    started = time.perf_counter()
    data_root = args.data_root.resolve()
    image_dir = data_root / "images" / args.split
    label_dir = data_root / "labels" / args.split
    images = sorted(
        path
        for path in image_dir.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    if not images:
        raise RuntimeError(f"No images found in {image_dir}")
    minimum_threshold = min(args.thresholds)
    model = YOLO(str(args.weights.resolve()))
    records: list[EvaluationRecord] = []
    predictions = model.predict(
        source=str(image_dir),
        conf=minimum_threshold,
        iou=args.nms_iou,
        max_det=args.max_detections,
        imgsz=args.image_size,
        batch=args.batch,
        device=args.device,
        stream=True,
        verbose=False,
    )
    for result in predictions:
        image_path = Path(result.path)
        height, width = result.orig_shape
        label_path = label_dir / f"{image_path.stem}.txt"
        prediction_boxes: list[Prediction] = [
            {
                "box": (float(xyxy[0]), float(xyxy[1]), float(xyxy[2]), float(xyxy[3])),
                "confidence": float(confidence),
            }
            for xyxy, confidence in zip(
                result.boxes.xyxy.cpu().numpy(),
                result.boxes.conf.cpu().numpy(),
                strict=True,
            )
        ]
        records.append(
            {
                "image": image_path.name,
                "ground_truth": ground_truth(label_path, width, height),
                "predictions": prediction_boxes,
            }
        )

    # Always bind the evaluation YAML to the selected native dataset directory.
    # A copied Windows data.yaml may point at a different dataset or not exist here.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    runtime_yaml = args.output.with_suffix(".data.yaml")
    runtime_yaml.write_text(
        yaml.safe_dump(
            {
                "path": str(data_root),
                "train": "images/train",
                "val": "images/val",
                "test": "images/test",
                "names": {0: "nutrition_table"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    validation = model.val(
        data=str(runtime_yaml),
        split=args.split,
        conf=0.001,
        iou=args.nms_iou,
        max_det=args.max_detections,
        imgsz=args.image_size,
        batch=args.batch,
        device=args.device,
        workers=0,
        plots=False,
        verbose=False,
    )
    payload = {
        "split": args.split,
        "image_count": len(records),
        "annotation_count": sum(len(record["ground_truth"]) for record in records),
        "weights": str(args.weights),
        "weights_sha256": hashlib.sha256(args.weights.read_bytes()).hexdigest(),
        "image_size": args.image_size,
        "nms_iou": args.nms_iou,
        "max_detections": args.max_detections,
        "map50": float(validation.box.map50),
        "map50_95": float(validation.box.map),
        "threshold_metrics": [score(records, threshold) for threshold in args.thresholds],
        "raw_prediction_threshold": minimum_threshold,
        "per_image_predictions": records,
        "elapsed_seconds": time.perf_counter() - started,
        "opencv_version": cv2.__version__,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    console_payload = {
        key: value for key, value in payload.items() if key != "per_image_predictions"
    }
    print(json.dumps(console_payload, indent=2))


if __name__ == "__main__":
    main()
