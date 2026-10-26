"""Create leakage-safe YOLOv11 nutrition-table train/validation/test assets."""
# ruff: noqa: E501

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import numpy as np

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.data.r3.common import REPO_ROOT, read_jsonl, sha256_file, write_json, write_jsonl

SEED = "nutrilens-r3-nutrition-yolo-v1"
SPLITS = (("train", 0.75), ("val", 0.125), ("test", 0.125))
SOURCE = REPO_ROOT / "data/external/r3/openfoodfacts/nutrition-table-detection"
OUTPUT = REPO_ROOT / "data/processed/r3-real-v1.0.0/yolo-nutrition-table-v1"


def _rank(value: str) -> str:
    return hashlib.sha256(f"{SEED}:{value}".encode()).hexdigest()


def _groups(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        group = str(row.get("barcode") or f"image:{row['image_id']}")
        groups.setdefault(group, []).append(row)
    return groups


def _assign(groups: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    target = {
        name: round(sum(len(rows) for rows in groups.values()) * ratio) for name, ratio in SPLITS
    }
    assigned: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for group, rows in sorted(groups.items(), key=lambda item: _rank(item[0])):
        split = min(
            (name for name, _ in SPLITS), key=lambda name: counts[name] / max(target[name], 1)
        )
        assigned[group] = split
        counts[split] += len(rows)
    return assigned


def _label(row: dict[str, Any]) -> str:
    lines: list[str] = []
    for box in row["source_boxes"]:
        x, y, width, height = (
            float(box["pixels_xywh"][key]) for key in ("x", "y", "width", "height")
        )
        image_width, image_height = float(row["width"]), float(row["height"])
        center_x, center_y = (x + width / 2) / image_width, (y + height / 2) / image_height
        normalized_width, normalized_height = width / image_width, height / image_height
        values = (center_x, center_y, normalized_width, normalized_height)
        if not all(0 < value <= 1 for value in values):
            raise ValueError(f"invalid normalized label for {row['image_id']}: {values}")
        lines.append("0 " + " ".join(f"{value:.6f}" for value in values))
    if not lines:
        raise ValueError(f"nutrition source row has no boxes: {row['image_id']}")
    return "\n".join(lines) + "\n"


def _copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256_file(source) != sha256_file(target):
            raise RuntimeError(f"refusing to replace mismatched exported image: {target}")
        return
    shutil.copy2(source, target)


def _contact_sheet(rows: list[dict[str, Any]], output: Path) -> None:
    tiles: list[np.ndarray[Any, Any]] = []
    for row in rows[:12]:
        image = cv2.imread(str(REPO_ROOT / row["local_path"]), cv2.IMREAD_COLOR)
        if image is None:
            raise RuntimeError(f"cannot render {row['local_path']}")
        for box in row["source_boxes"]:
            values = box["pixels_xywh"]
            x, y, width, height = (
                round(float(values[key])) for key in ("x", "y", "width", "height")
            )
            cv2.rectangle(image, (x, y), (x + width, y + height), (0, 255, 0), 4)
        scale = min(320 / image.shape[1], 220 / image.shape[0])
        tile = cv2.resize(image, (round(image.shape[1] * scale), round(image.shape[0] * scale)))
        tiles.append(
            cv2.copyMakeBorder(
                tile, 0, 220 - tile.shape[0], 0, 320 - tile.shape[1], cv2.BORDER_CONSTANT
            )
        )
    contact_rows = [cv2.hconcat(tiles[index : index + 4]) for index in range(0, len(tiles), 4)]
    canvas = cv2.vconcat(contact_rows)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), canvas):
        raise RuntimeError(f"failed writing contact sheet: {output}")


def build(output: Path) -> dict[str, Any]:
    rows = list(read_jsonl(SOURCE / "manifests/source-images.jsonl"))
    groups = _groups(rows)
    assignments = _assign(groups)
    split_rows: dict[str, list[dict[str, Any]]] = {name: [] for name, _ in SPLITS}
    for group, grouped_rows in groups.items():
        split_rows[assignments[group]].extend(grouped_rows)
    for split, rows_for_split in split_rows.items():
        rows_for_split.sort(key=lambda row: str(row["image_id"]))
        for row in rows_for_split:
            suffix = Path(str(row["local_path"])).suffix
            _copy(
                REPO_ROOT / row["local_path"],
                output / "images" / split / f"{row['image_id']}{suffix}",
            )
            label_path = output / "labels" / split / f"{row['image_id']}.txt"
            label_path.parent.mkdir(parents=True, exist_ok=True)
            label_path.write_text(_label(row), encoding="utf-8")
            row["yolo_split"] = split
        write_jsonl(REPO_ROOT / f"data/splits/r3_nutrition_detector_{split}.jsonl", rows_for_split)
    data_yaml = (
        "path: "
        + output.as_posix()
        + "\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: nutrition_table\n"
    )
    (output / "data.yaml").write_text(data_yaml, encoding="utf-8")
    _contact_sheet(
        split_rows["train"], REPO_ROOT / "reports/r3-real-evaluation/nutrition-yolo-annotations.jpg"
    )
    all_products = {
        split: {str(row.get("barcode") or f"image:{row['image_id']}") for row in values}
        for split, values in split_rows.items()
    }
    leakage = any(
        all_products[first] & all_products[second]
        for first in all_products
        for second in all_products
        if first < second
    )
    summary = {
        "seed": SEED,
        "grouping_rule": "barcode else image_id",
        "leakage": leakage,
        "splits": {
            split: {
                "images": len(values),
                "annotations": sum(len(row["source_boxes"]) for row in values),
                "products": len(all_products[split]),
                "manifest_sha256": sha256_file(
                    REPO_ROOT / f"data/splits/r3_nutrition_detector_{split}.jsonl"
                ),
            }
            for split, values in split_rows.items()
        },
    }
    write_json(output / "split-summary.json", summary)
    if leakage:
        raise RuntimeError("barcode leakage detected")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.output.resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
