"""Reusable COCO/YOLO conversion for validated R2 annotation records."""

from __future__ import annotations

from typing import Any

from scripts.data_engineering.schemas import DetectionAnnotation


def to_yolo_line(
    annotation: DetectionAnnotation,
    *,
    class_index: int,
    image_width: int,
    image_height: int,
) -> str:
    box = annotation.bounding_box
    if box.x + box.width > image_width or box.y + box.height > image_height:
        raise ValueError("bounding box extends beyond image dimensions")
    center_x = (box.x + box.width / 2) / image_width
    center_y = (box.y + box.height / 2) / image_height
    width = box.width / image_width
    height = box.height / image_height
    return f"{class_index} {center_x:.6f} {center_y:.6f} {width:.6f} {height:.6f}"


def to_coco(
    annotations: list[DetectionAnnotation],
    images: list[dict[str, Any]],
    labels: list[str],
) -> dict[str, Any]:
    image_ids = {str(image["id"]): image for image in images}
    categories = {label: index + 1 for index, label in enumerate(labels)}
    coco_annotations: list[dict[str, Any]] = []
    for index, annotation in enumerate(annotations, start=1):
        if annotation.image_id not in image_ids:
            raise ValueError(f"unknown image ID: {annotation.image_id}")
        if annotation.label not in categories:
            raise ValueError(f"unknown annotation label: {annotation.label}")
        box = annotation.bounding_box
        coco_annotations.append(
            {
                "id": index,
                "image_id": annotation.image_id,
                "category_id": categories[annotation.label],
                "bbox": [box.x, box.y, box.width, box.height],
                "area": box.width * box.height,
                "iscrowd": 0,
                "source_annotation_id": annotation.annotation_id,
            }
        )
    return {
        "images": images,
        "annotations": coco_annotations,
        "categories": [{"id": index, "name": label} for label, index in categories.items()],
    }
