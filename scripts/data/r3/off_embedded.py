"""Pinned Open Food Facts Hugging Face datasets with Parquet-embedded images."""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path
from typing import Any, Literal

import pyarrow.parquet as pq
from PIL import Image

from scripts.data.r3 import DATA_RELEASE
from scripts.data.r3.common import (
    REPO_ROOT,
    artifact_rows,
    atomic_text,
    download_huggingface_snapshot,
    relative_to_repo,
    sha256_bytes,
    tree_digest,
    utc_now,
    write_json,
    write_jsonl,
)
from scripts.data_engineering.annotations import to_coco, to_yolo_line
from scripts.data_engineering.schemas import (
    BoundingBox,
    DetectionAnnotation,
    ImageManifestRecord,
)

DatasetKind = Literal["nutrition", "front"]


def _safe_image_id(value: object) -> str:
    raw = str(value)
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", raw).strip("._")[:100]
    if not cleaned or cleaned != raw:
        cleaned = f"{cleaned or 'image'}-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"
    return cleaned


def normalized_yxyx_to_pixels(values: list[float], *, width: int, height: int) -> BoundingBox:
    if len(values) != 4:
        raise ValueError("OFF bounding boxes must contain four values")
    raw = [float(value) for value in values]
    tolerance = 1e-6
    if any(value < -tolerance or value > 1 + tolerance for value in raw):
        raise ValueError(f"invalid normalized OFF bounding box: {values}")
    y_min, x_min, y_max, x_max = (min(1.0, max(0.0, value)) for value in raw)
    if not (0 <= x_min < x_max <= 1 and 0 <= y_min < y_max <= 1):
        raise ValueError(f"invalid normalized OFF bounding box: {values}")
    return BoundingBox(
        x=x_min * width,
        y=y_min * height,
        width=(x_max - x_min) * width,
        height=(y_max - y_min) * height,
    )


def _image_bytes(value: Any, parquet_path: Path) -> bytes:
    if not isinstance(value, dict):
        raise ValueError("Parquet image value is not a struct")
    content = value.get("bytes")
    if content is not None:
        return bytes(content)
    relative = value.get("path")
    if not relative:
        raise ValueError("Parquet image contains neither bytes nor path")
    candidate = (parquet_path.parent / str(relative)).resolve()
    if parquet_path.parent.resolve() not in candidate.parents:
        raise ValueError("Parquet image path escapes its shard directory")
    return candidate.read_bytes()


def _extension_and_dimensions(content: bytes) -> tuple[str, str, int, int]:
    with Image.open(io.BytesIO(content)) as image:
        image.verify()
        image_format = str(image.format or "").upper()
        width, height = image.size
    extensions = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}
    if image_format not in extensions:
        raise ValueError(f"unsupported embedded image format: {image_format}")
    return extensions[image_format], image_format, width, height


def _write_content_without_overwrite(destination: Path, content: bytes) -> str:
    checksum = sha256_bytes(content)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha256_bytes(destination.read_bytes()) != checksum:
            raise RuntimeError(f"refusing to overwrite differing image: {destination}")
        return checksum
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(content)
    temporary.replace(destination)
    return checksum


def acquire_off_embedded_dataset(
    *,
    dataset_id: str,
    repo_id: str,
    revision: str,
    destination: Path,
    kind: DatasetKind,
    license_name: str,
    dataset_version: str,
) -> dict[str, Any]:
    source_root = destination / "source"
    download_huggingface_snapshot(
        repo_id=repo_id,
        revision=revision,
        destination=source_root,
        allow_patterns=["README.md", ".gitattributes", "data/*.parquet"],
    )
    image_rows: list[dict[str, Any]] = []
    r2_images: list[dict[str, Any]] = []
    r2_detections: list[dict[str, Any]] = []
    r2_detection_models: list[DetectionAnnotation] = []
    coco_images: list[dict[str, Any]] = []
    split_counts: dict[str, int] = {}
    total_bytes = 0

    for parquet_path in sorted((source_root / "data").glob("*.parquet")):
        split = parquet_path.name.split("-", maxsplit=1)[0]
        r2_split: Literal["TRAIN", "TEST"] = "TEST" if split in {"val", "test"} else "TRAIN"
        parquet = pq.ParquetFile(parquet_path)
        for batch in parquet.iter_batches(batch_size=32):
            for row in batch.to_pylist():
                image_id = _safe_image_id(row["image_id"])
                content = _image_bytes(row["image"], parquet_path)
                extension, image_format, width, height = _extension_and_dimensions(content)
                if width != int(row["width"]) or height != int(row["height"]):
                    raise ValueError(f"dimension mismatch for {image_id}")
                local_path = destination / "images" / split / f"{image_id}.{extension}"
                checksum = _write_content_without_overwrite(local_path, content)
                total_bytes += len(content)
                meta = dict(row.get("meta") or {})
                source_boxes: list[dict[str, Any]] = []
                if kind == "nutrition":
                    objects = dict(row.get("objects") or {})
                    boxes = list(objects.get("bbox") or [])
                    categories = list(objects.get("category_name") or [])
                    if len(boxes) != len(categories):
                        raise ValueError(f"box/category mismatch for {image_id}")
                    for index, (raw_box, category) in enumerate(
                        zip(boxes, categories, strict=True)
                    ):
                        pixel_box = normalized_yxyx_to_pixels(
                            list(raw_box), width=width, height=height
                        )
                        annotation = DetectionAnnotation(
                            annotation_id=f"{dataset_id}:{image_id}:{index}",
                            image_id=image_id,
                            label="nutrition_table",
                            bounding_box=pixel_box,
                            annotation_source="OFF_MANUALLY_REVIEWED_BOUNDING_BOX",
                            review_status="SOURCE_MANUALLY_REVIEWED",
                        )
                        r2_detection_models.append(annotation)
                        r2_detections.append(annotation.model_dump(mode="json"))
                        source_boxes.append(
                            {
                                "category_name": str(category),
                                "normalized_order": "y_min,x_min,y_max,x_max",
                                "normalized": [float(value) for value in raw_box],
                                "pixels_xywh": pixel_box.model_dump(mode="json"),
                            }
                        )
                category_name = str(row.get("category_name") or "nutrition-table")
                manifest = ImageManifestRecord(
                    image_id=image_id,
                    source_dataset=dataset_id,
                    source_record_id=image_id,
                    local_path=relative_to_repo(local_path),
                    image_type="NUTRITION_PANEL" if kind == "nutrition" else category_name.upper(),
                    product_id=str(meta.get("barcode") or "") or None,
                    width=width,
                    height=height,
                    format=image_format,
                    rights_status=license_name,
                    capture_source="OPEN_FOOD_FACTS_PUBLIC_DATASET",
                    checksum=checksum,
                    annotation_status="MANUALLY_REVIEWED"
                    if kind == "nutrition"
                    else "SOURCE_LABEL",
                    split=r2_split,
                    notes=f"R3 supplemental acquisition; official source split={split}",
                )
                r2_images.append(manifest.model_dump(mode="json"))
                coco_images.append(
                    {
                        "file_name": relative_to_repo(local_path),
                        "height": height,
                        "id": image_id,
                        "source_split": split,
                        "width": width,
                    }
                )
                image_rows.append(
                    {
                        "annotation_kind": (
                            "OFF_MANUALLY_REVIEWED_BOUNDING_BOX"
                            if kind == "nutrition"
                            else "OFF_MANUALLY_REVIEWED_CLASS"
                        ),
                        "barcode": str(meta.get("barcode") or ""),
                        "bytes": len(content),
                        "category_id": row.get("category_id"),
                        "category_name": category_name,
                        "height": height,
                        "image_id": image_id,
                        "image_role": "nutrition" if kind == "nutrition" else category_name,
                        "license": license_name,
                        "local_path": relative_to_repo(local_path),
                        "off_image_id": str(meta.get("off_image_id") or ""),
                        "original_url": str(meta.get("image_url") or ""),
                        "sha256": checksum,
                        "source_boxes": source_boxes,
                        "source_dataset": repo_id,
                        "source_revision": revision,
                        "source_split": split,
                        "width": width,
                    }
                )
                split_counts[split] = split_counts.get(split, 0) + 1

    if not image_rows:
        raise RuntimeError(f"no images were extracted from {repo_id}")
    manifest_dir = destination / "manifests"
    write_jsonl(manifest_dir / "source-images.jsonl", image_rows)
    processed = REPO_ROOT / "data" / "processed" / DATA_RELEASE / dataset_id.lower()
    write_jsonl(processed / "image-manifest.jsonl", r2_images)
    if r2_detections:
        write_jsonl(processed / "detection-annotations.jsonl", r2_detections)
        write_json(
            processed / "coco-annotations.json",
            to_coco(r2_detection_models, coco_images, ["nutrition_table"]),
        )
        yolo_labels = processed / "yolo" / "labels"
        image_dimensions = {
            str(image["id"]): (int(image["width"]), int(image["height"])) for image in coco_images
        }
        annotations_by_image: dict[str, list[DetectionAnnotation]] = {}
        for annotation in r2_detection_models:
            annotations_by_image.setdefault(annotation.image_id, []).append(annotation)
        for image_id, annotations in sorted(annotations_by_image.items()):
            image_width, image_height = image_dimensions[image_id]
            with atomic_text(yolo_labels / f"{image_id}.txt") as target:
                for annotation in sorted(annotations, key=lambda item: item.annotation_id):
                    target.write(
                        to_yolo_line(
                            annotation,
                            class_index=0,
                            image_width=image_width,
                            image_height=image_height,
                        )
                        + "\n"
                    )
        write_json(
            processed / "annotation-export-summary.json",
            {
                "coco_annotation_count": len(r2_detection_models),
                "coco_category_count": 1,
                "ocr_annotation_count": 0,
                "ocr_annotation_reason": (
                    "The official source provides region boxes but no OCR transcriptions."
                ),
                "source_annotation_type": "OFF_MANUALLY_REVIEWED_BOUNDING_BOX",
                "yolo_class_map": {"0": "nutrition_table"},
                "yolo_label_file_count": len(annotations_by_image),
            },
        )
    artifacts = artifact_rows(source_root)
    summary = {
        "acquired_at": utc_now(),
        "annotation_count": len(r2_detections) if kind == "nutrition" else len(image_rows),
        "artifacts": artifacts,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "extracted_image_bytes": total_bytes,
        "image_count": len(image_rows),
        "license": license_name,
        "payload_manifest": relative_to_repo(manifest_dir / "source-images.jsonl"),
        "payload_tree_sha256": tree_digest(
            [{"path": row["local_path"], "sha256": row["sha256"]} for row in image_rows]
        ),
        "repo_id": repo_id,
        "source_revision": revision,
        "split_counts": split_counts,
        "status": "DOWNLOADED_AND_VALIDATED",
    }
    write_json(destination / "acquisition-summary.json", summary)
    return summary
