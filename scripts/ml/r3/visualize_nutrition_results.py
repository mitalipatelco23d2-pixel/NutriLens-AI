"""Create a deterministic mixed success/failure contact sheet from saved predictions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def iou(a: list[float], b: list[float]) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tiles", type=int, default=12)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = json.loads(args.evaluation.read_text(encoding="utf-8"))
    split = payload["split"]
    ranked = []
    for record in payload["per_image_predictions"]:
        predictions = [
            prediction
            for prediction in record["predictions"]
            if prediction["confidence"] >= args.threshold
        ]
        best_overlaps = [
            max((iou(prediction["box"], gt) for prediction in predictions), default=0.0)
            for gt in record["ground_truth"]
        ]
        score = min(best_overlaps, default=0.0)
        ranked.append((score, record, predictions))
    ranked.sort(key=lambda item: (item[0], item[1]["image"]))
    failure_count = min(args.tiles // 2, len(ranked))
    selected = ranked[:failure_count] + ranked[-(args.tiles - failure_count) :]

    tile_width, tile_height = 480, 360
    columns = 3
    rows = (len(selected) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * tile_width, rows * tile_height), "white")
    font = ImageFont.load_default()
    for index, (best_iou, record, predictions) in enumerate(selected):
        source = Image.open(args.data_root / "images" / split / record["image"]).convert("RGB")
        scale = min(tile_width / source.width, (tile_height - 30) / source.height)
        resized = source.resize(
            (max(1, round(source.width * scale)), max(1, round(source.height * scale)))
        )
        tile = Image.new("RGB", (tile_width, tile_height), "white")
        offset_x = (tile_width - resized.width) // 2
        offset_y = 30 + (tile_height - 30 - resized.height) // 2
        tile.paste(resized, (offset_x, offset_y))
        draw = ImageDraw.Draw(tile)
        draw.text(
            (5, 5),
            f"{record['image']}  best IoU={best_iou:.3f}  pred={len(predictions)}",
            fill="black",
            font=font,
        )
        for gt in record["ground_truth"]:
            draw.rectangle(
                tuple(
                    offset_x + value * scale if axis % 2 == 0 else offset_y + value * scale
                    for axis, value in enumerate(gt)
                ),
                outline="lime",
                width=3,
            )
        for prediction in predictions:
            box = prediction["box"]
            draw.rectangle(
                tuple(
                    offset_x + value * scale if axis % 2 == 0 else offset_y + value * scale
                    for axis, value in enumerate(box)
                ),
                outline="red",
                width=2,
            )
        sheet.paste(tile, ((index % columns) * tile_width, (index // columns) * tile_height))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(args.output, quality=92)


if __name__ == "__main__":
    main()
