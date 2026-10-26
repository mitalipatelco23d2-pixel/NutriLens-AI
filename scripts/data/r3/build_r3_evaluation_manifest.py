"""Build a deterministic, product-disjoint real R3 evaluation manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import cv2

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from ai.vision.barcode_qr import decode_barcodes
from scripts.data.r3.common import REPO_ROOT, read_jsonl, write_json, write_jsonl

SEED = "nutrilens-r3-real-evaluation-v1"
BARCODE_TARGET = 50
BARCODE_MAX_ATTEMPTS = 500

ROOTS = {
    "nutrition": REPO_ROOT / "data/external/r3/openfoodfacts/nutrition-table-detection",
    "front": REPO_ROOT / "data/external/r3/openfoodfacts/front-image-classification",
    "product": REPO_ROOT / "data/external/r3/openfoodfacts/product-images",
    "grocery": REPO_ROOT / "data/external/r3/grocery-store-dataset",
    "meal": REPO_ROOT / "data/external/r3/food-101",
}


def _rank(row: dict[str, Any]) -> str:
    value = f"{SEED}:{row['source_dataset']}:{row['image_id']}"
    return hashlib.sha256(value.encode()).hexdigest()


def _select(
    rows: Iterable[dict[str, Any]],
    count: int,
    *,
    used_products: set[str] | None = None,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    used = used_products if used_products is not None else set()
    for row in sorted(rows, key=_rank):
        product = str(row.get("barcode") or "")
        if product and product in used:
            continue
        selected.append(row)
        if product:
            used.add(product)
        if len(selected) == count:
            break
    if len(selected) < count:
        raise RuntimeError(f"only {len(selected)} of {count} requested evaluation rows available")
    return selected


def _manifest(root: Path) -> list[dict[str, Any]]:
    path = root / "manifests/source-images.jsonl"
    if not path.is_file():
        raise RuntimeError(f"missing source manifest: {path}")
    return list(read_jsonl(path))


def _select_visible_barcodes(
    rows: Iterable[dict[str, Any]], *, used_products: set[str]
) -> tuple[list[dict[str, Any]], int]:
    """Select actual barcode-visible examples without inferring visibility from metadata.

    The local decoder matching the OFF product GTIN is retained as an observability
    criterion.  It is deliberately recorded in the manifest so this operational
    subset is never reported as an independent barcode-accuracy sample.
    """

    selected: list[dict[str, Any]] = []
    attempted = 0
    for row in sorted(rows, key=_rank):
        barcode = str(row.get("barcode") or "")
        if not barcode or barcode in used_products:
            continue
        image_path = REPO_ROOT / str(row["local_path"])
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        attempted += 1
        if image is None:
            continue
        decoded, _ = decode_barcodes(image, view_id=str(row["image_id"]))
        if not any(item.value == barcode and item.checksum_valid is True for item in decoded):
            if attempted >= BARCODE_MAX_ATTEMPTS:
                break
            continue
        selected.append(row)
        used_products.add(barcode)
        if len(selected) == BARCODE_TARGET or attempted >= BARCODE_MAX_ATTEMPTS:
            break
    return selected, attempted


def _entry(row: dict[str, Any], role: str, ground_truth: dict[str, Any]) -> dict[str, Any]:
    evaluation_hash = hashlib.sha256((role + ":" + str(row["image_id"])).encode()).hexdigest()
    return {
        "evaluation_id": f"r3eval-{evaluation_hash[:16]}",
        "purpose": "R3_EVALUATION",
        "dataset_role": role,
        "image_id": row["image_id"],
        "local_path": row["local_path"],
        "sha256": row["sha256"],
        "width": row["width"],
        "height": row["height"],
        "source_dataset": row["source_dataset"],
        "source_revision": row.get("source_revision") or row.get("source_version"),
        "source_split": row.get("source_split"),
        "source_record_id": row.get("source_record_id") or row.get("image_id"),
        "source_url": row.get("original_url") or row.get("source_dataset"),
        "product_barcode": row.get("barcode"),
        "license": row["license"],
        "manual_review_status": "PENDING_NUTRILENS_REVIEW",
        "retention_status": "LOCAL_EXTERNAL_DATASET_ASSET",
        "ground_truth": ground_truth,
    }


def build(output: Path) -> dict[str, Any]:
    used_products: set[str] = set()
    nutrition_rows = _manifest(ROOTS["nutrition"])
    nutrition = _select(
        (row for row in nutrition_rows if row["source_split"] == "val"),
        100,
        used_products=used_products,
    )
    front_rows = _manifest(ROOTS["front"])
    fronts = _select(
        (
            row
            for row in front_rows
            if row["source_split"] == "test" and row["category_name"] == "front"
        ),
        100,
        used_products=used_products,
    )
    difficult = _select(
        (
            row
            for row in front_rows
            if row["source_split"] == "test" and row["category_name"] == "other"
        ),
        25,
        used_products=used_products,
    )
    product_rows = _manifest(ROOTS["product"])
    ingredients = _select(
        (row for row in product_rows if row["image_role"] == "ingredients"),
        100,
        used_products=used_products,
    )
    barcode_candidates, barcode_attempted = _select_visible_barcodes(
        (row for row in product_rows if row["image_role"] in {"other", "packaging", "front"}),
        used_products=used_products,
    )
    grocery_rows = _manifest(ROOTS["grocery"])
    groceries = _select((row for row in grocery_rows if row["source_split"] == "test"), 100)
    meal_rows = _manifest(ROOTS["meal"])
    meals = _select((row for row in meal_rows if row["source_split"] == "test"), 100)

    references_path = ROOTS["product"] / "manifests/product-references.jsonl"
    references = {str(row["barcode"]): row for row in read_jsonl(references_path)}
    entries: list[dict[str, Any]] = []
    for row in nutrition:
        entries.append(
            _entry(
                row,
                "NUTRITION_PANEL",
                {
                    "boxes": row["source_boxes"],
                    "type": "OFF_MANUALLY_REVIEWED_BOUNDING_BOX",
                },
            )
        )
    for row in fronts + difficult:
        entries.append(
            _entry(
                row,
                "PACKAGE_FRONT" if row["category_name"] == "front" else "DIFFICULT_PACKAGE",
                {
                    "class": row["category_name"],
                    "type": "OFF_MANUALLY_REVIEWED_CLASS",
                },
            )
        )
    for row in ingredients:
        reference = references.get(str(row["barcode"]), {})
        entries.append(
            _entry(
                row,
                "INGREDIENT_PANEL",
                {
                    "ingredient_text": reference.get("ingredients_reference"),
                    "type": "PRODUCT_DATABASE_REFERENCE",
                },
            )
        )
    for row in barcode_candidates:
        entries.append(
            _entry(
                row,
                "BARCODE_CANDIDATE",
                {
                    "barcode": row["barcode"],
                    "selection_warning": (
                        "Selected only after local OpenCV decode matched the OFF GTIN; "
                        "this is a visibility/operational subset, not an independent "
                        "barcode-accuracy sample."
                    ),
                    "type": "OFF_PRODUCT_BARCODE_METADATA_MATCHED_BY_LOCAL_DECODE",
                    "visibility_evidence": "LOCAL_OPENCV_DECODE_MATCHED_METADATA",
                },
            )
        )
    for row in groceries:
        entries.append(
            _entry(
                row,
                "GROCERY_ITEM",
                {
                    "coarse_label": row["coarse_label"],
                    "fine_label": row["fine_label"],
                    "fine_name_from_path": row["fine_name_from_path"],
                    "type": "OFFICIAL_CLASS_LABEL",
                },
            )
        )
    for row in meals:
        entries.append(
            _entry(
                row,
                "PREPARED_MEAL",
                {"class": row["class_name"], "type": "OFFICIAL_DISH_CLASS"},
            )
        )
    entries.sort(key=lambda row: str(row["evaluation_id"]))
    write_jsonl(output, entries)
    counts: dict[str, int] = {}
    for row in entries:
        role = str(row["dataset_role"])
        counts[role] = counts.get(role, 0) + 1
    summary = {
        "counts": counts,
        "item_count": len(entries),
        "barcode_visibility_selection": {
            "attempted_source_images": barcode_attempted,
            "matched_visible_images": len(barcode_candidates),
            "method": "LOCAL_OPENCV_DECODE_MATCHED_OFF_GTIN",
            "target": BARCODE_TARGET,
        },
        "myfoodrepo_multi_food_status": "MANUAL_ACCESS_REQUIRED",
        "product_disjoint_selection": True,
        "seed": SEED,
    }
    write_json(output.with_suffix(".summary.json"), summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "data/splits/r3_real_evaluation.jsonl",
    )
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
