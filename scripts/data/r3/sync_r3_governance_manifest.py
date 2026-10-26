"""Sync completed R3 acquisition summaries into the canonical acquisition manifest."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.data.r3.common import REPO_ROOT, relative_to_repo, sha256_file, write_csv

FIELDS = [
    "Dataset ID",
    "Filename",
    "Source URL",
    "Download date UTC",
    "Version",
    "Size bytes",
    "SHA-256",
    "Local path",
    "Privacy status",
]
SOURCES = {
    "OFF-R3-NUTRITION-TABLE-DETECTION": (
        REPO_ROOT
        / "data/external/r3/openfoodfacts/nutrition-table-detection/acquisition-summary.json",
        "https://huggingface.co/datasets/openfoodfacts/nutrition-table-detection",
    ),
    "OFF-R3-FRONT-IMAGE-CLASSIFICATION": (
        REPO_ROOT
        / "data/external/r3/openfoodfacts/front-image-classification/acquisition-summary.json",
        "https://huggingface.co/datasets/openfoodfacts/front_image_classification",
    ),
    "OFF-R3-PRODUCT-IMAGE-CORPUS": (
        REPO_ROOT / "data/external/r3/openfoodfacts/product-images/acquisition-summary.json",
        "https://huggingface.co/datasets/openfoodfacts/product-database",
    ),
    "GROCERY-STORE-R3": (
        REPO_ROOT / "data/external/r3/grocery-store-dataset/acquisition-summary.json",
        "https://github.com/marcusklasson/GroceryStoreDataset",
    ),
    "FOOD-101-R3": (
        REPO_ROOT / "data/external/r3/food-101/acquisition-summary.json",
        "https://data.vision.ee.ethz.ch/cvl/food-101.tar.gz",
    ),
}


def _summary_row(dataset_id: str, path: Path, source_url: str) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"missing completed acquisition summary: {path}")
    summary = json.loads(path.read_text(encoding="utf-8"))
    if summary.get("dataset_id") != dataset_id:
        raise RuntimeError(f"dataset ID mismatch in {path}")
    if summary.get("status") != "DOWNLOADED_AND_VALIDATED":
        raise RuntimeError(f"acquisition is not complete: {dataset_id}={summary.get('status')}")
    version = summary.get("source_revision") or summary.get("source_version")
    if not version:
        raise RuntimeError(f"source version is missing: {dataset_id}")
    return {
        "Dataset ID": dataset_id,
        "Filename": path.name,
        "Source URL": source_url,
        "Download date UTC": summary.get("acquired_at"),
        "Version": version,
        "Size bytes": path.stat().st_size,
        "SHA-256": sha256_file(path),
        "Local path": relative_to_repo(path),
        "Privacy status": "SCREENED_EXTERNAL_DATA_ASSET",
    }


def sync(manifest: Path) -> int:
    with manifest.open(encoding="utf-8", newline="") as source:
        existing = list(csv.DictReader(source))
    r3_ids = set(SOURCES)
    rows = [row for row in existing if row.get("Dataset ID") not in r3_ids]
    rows.extend(
        _summary_row(dataset_id, path, source_url)
        for dataset_id, (path, source_url) in sorted(SOURCES.items())
    )
    write_csv(manifest, FIELDS, rows)
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPO_ROOT / "data/manifests/downloaded-artifacts.csv",
    )
    args = parser.parse_args()
    count = sync(args.manifest.resolve())
    print(f"Synced {len(SOURCES)} R3 summaries; canonical manifest now has {count} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
