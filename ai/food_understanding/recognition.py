"""Conservative category, meal-item, and portion foundations."""

from __future__ import annotations

from uuid import uuid4

from ai.food_understanding.schemas import (
    CategoryCandidate,
    DetectionMethod,
    MealItem,
    OCRLine,
    PortionEstimate,
    PortionMethod,
)
from ai.vision.yolo_engine import YOLODetection

COCO_FOOD_CLASSES = {
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
}
OCR_CATEGORY_TERMS = {
    "cereal": "cereal",
    "biscuit": "biscuits",
    "cookie": "biscuits",
    "juice": "beverage",
    "milk": "dairy beverage",
    "yogurt": "yogurt",
    "yoghurt": "yogurt",
    "snack": "snack",
}


def recognize_categories(
    lines: list[OCRLine], detections: list[YOLODetection], view_id: str
) -> list[CategoryCandidate]:
    candidates = [
        CategoryCandidate(
            value=detection.label,
            confidence=detection.confidence,
            method="PRETRAINED_COCO",
            source_view_id=view_id,
        )
        for detection in detections
        if detection.label in COCO_FOOD_CLASSES
    ]
    combined = " ".join(line.text.lower() for line in lines)
    for term, category in OCR_CATEGORY_TERMS.items():
        if term in combined:
            candidates.append(
                CategoryCandidate(
                    value=category,
                    confidence=0.45,
                    method="OCR_CONTEXT",
                    source_view_id=view_id,
                )
            )
    return sorted(candidates, key=lambda candidate: candidate.confidence, reverse=True)


def meal_items(detections: list[YOLODetection], view_id: str) -> list[MealItem]:
    items: list[MealItem] = []
    for detection in detections:
        if detection.label not in COCO_FOOD_CLASSES:
            continue
        candidate = CategoryCandidate(
            value=detection.label,
            confidence=detection.confidence,
            method="PRETRAINED_COCO",
            source_view_id=view_id,
        )
        items.append(
            MealItem(
                item_id=f"item-{uuid4().hex[:12]}",
                bounding_box=detection.bounding_box,
                food_candidates=[candidate],
                confidence=detection.confidence,
                method=DetectionMethod.MODEL,
            )
        )
    return items


def unknown_portion(item_id: str | None = None) -> PortionEstimate:
    return PortionEstimate(
        item_id=item_id,
        method=PortionMethod.UNKNOWN,
        confidence=None,
        assumptions=["No reliable scale, depth, known serving, or user amount was supplied."],
    )


def user_portion(amount: float, unit: str, item_id: str | None = None) -> PortionEstimate:
    return PortionEstimate(
        item_id=item_id,
        method=PortionMethod.USER_ENTERED,
        estimated_amount=amount,
        unit=unit,
        confidence=1.0,
        assumptions=["Amount was entered by the user and was not estimated from pixels."],
    )
