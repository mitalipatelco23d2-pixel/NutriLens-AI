"""Verify R3 supplemental image payloads, checksums, counts, and tracked summaries."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.data.r3 import DATA_RELEASE
from scripts.data.r3.common import (
    REPO_ROOT,
    read_jsonl,
    relative_to_repo,
    sha256_file,
    utc_now,
    write_csv,
    write_json,
)
from scripts.data_engineering.images import inspect_image

DATASETS = {
    "OFF-R3-NUTRITION-TABLE-DETECTION": REPO_ROOT
    / "data/external/r3/openfoodfacts/nutrition-table-detection",
    "OFF-R3-FRONT-IMAGE-CLASSIFICATION": REPO_ROOT
    / "data/external/r3/openfoodfacts/front-image-classification",
    "OFF-R3-PRODUCT-IMAGE-CORPUS": REPO_ROOT / "data/external/r3/openfoodfacts/product-images",
    "GROCERY-STORE-R3": REPO_ROOT / "data/external/r3/grocery-store-dataset",
    "FOOD-101-R3": REPO_ROOT / "data/external/r3/food-101",
}


def _verify_nutrition_exports(expected_annotations: int) -> list[str]:
    processed = REPO_ROOT / "data/processed" / DATA_RELEASE / "off-r3-nutrition-table-detection"
    detection_path = processed / "detection-annotations.jsonl"
    coco_path = processed / "coco-annotations.json"
    yolo_root = processed / "yolo/labels"
    summary_path = processed / "annotation-export-summary.json"
    required = (detection_path, coco_path, yolo_root, summary_path)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return [f"missing R2 annotation export: {path}" for path in missing]

    detection_count = sum(1 for _ in read_jsonl(detection_path))
    coco = json.loads(coco_path.read_text(encoding="utf-8"))
    yolo_line_count = 0
    for label_path in yolo_root.glob("*.txt"):
        yolo_line_count += sum(
            1 for line in label_path.read_text(encoding="utf-8").splitlines() if line.strip()
        )
    export_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for label, value in (
        ("canonical detection", detection_count),
        ("COCO", len(coco.get("annotations", []))),
        ("YOLO", yolo_line_count),
    ):
        if value != expected_annotations:
            errors.append(
                f"{label} annotation count {value} != source count {expected_annotations}"
            )
    if export_summary.get("ocr_annotation_count") != 0:
        errors.append("OCR annotation count must remain zero without source transcriptions")
    return errors


def _verify_manifest(root: Path, *, full: bool) -> tuple[int, int, Counter[str], list[str]]:
    manifest = root / "manifests/source-images.jsonl"
    if not manifest.is_file():
        return 0, 0, Counter(), [f"missing manifest: {manifest}"]
    count = 0
    total_bytes = 0
    roles: Counter[str] = Counter()
    errors: list[str] = []
    seen_ids: set[str] = set()
    for row in read_jsonl(manifest):
        count += 1
        image_id = str(row["image_id"])
        if image_id in seen_ids:
            errors.append(f"duplicate image_id {image_id}")
        seen_ids.add(image_id)
        local_path = (REPO_ROOT / str(row["local_path"])).resolve()
        if REPO_ROOT.resolve() not in local_path.parents:
            errors.append(f"path escapes repository: {row['local_path']}")
            continue
        if not local_path.is_file():
            errors.append(f"missing image: {row['local_path']}")
            continue
        total_bytes += local_path.stat().st_size
        role = str(row.get("image_role") or row.get("class_name") or "unclassified")
        roles[role] += 1
        if full:
            inspection = inspect_image(local_path)
            if not inspection.valid:
                errors.append(f"invalid image {row['local_path']}: {inspection.failure_reason}")
            elif inspection.checksum != row.get("sha256"):
                errors.append(f"checksum mismatch: {row['local_path']}")
            elif inspection.width != row.get("width") or inspection.height != row.get("height"):
                errors.append(f"dimension mismatch: {row['local_path']}")
    return count, total_bytes, roles, errors


def verify(*, full: bool) -> dict[str, Any]:
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    artifact_rows: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}
    for expected_id, root in DATASETS.items():
        summary_path = root / "acquisition-summary.json"
        if not summary_path.is_file():
            errors.append(f"missing acquisition summary for {expected_id}")
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summaries[expected_id] = summary
        if summary.get("dataset_id") != expected_id:
            errors.append(f"dataset ID mismatch in {summary_path}")
        count, total_bytes, roles, manifest_errors = _verify_manifest(root, full=full)
        errors.extend(f"{expected_id}: {error}" for error in manifest_errors)
        if count != int(summary.get("image_count", -1)):
            errors.append(
                f"{expected_id}: manifest count {count} != summary {summary.get('image_count')}"
            )
        if expected_id == "OFF-R3-NUTRITION-TABLE-DETECTION":
            errors.extend(
                f"{expected_id}: {error}"
                for error in _verify_nutrition_exports(int(summary.get("annotation_count", -1)))
            )
        rows.append(
            {
                "Dataset ID": expected_id,
                "Status": summary.get("status"),
                "Source version": summary.get("source_revision") or summary.get("source_version"),
                "License": summary.get("license"),
                "Image count": count,
                "Annotation count": summary.get("annotation_count", ""),
                "Product count": summary.get("product_count", ""),
                "Local bytes": total_bytes,
                "Payload tree SHA-256": summary.get("payload_tree_sha256"),
                "Local path": relative_to_repo(root),
                "Verified at": utc_now(),
                "Role counts": json.dumps(dict(sorted(roles.items())), sort_keys=True),
            }
        )
        for artifact in summary.get("artifacts", []):
            artifact_path = root / "source" / str(artifact["path"])
            if (
                full
                and artifact_path.is_file()
                and sha256_file(artifact_path) != artifact["sha256"]
            ):
                errors.append(
                    f"{expected_id}: source artifact checksum mismatch {artifact['path']}"
                )
            artifact_rows.append(
                {
                    "Dataset ID": expected_id,
                    "Artifact path": artifact["path"],
                    "Bytes": artifact["bytes"],
                    "SHA-256": artifact["sha256"],
                    "Source version": summary.get("source_revision")
                    or summary.get("source_version"),
                }
            )
        if summary.get("archive_sha256"):
            artifact_rows.append(
                {
                    "Dataset ID": expected_id,
                    "Artifact path": "archive/food-101.tar.gz",
                    "Bytes": summary.get("archive_bytes"),
                    "SHA-256": summary.get("archive_sha256"),
                    "Source version": summary.get("source_version"),
                }
            )

    myfood = REPO_ROOT / "data/external/r3/myfoodrepo/access-status.json"
    if not myfood.is_file():
        errors.append("missing MyFoodRepo access-status.json")
    else:
        status = json.loads(myfood.read_text(encoding="utf-8"))
        if status.get("status") != "MANUAL_ACCESS_REQUIRED":
            errors.append("MyFoodRepo access status was not recorded as MANUAL_ACCESS_REQUIRED")

    manifests = REPO_ROOT / "data/manifests"
    fields = [
        "Dataset ID",
        "Status",
        "Source version",
        "License",
        "Image count",
        "Annotation count",
        "Product count",
        "Local bytes",
        "Payload tree SHA-256",
        "Local path",
        "Verified at",
        "Role counts",
    ]
    write_csv(manifests / "r3-acquisitions.csv", fields, rows)
    artifact_fields = ["Dataset ID", "Artifact path", "Bytes", "SHA-256", "Source version"]
    write_csv(manifests / "r3-source-artifacts.csv", artifact_fields, artifact_rows)
    source_image_count = sum(int(row["Image count"]) for row in rows)
    annotation_status = {
        "classification_annotations": sum(
            int(summaries[dataset_id].get("annotation_count", 0))
            for dataset_id in (
                "OFF-R3-FRONT-IMAGE-CLASSIFICATION",
                "GROCERY-STORE-R3",
                "FOOD-101-R3",
            )
            if dataset_id in summaries
        ),
        "detection_annotations": int(
            summaries.get("OFF-R3-NUTRITION-TABLE-DETECTION", {}).get("annotation_count", 0)
        ),
        "multi_food_annotations": 0,
        "notes": (
            "R3 supplemental acquisitions processed through R2 image contracts; "
            "MyFoodRepo multi-food annotations remain MANUAL_ACCESS_REQUIRED."
        ),
        "ocr_annotations": 0,
        "release": "r3-real-v1.0.0",
        "source_images": source_image_count,
        "source_role_annotations": int(
            summaries.get("OFF-R3-PRODUCT-IMAGE-CORPUS", {}).get("image_count", 0)
        ),
        "status": "R3_SUPPLEMENTAL_REAL_IMAGES_AVAILABLE_WITH_LIMITATIONS",
        "updated_at": utc_now(),
    }
    write_json(
        REPO_ROOT / "data/annotations/r3-supplemental-annotation-status.json",
        annotation_status,
    )
    report = {
        "dataset_count": len(rows),
        "errors": errors,
        "full_checksum_verification": full,
        "image_count": source_image_count,
        "status": "PASS" if not errors else "FAIL",
        "verified_at": utc_now(),
    }
    write_json(manifests / "r3-verification-summary.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quick", action="store_true", help="Check paths/counts but skip rehashing every image."
    )
    args = parser.parse_args()
    report = verify(full=not args.quick)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
