"""Clone and validate the complete official GroceryStoreDataset repository."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.data.r3 import DATA_RELEASE
from scripts.data.r3.common import (
    REPO_ROOT,
    relative_to_repo,
    tree_digest,
    utc_now,
    write_json,
    write_jsonl,
)
from scripts.data_engineering.images import inspect_image
from scripts.data_engineering.schemas import ImageManifestRecord

REPOSITORY = "https://github.com/marcusklasson/GroceryStoreDataset.git"
REVISION = "fc80ba90f803d79d0383df52c5a4ac5de99ff6fc"
DATASET_ID = "GROCERY-STORE-R3"


def _run_git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def ensure_repository(destination: Path) -> Path:
    repository = destination / "repository"
    if repository.exists():
        if not (repository / ".git").is_dir():
            raise RuntimeError(f"existing path is not a Git checkout: {repository}")
        current = _run_git("rev-parse", "HEAD", cwd=repository)
        if current != REVISION:
            raise RuntimeError(f"refusing to replace GroceryStoreDataset revision {current}")
        return repository
    destination.mkdir(parents=True, exist_ok=True)
    _run_git("clone", "--depth", "1", REPOSITORY, str(repository))
    current = _run_git("rev-parse", "HEAD", cwd=repository)
    if current != REVISION:
        raise RuntimeError(f"official repository moved: expected {REVISION}, received {current}")
    return repository


def _split_row(line: str) -> tuple[str, int, int]:
    parts = [part for part in re.split(r"[\s,]+", line.strip()) if part]
    if len(parts) != 3:
        raise ValueError(f"unexpected GroceryStore split row: {line!r}")
    return parts[0], int(parts[1]), int(parts[2])


def acquire(destination: Path) -> dict[str, Any]:
    repository = ensure_repository(destination)
    dataset_root = repository / "dataset"
    image_rows: list[dict[str, Any]] = []
    r2_rows: list[dict[str, Any]] = []
    split_counts: dict[str, int] = {}
    split_map = {"train": "TRAIN", "val": "VALIDATION", "test": "TEST"}
    for source_split, r2_split in split_map.items():
        split_file = dataset_root / f"{source_split}.txt"
        for line_number, line in enumerate(
            split_file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            relative, fine_label, coarse_label = _split_row(line)
            image_path = dataset_root / relative
            inspection = inspect_image(image_path)
            if not inspection.valid:
                raise RuntimeError(
                    f"invalid GroceryStore image {relative}: {inspection.failure_reason}"
                )
            image_id = f"grocery-{source_split}-{line_number:06d}"
            fine_name = image_path.parent.name
            row = {
                "annotation_kind": "OFFICIAL_CLASS_LABEL",
                "bytes": image_path.stat().st_size,
                "coarse_label": coarse_label,
                "fine_label": fine_label,
                "fine_name_from_path": fine_name,
                "format": inspection.format,
                "height": inspection.height,
                "image_id": image_id,
                "license": "MIT repository; depicted-image rights require review",
                "local_path": relative_to_repo(image_path),
                "sha256": inspection.checksum,
                "source_dataset": REPOSITORY,
                "source_record_id": f"{source_split}:{line_number}",
                "source_revision": REVISION,
                "source_split": source_split,
                "width": inspection.width,
            }
            image_rows.append(row)
            manifest = ImageManifestRecord(
                image_id=image_id,
                source_dataset=DATASET_ID,
                source_record_id=str(row["source_record_id"]),
                local_path=str(row["local_path"]),
                image_type="GROCERY_ITEM",
                width=int(inspection.width or 0),
                height=int(inspection.height or 0),
                format=str(inspection.format),
                rights_status="ACADEMIC_EVALUATION; IMAGE_RIGHTS_REVIEW_REQUIRED",
                capture_source="OFFICIAL_GROCERY_STORE_DATASET",
                checksum=str(inspection.checksum),
                annotation_status="OFFICIAL_CLASS_LABEL",
                split=r2_split,  # type: ignore[arg-type]
                notes=f"fine={fine_label}; coarse={coarse_label}; path_class={fine_name}",
            )
            r2_rows.append(manifest.model_dump(mode="json"))
            split_counts[source_split] = split_counts.get(source_split, 0) + 1
    manifest_dir = destination / "manifests"
    write_jsonl(manifest_dir / "source-images.jsonl", image_rows)
    processed = REPO_ROOT / "data" / "processed" / DATA_RELEASE / DATASET_ID.lower()
    write_jsonl(processed / "image-manifest.jsonl", r2_rows)
    summary = {
        "acquired_at": utc_now(),
        "annotation_count": len(image_rows),
        "dataset_id": DATASET_ID,
        "image_count": len(image_rows),
        "license": "MIT repository; third-party/depicted image rights require review",
        "payload_manifest": relative_to_repo(manifest_dir / "source-images.jsonl"),
        "payload_tree_sha256": tree_digest(
            [{"path": row["local_path"], "sha256": row["sha256"]} for row in image_rows]
        ),
        "repository": REPOSITORY,
        "source_revision": REVISION,
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
        default=REPO_ROOT / "data/external/r3/grocery-store-dataset",
    )
    args = parser.parse_args()
    print(json.dumps(acquire(args.destination), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
