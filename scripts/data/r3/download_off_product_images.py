"""Build a traceable multi-view OFF product-image corpus from the official Parquet dump."""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pyarrow.parquet as pq
import requests

from scripts.data.r3 import DATA_RELEASE
from scripts.data.r3.common import (
    REPO_ROOT,
    artifact_rows,
    download_file,
    download_huggingface_snapshot,
    read_jsonl,
    relative_to_repo,
    tree_digest,
    utc_now,
    write_json,
    write_jsonl,
)
from scripts.data_engineering.images import inspect_image
from scripts.data_engineering.schemas import ImageManifestRecord

REPO_ID = "openfoodfacts/product-database"
REVISION = "cb1ae34c41cd2c4cc44eaf7007494d28ec4d9acb"
DATASET_ID = "OFF-R3-PRODUCT-IMAGE-CORPUS"
AWS_IMAGE_ROOT = "https://openfoodfacts-images.s3.eu-west-3.amazonaws.com/data"
OFF_IMAGE_ROOT = "https://images.openfoodfacts.org/images/products"
SELECTED_ROLES = ("front", "nutrition", "ingredients", "packaging")
SELECTION_POOL_MULTIPLIER = 4


@dataclass(frozen=True)
class ImageCandidate:
    barcode: str
    image_key: str
    image_role: str
    image_id: str
    revision: int | None
    product_name: str | None
    brand: str | None
    source_kind: str


def off_product_folder(barcode: str) -> str:
    """Implement the official Product Opener image-directory algorithm."""

    normalized = re.sub(r"[^0-9]", "", barcode)
    if not normalized:
        raise ValueError("barcode contains no digits")
    if len(normalized) <= 8:
        return normalized
    return "/".join((normalized[:3], normalized[3:6], normalized[6:9], normalized[9:]))


def selected_role(image_key: str) -> str | None:
    for role in SELECTED_ROLES:
        if image_key == role or image_key.startswith(f"{role}_"):
            return role
    return None


def _localized_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, list):
        return None
    entries = [entry for entry in value if isinstance(entry, dict) and entry.get("text")]
    for preferred in ("main", "en"):
        for entry in entries:
            if str(entry.get("lang")) == preferred:
                return str(entry["text"]).strip() or None
    return str(entries[0]["text"]).strip() if entries else None


def image_candidates(row: dict[str, Any]) -> list[ImageCandidate]:
    barcode = str(row.get("code") or "").strip()
    if not barcode:
        return []
    images = [entry for entry in (row.get("images") or []) if isinstance(entry, dict)]
    selected_by_role: dict[str, ImageCandidate] = {}
    referenced: set[str] = set()
    product_name = _localized_text(row.get("product_name"))
    brand = str(row.get("brands") or "").strip() or None
    for entry in images:
        key = str(entry.get("key") or "")
        role = selected_role(key)
        image_id = str(entry.get("imgid") or "")
        revision = entry.get("rev")
        if role is None or not image_id or revision is None:
            continue
        referenced.add(image_id)
        candidate = ImageCandidate(
            barcode=barcode,
            image_key=key,
            image_role=role,
            image_id=image_id,
            revision=int(revision),
            product_name=product_name,
            brand=brand,
            source_kind="SELECTED_ROLE",
        )
        existing = selected_by_role.get(role)
        ranking = (0 if key == role else 1 if key.endswith("_en") else 2, key)
        existing_ranking = (
            (
                0
                if existing is not None and existing.image_key == role
                else 1
                if existing is not None and existing.image_key.endswith("_en")
                else 2
            ),
            existing.image_key if existing is not None else "",
        )
        if existing is None or ranking < existing_ranking:
            selected_by_role[role] = candidate
    raw_keys = sorted(
        str(entry.get("key"))
        for entry in images
        if str(entry.get("key") or "").isdigit() and str(entry.get("key")) not in referenced
    )
    selected = [
        selected_by_role[role]
        for role in ("front", "nutrition", "ingredients")
        if role in selected_by_role
    ]
    if raw_keys:
        key = raw_keys[0]
        selected.append(
            ImageCandidate(
                barcode=barcode,
                image_key=key,
                image_role="other",
                image_id=key,
                revision=None,
                product_name=product_name,
                brand=brand,
                source_kind="RAW_UNSELECTED",
            )
        )
    elif "packaging" in selected_by_role:
        selected.append(selected_by_role["packaging"])
    return selected


def candidate_url(candidate: ImageCandidate, *, root: str) -> str:
    folder = off_product_folder(candidate.barcode)
    if candidate.source_kind == "SELECTED_ROLE":
        filename = f"{candidate.image_key}.{candidate.revision}.full.jpg"
    else:
        filename = f"{candidate.image_key}.jpg"
    return f"{root}/{folder}/{filename}"


def _score(barcode: str) -> int:
    return int.from_bytes(hashlib.sha256(barcode.encode()).digest()[:8], "big")


def _product_reference(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "barcode": str(row.get("code") or ""),
        "brand": str(row.get("brands") or "").strip() or None,
        "categories": str(row.get("categories") or "").strip() or None,
        "ingredients_reference": _localized_text(row.get("ingredients_text")),
        "ingredients_reference_type": "PRODUCT_DATABASE_REFERENCE",
        "nutrition_data_per": row.get("nutrition_data_per"),
        "nutriments_reference": row.get("nutriments"),
        "product_name": _localized_text(row.get("product_name")),
    }


def select_products(parquet_path: Path, *, product_count: int) -> list[dict[str, Any]]:
    columns = [
        "code",
        "images",
        "product_name",
        "brands",
        "ingredients_text",
        "categories",
        "nutrition_data_per",
        "nutriments",
    ]
    selected: list[tuple[int, str, dict[str, Any]]] = []
    eligible_seen = 0
    selection_pool_size = product_count * SELECTION_POOL_MULTIPLIER
    parquet = pq.ParquetFile(parquet_path)
    for batch in parquet.iter_batches(batch_size=1024, columns=columns):
        for row in batch.to_pylist():
            candidates = image_candidates(row)
            roles = {candidate.image_role for candidate in candidates}
            if "front" not in roles or not roles.intersection({"nutrition", "ingredients"}):
                continue
            eligible_seen += 1
            barcode = str(row.get("code") or "")
            score = _score(barcode)
            item = (-score, barcode, _product_reference(row))
            if len(selected) < product_count:
                heapq.heappush(selected, item)
            elif score < -selected[0][0]:
                heapq.heapreplace(selected, item)
            if eligible_seen >= selection_pool_size:
                return [item[2] for item in sorted(selected, key=lambda item: (-item[0], item[1]))]
    return [item[2] for item in sorted(selected, key=lambda item: (-item[0], item[1]))]


def _rows_for_selected_products(
    parquet_path: Path, references: list[dict[str, Any]]
) -> dict[str, list[ImageCandidate]]:
    wanted = {str(row["barcode"]) for row in references}
    found: dict[str, list[ImageCandidate]] = {}
    columns = ["code", "images", "product_name", "brands"]
    parquet = pq.ParquetFile(parquet_path)
    for batch in parquet.iter_batches(batch_size=2048, columns=columns):
        for row in batch.to_pylist():
            barcode = str(row.get("code") or "")
            if barcode in wanted:
                found[barcode] = image_candidates(row)
        if len(found) == len(wanted):
            break
    return found


def _safe_key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


def _download_one(candidate: ImageCandidate, destination: Path) -> dict[str, Any]:
    local_path = (
        destination
        / "images"
        / candidate.image_role
        / f"{candidate.barcode}__{_safe_key(candidate.image_key)}.jpg"
    )
    urls = [
        candidate_url(candidate, root=AWS_IMAGE_ROOT),
        candidate_url(candidate, root=OFF_IMAGE_ROOT),
    ]
    errors: list[str] = []
    for url in urls:
        try:
            download_file(url, local_path, max_bytes=15 * 1024 * 1024, timeout_seconds=90)
            inspection = inspect_image(local_path)
            if not inspection.valid:
                raise RuntimeError(inspection.failure_reason or "invalid image")
            return {
                "barcode": candidate.barcode,
                "brand": candidate.brand,
                "bytes": local_path.stat().st_size,
                "download_url": url,
                "format": inspection.format,
                "height": inspection.height,
                "image_id": f"{candidate.barcode}_{candidate.image_key}",
                "image_role": candidate.image_role,
                "license": "CC-BY-SA-3.0",
                "local_path": relative_to_repo(local_path),
                "off_image_id": candidate.image_id,
                "off_image_key": candidate.image_key,
                "original_url": candidate_url(candidate, root=OFF_IMAGE_ROOT),
                "product_name": candidate.product_name,
                "sha256": inspection.checksum,
                "source_dataset": REPO_ID,
                "source_kind": candidate.source_kind,
                "source_revision": REVISION,
                "width": inspection.width,
            }
        except (requests.RequestException, RuntimeError, ValueError) as exc:
            errors.append(f"{url}: {type(exc).__name__}")
            local_path.unlink(missing_ok=True)
    return {
        "barcode": candidate.barcode,
        "image_key": candidate.image_key,
        "image_role": candidate.image_role,
        "status": "DOWNLOAD_FAILED",
        "errors": errors,
    }


def acquire_product_corpus(
    destination: Path, *, product_count: int, max_images: int, workers: int
) -> dict[str, Any]:
    source_root = destination / "source"
    download_huggingface_snapshot(
        repo_id=REPO_ID,
        revision=REVISION,
        destination=source_root,
        allow_patterns=["README.md", ".gitattributes", "food.parquet"],
    )
    parquet_path = source_root / "food.parquet"
    references = select_products(parquet_path, product_count=product_count)
    if len(references) < product_count:
        raise RuntimeError(f"only {len(references)} eligible multi-view products were found")
    candidate_groups = _rows_for_selected_products(parquet_path, references)
    candidates = [
        candidate
        for reference in references
        for candidate in candidate_groups.get(str(reference["barcode"]), [])
    ][:max_images]
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(_download_one, candidate, destination): candidate
            for candidate in candidates
        }
        for index, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if index == 1 or index % 250 == 0 or index == len(futures):
                successful = sum(row.get("sha256") is not None for row in results)
                print(
                    f"Processed {index}/{len(futures)} OFF image candidates ({successful} valid)",
                    flush=True,
                )
    images = sorted(
        (row for row in results if row.get("sha256")),
        key=lambda row: (str(row["barcode"]), str(row["image_role"]), str(row["image_id"])),
    )
    failures = sorted(
        (row for row in results if row.get("status") == "DOWNLOAD_FAILED"),
        key=lambda row: (str(row["barcode"]), str(row["image_key"])),
    )
    manifest_dir = destination / "manifests"
    write_jsonl(manifest_dir / "product-references.jsonl", references)
    write_jsonl(manifest_dir / "source-images.jsonl", images)
    write_jsonl(manifest_dir / "download-failures.jsonl", failures)

    r2_rows: list[dict[str, Any]] = []
    for row in images:
        record = ImageManifestRecord(
            image_id=str(row["image_id"]),
            source_dataset=DATASET_ID,
            source_record_id=str(row["image_id"]),
            local_path=str(row["local_path"]),
            image_type=str(row["image_role"]).upper(),
            product_id=str(row["barcode"]),
            width=int(row["width"]),
            height=int(row["height"]),
            format=str(row["format"]),
            rights_status="CC-BY-SA-3.0",
            capture_source="OPEN_FOOD_FACTS_PRODUCT_DATABASE_IMAGE_METADATA",
            checksum=str(row["sha256"]),
            annotation_status="SOURCE_ROLE"
            if row["source_kind"] == "SELECTED_ROLE"
            else "UNLABELED",
            split="TEST",
            notes="R3 supplemental deterministic held-out product corpus",
        )
        r2_rows.append(record.model_dump(mode="json"))
    processed = REPO_ROOT / "data" / "processed" / DATA_RELEASE / DATASET_ID.lower()
    write_jsonl(processed / "image-manifest.jsonl", r2_rows)
    artifacts = artifact_rows(source_root)
    unique_products = len({str(row["barcode"]) for row in images})
    role_counts = Counter(str(row["image_role"]) for row in images)
    summary = {
        "acquired_at": utc_now(),
        "artifacts": artifacts,
        "candidate_count": len(candidates),
        "dataset_id": DATASET_ID,
        "download_failures": len(failures),
        "download_failures_manifest": relative_to_repo(manifest_dir / "download-failures.jsonl"),
        "image_count": len(images),
        "license": "ODbL database metadata; CC-BY-SA-3.0 product images",
        "payload_manifest": relative_to_repo(manifest_dir / "source-images.jsonl"),
        "payload_tree_sha256": tree_digest(
            [{"path": row["local_path"], "sha256": row["sha256"]} for row in images]
        ),
        "product_count": unique_products,
        "requested_product_count": product_count,
        "repo_id": REPO_ID,
        "role_counts": dict(sorted(role_counts.items())),
        "selection_method": (
            f"SHA256 rank within first {product_count * SELECTION_POOL_MULTIPLIER} "
            "eligible multi-view products in pinned Parquet order"
        ),
        "source_revision": REVISION,
        "status": (
            "DOWNLOADED_AND_VALIDATED" if unique_products >= 2000 else "INSUFFICIENT_PRODUCTS"
        ),
        "total_image_bytes": sum(int(row["bytes"]) for row in images),
    }
    write_json(destination / "acquisition-summary.json", summary)
    if unique_products < 2000:
        raise RuntimeError(f"only {unique_products} products downloaded; 2,000 are required")
    return summary


def summarize_existing_corpus(destination: Path) -> dict[str, Any]:
    """Regenerate the governed summary from an already validated local corpus.

    This is intentionally manifest-only: it never fetches, replaces, or rescans
    the pinned Parquet/image payload after a successful acquisition.
    """

    manifest_dir = destination / "manifests"
    image_path = manifest_dir / "source-images.jsonl"
    reference_path = manifest_dir / "product-references.jsonl"
    failures_path = manifest_dir / "download-failures.jsonl"
    required = (image_path, reference_path, failures_path)
    missing = [path for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"cannot finalize missing corpus manifests: {missing}")
    images = list(read_jsonl(image_path))
    references = list(read_jsonl(reference_path))
    failures = list(read_jsonl(failures_path))
    unique_products = len({str(row["barcode"]) for row in images})
    role_counts = Counter(str(row["image_role"]) for row in images)
    source_root = destination / "source"
    summary = {
        "acquired_at": utc_now(),
        "artifacts": artifact_rows(source_root),
        "candidate_count": len(images) + len(failures),
        "dataset_id": DATASET_ID,
        "download_failures": len(failures),
        "download_failures_manifest": relative_to_repo(failures_path),
        "image_count": len(images),
        "license": "ODbL database metadata; CC-BY-SA-3.0 product images",
        "payload_manifest": relative_to_repo(image_path),
        "payload_tree_sha256": tree_digest(
            [{"path": row["local_path"], "sha256": row["sha256"]} for row in images]
        ),
        "product_count": unique_products,
        "requested_product_count": len(references),
        "repo_id": REPO_ID,
        "role_counts": dict(sorted(role_counts.items())),
        "selection_method": (
            f"SHA256 rank within first {len(references) * SELECTION_POOL_MULTIPLIER} "
            "eligible multi-view products in pinned Parquet order"
        ),
        "source_revision": REVISION,
        "status": "DOWNLOADED_AND_VALIDATED"
        if unique_products >= 2000
        else "INSUFFICIENT_PRODUCTS",
        "total_image_bytes": sum(int(row["bytes"]) for row in images),
    }
    write_json(destination / "acquisition-summary.json", summary)
    if unique_products < 2000:
        raise RuntimeError(
            f"only {unique_products} products in completed corpus; 2,000 are required"
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination",
        type=Path,
        default=REPO_ROOT / "data/external/r3/openfoodfacts/product-images",
    )
    parser.add_argument("--product-count", type=int, default=2500)
    parser.add_argument("--max-images", type=int, default=10000)
    parser.add_argument("--workers", type=int, default=32)
    parser.add_argument(
        "--finalize-existing",
        action="store_true",
        help="Regenerate the governed summary from completed manifests without network access.",
    )
    args = parser.parse_args()
    summary = (
        summarize_existing_corpus(args.destination)
        if args.finalize_existing
        else acquire_product_corpus(
            args.destination,
            product_count=args.product_count,
            max_images=args.max_images,
            workers=args.workers,
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
