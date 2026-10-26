"""Hybrid region proposals from geometry, OCR layout, and detector output."""

from __future__ import annotations

from uuid import uuid4

from ai.food_understanding.schemas import Box, DetectionMethod, OCRLine, Region
from ai.vision.yolo_engine import YOLODetection

NUTRITION_TERMS = {
    "nutrition",
    "nutritional",
    "nutrient information",
    "matrientinformation",
    "typical values",
    "valeurs moyennes",
    "gemiddelde waarden",
    "energy kcal",
    "energy kj",
}
INGREDIENT_TERMS = {
    "ingredient",
    "ingredients",
    "ngredients",
    "ngreoients",
    "composition",
    "made from",
    "made with",
}
ALLERGEN_TERMS = {"contains", "allergen", "allergen information"}
NUTRITION_STOP_TERMS = {
    "ingredients",
    "allergen",
    "contains",
    "net quantity",
    "batch no",
    "mrp",
    "use by",
    "best before",
}
INGREDIENT_STOP_TERMS = {
    "nutrition",
    "nutritional",
    "net quantity",
    "serving size",
    "batch no",
    "mrp",
    "use by",
    "best before",
    "mfg",
    "fssai",
}
PACKAGE_CLASSES = {"bottle"}


def full_frame_product_region(width: int, height: int, view_id: str) -> Region:
    return Region(
        region_id=f"region-{uuid4().hex[:12]}",
        region_type="product",
        bounding_box=Box(x=0, y=0, width=width, height=height),
        method=DetectionMethod.HEURISTIC,
        confidence=0.25,
        source_view_id=view_id,
    )


def regions_from_yolo(detections: list[YOLODetection], view_id: str) -> list[Region]:
    regions: list[Region] = []
    for detection in detections:
        if detection.label in PACKAGE_CLASSES:
            region_type = "product"
        elif detection.label in {"bowl", "cup"}:
            region_type = "plate_or_container"
        else:
            continue
        regions.append(
            Region(
                region_id=f"region-{uuid4().hex[:12]}",
                region_type=region_type,  # type: ignore[arg-type]
                bounding_box=detection.bounding_box,
                method=DetectionMethod.MODEL,
                confidence=detection.confidence,
                source_view_id=view_id,
            )
        )
    return regions


def nutrition_regions_from_custom_yolo(
    detections: list[YOLODetection], view_id: str
) -> list[Region]:
    return [
        Region(
            region_id=f"region-{uuid4().hex[:12]}",
            region_type="nutrition_table",
            bounding_box=detection.bounding_box,
            method=DetectionMethod.CUSTOM_MODEL,
            confidence=detection.confidence,
            source_view_id=view_id,
        )
        for detection in detections
        if detection.label == "nutrition_table"
    ]


def text_region(
    lines: list[OCRLine],
    *,
    terms: set[str],
    region_type: str,
    view_id: str,
    stop_terms: set[str] | None = None,
    max_lines: int = 14,
) -> Region | None:
    boxed = sorted(
        (line for line in lines if line.bounding_box is not None),
        key=lambda line: (line.bounding_box.y, line.bounding_box.x),  # type: ignore[union-attr]
    )
    anchor_index = next(
        (
            index
            for index, line in enumerate(boxed)
            if any(term in line.text.casefold() for term in terms)
            or (
                region_type == "nutrition_table"
                and "information" in line.text.casefold()
                and "allergen" not in line.text.casefold()
                and ("100" in line.text.casefold() or "per" in line.text.casefold())
            )
        ),
        None,
    )
    if anchor_index is None:
        return None

    anchor_box = boxed[anchor_index].bounding_box
    candidates: list[OCRLine] = []
    stops = stop_terms or set()
    for line in boxed[anchor_index : anchor_index + max_lines]:
        lowered = line.text.casefold()
        if candidates and any(term in lowered for term in stops):
            if (
                region_type == "nutrition_table"
                and anchor_box is not None
                and line.bounding_box is not None
                and line.bounding_box.x + line.bounding_box.width < anchor_box.x - 20
            ):
                continue
            break
        candidates.append(line)
    if not candidates:
        return None
    boxes = [line.bounding_box for line in candidates if line.bounding_box is not None]
    x1 = min(box.x for box in boxes)
    y1 = min(box.y for box in boxes)
    x2 = max(box.x + box.width for box in boxes)
    y2 = max(box.y + box.height for box in boxes)
    confidences = [line.confidence for line in candidates if line.confidence is not None]
    confidence = sum(confidences) / len(confidences) if confidences else 0.4
    return Region(
        region_id=f"region-{uuid4().hex[:12]}",
        region_type=region_type,  # type: ignore[arg-type]
        bounding_box=Box(x=x1, y=y1, width=x2 - x1, height=y2 - y1),
        method=DetectionMethod.OCR_LAYOUT,
        confidence=confidence,
        source_view_id=view_id,
    )
