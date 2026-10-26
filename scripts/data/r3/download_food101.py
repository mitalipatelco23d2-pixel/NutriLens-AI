"""Download, safely extract, and validate the complete official ETH Food-101 dataset."""

from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.data.r3 import DATA_RELEASE
from scripts.data.r3.common import (
    REPO_ROOT,
    download_file_parallel_ranges,
    relative_to_repo,
    safe_extract_tar,
    sha256_file,
    tree_digest,
    utc_now,
    write_json,
    write_jsonl,
)
from scripts.data_engineering.images import ImageInspection, inspect_image
from scripts.data_engineering.schemas import ImageManifestRecord

SOURCE_URL = "https://data.vision.ee.ethz.ch/cvl/food-101.tar.gz"
SOURCE_VERSION = "official archive; Last-Modified 2014-07-09"
EXPECTED_BYTES = 4_996_278_331
EXPECTED_SHA256 = "d97d15e438b7f4498f96086a4f7e2fa42a32f2712e87d3295441b2b6314053a4"
DATASET_ID = "FOOD-101-R3"
ImageTask = tuple[str, str, int, str]


def _ensure_extracted(archive: Path, payload: Path) -> Path:
    marker = payload / ".nutrilens-extracted.json"
    root = payload / "food-101"
    if marker.exists():
        if not (root / "images").is_dir() or not (root / "meta").is_dir():
            raise RuntimeError("Food-101 extraction marker exists but payload is incomplete")
        return root
    if payload.exists() and any(payload.iterdir()):
        raise RuntimeError(f"refusing to overwrite unmarked extraction directory: {payload}")
    safe_extract_tar(archive, payload)
    write_json(
        marker,
        {"archive_sha256": sha256_file(archive), "extracted_at": utc_now()},
    )
    return root


def _inspect_food_item(root: Path, item: ImageTask) -> tuple[ImageTask, ImageInspection]:
    _, _, _, entry = item
    return item, inspect_image(root / "images" / f"{entry}.jpg")


def acquire(destination: Path, *, workers: int) -> dict[str, Any]:
    archive = destination / "archive" / "food-101.tar.gz"
    download_file_parallel_ranges(
        SOURCE_URL,
        archive,
        expected_size=EXPECTED_BYTES,
        expected_sha256=EXPECTED_SHA256,
        workers=32,
        timeout_seconds=120,
        force_ipv4=True,
    )
    payload = destination / "payload"
    extraction_marker = payload / ".nutrilens-extracted.json"
    if extraction_marker.is_file():
        archive_checksum = str(
            json.loads(extraction_marker.read_text(encoding="utf-8"))["archive_sha256"]
        )
    else:
        archive_checksum = sha256_file(archive)
    root = _ensure_extracted(archive, payload)
    image_rows: list[dict[str, Any]] = []
    r2_rows: list[dict[str, Any]] = []
    split_counts: dict[str, int] = {}
    tasks: list[ImageTask] = []
    for source_split, r2_split in (("train", "TRAIN"), ("test", "TEST")):
        entries = (root / "meta" / f"{source_split}.txt").read_text(encoding="utf-8").splitlines()
        for line_number, entry in enumerate(entries, start=1):
            if not entry.strip():
                continue
            tasks.append((source_split, r2_split, line_number, entry))
    inspect_one = partial(_inspect_food_item, root)
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        inspected = executor.map(inspect_one, tasks)
        for index, (item, inspection) in enumerate(inspected, start=1):
            source_split, r2_split, line_number, entry = item
            image_path = root / "images" / f"{entry}.jpg"
            if not inspection.valid:
                raise RuntimeError(f"invalid Food-101 image {entry}: {inspection.failure_reason}")
            class_name = entry.split("/", maxsplit=1)[0]
            image_id = f"food101-{source_split}-{line_number:06d}"
            row = {
                "annotation_kind": "OFFICIAL_DISH_CLASS",
                "bytes": image_path.stat().st_size,
                "class_name": class_name,
                "format": inspection.format,
                "height": inspection.height,
                "image_id": image_id,
                "license": "OFFICIAL_RESEARCH_DATASET; NO EXPLICIT LICENCE ON SOURCE PAGE",
                "local_path": relative_to_repo(image_path),
                "sha256": inspection.checksum,
                "source_dataset": SOURCE_URL,
                "source_record_id": entry,
                "source_split": source_split,
                "source_version": SOURCE_VERSION,
                "width": inspection.width,
            }
            image_rows.append(row)
            record = ImageManifestRecord(
                image_id=image_id,
                source_dataset=DATASET_ID,
                source_record_id=entry,
                local_path=str(row["local_path"]),
                image_type="PREPARED_MEAL",
                width=int(inspection.width or 0),
                height=int(inspection.height or 0),
                format=str(inspection.format),
                rights_status="ACADEMIC_EVALUATION_ONLY; LICENCE_REVIEW_REQUIRED",
                capture_source="OFFICIAL_ETH_FOOD_101_ARCHIVE",
                checksum=str(inspection.checksum),
                annotation_status="OFFICIAL_DISH_CLASS",
                split=r2_split,  # type: ignore[arg-type]
                notes=f"Food-101 class={class_name}",
            )
            r2_rows.append(record.model_dump(mode="json"))
            split_counts[source_split] = split_counts.get(source_split, 0) + 1
            if index == 1 or index % 10_000 == 0 or index == len(tasks):
                print(f"Validated {index}/{len(tasks)} Food-101 images", flush=True)
    manifest_dir = destination / "manifests"
    write_jsonl(manifest_dir / "source-images.jsonl", image_rows)
    processed = REPO_ROOT / "data" / "processed" / DATA_RELEASE / DATASET_ID.lower()
    write_jsonl(processed / "image-manifest.jsonl", r2_rows)
    summary = {
        "acquired_at": utc_now(),
        "annotation_count": len(image_rows),
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": archive_checksum,
        "dataset_id": DATASET_ID,
        "image_count": len(image_rows),
        "license": "No explicit licence on official page; academic evaluation and citation only",
        "payload_manifest": relative_to_repo(manifest_dir / "source-images.jsonl"),
        "payload_tree_sha256": tree_digest(
            [{"path": row["local_path"], "sha256": row["sha256"]} for row in image_rows]
        ),
        "source_url": SOURCE_URL,
        "source_version": SOURCE_VERSION,
        "split_counts": split_counts,
        "status": "DOWNLOADED_AND_VALIDATED",
    }
    write_json(destination / "acquisition-summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination",
        type=Path,
        default=REPO_ROOT / "data/external/r3/food-101",
    )
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    print(json.dumps(acquire(args.destination, workers=args.workers), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
