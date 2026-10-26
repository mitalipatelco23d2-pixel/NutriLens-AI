"""End-to-end local R3 Food Understanding pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

import numpy as np

from ai.food_understanding.confidence import aggregate_scan_confidence
from ai.food_understanding.config import DEFAULT_CONFIG, R3Config
from ai.food_understanding.extraction import (
    extract_dates,
    extract_front_candidates,
    extract_ingredients,
    extract_nutrition,
    merge_ingredient_allergen_evidence,
    merge_nutrition_evidence,
)
from ai.food_understanding.image_input import validate_image_bytes
from ai.food_understanding.insight_composer import compose_scan_insights
from ai.food_understanding.local_lookup import LocalProductLookup
from ai.food_understanding.quality import assess_image_quality
from ai.food_understanding.recognition import meal_items, recognize_categories, unknown_portion
from ai.food_understanding.schemas import (
    Box,
    DetectionMethod,
    IngredientExtraction,
    InputKind,
    ManualReviewField,
    ModelMetadata,
    NutritionExtraction,
    PreprocessProfile,
    R3ScanResult,
    Region,
    Timing,
    ViewType,
)
from ai.ocr.orchestrator import OCROrchestrator
from ai.vision.barcode_qr import decode_barcodes, decode_qr
from ai.vision.nutrition_yolo_engine import NutritionYOLOEngine
from ai.vision.preprocessing import preprocess
from ai.vision.regions import (
    ALLERGEN_TERMS,
    INGREDIENT_STOP_TERMS,
    INGREDIENT_TERMS,
    NUTRITION_STOP_TERMS,
    NUTRITION_TERMS,
    full_frame_product_region,
    nutrition_regions_from_custom_yolo,
    regions_from_yolo,
    text_region,
)
from ai.vision.yolo_engine import YOLO11Engine


@dataclass(frozen=True)
class ImagePayload:
    content: bytes
    filename: str
    mime_type: str
    view_type: ViewType = ViewType.GENERAL


class FoodUnderstandingPipeline:
    def __init__(
        self,
        config: R3Config = DEFAULT_CONFIG,
        *,
        ocr: OCROrchestrator | None = None,
        detector: YOLO11Engine | None = None,
        nutrition_detector: NutritionYOLOEngine | None = None,
        lookup: LocalProductLookup | None = None,
    ) -> None:
        self.config = config
        self.ocr = ocr or OCROrchestrator(config)
        self.detector = detector or YOLO11Engine(config)
        self.nutrition_detector = nutrition_detector or NutritionYOLOEngine(config)
        self.lookup = lookup or LocalProductLookup()

    def scan(
        self,
        payloads: list[ImagePayload],
        *,
        input_kind: InputKind,
        languages: list[str] | None = None,
        trace_id: str | None = None,
    ) -> R3ScanResult:
        if not payloads:
            raise ValueError("At least one image is required.")
        started = time.perf_counter()
        scan_id = f"scan-{uuid4().hex}"
        trace = trace_id or f"trace-{uuid4().hex}"
        language_list = languages or ["en"]

        validation_ms = quality_ms = preprocessing_ms = 0.0
        detection_ms = barcode_qr_ms = ocr_ms = extraction_ms = 0.0
        metadata = []
        qualities = {}
        preprocessing_results = {}
        ocr_results = {}
        all_regions: list[Region] = []
        barcodes = []
        qr_codes = []
        brands = []
        products = []
        dates = []
        categories = []
        items = []
        warnings: list[str] = []
        models: list[ModelMetadata] = []
        selected_nutrition: NutritionExtraction | None = None
        selected_ingredients: IngredientExtraction | None = None

        for index, payload in enumerate(payloads):
            view_id = f"view-{index + 1}"
            validation_started = time.perf_counter()
            validated = validate_image_bytes(
                payload.content,
                filename=payload.filename,
                mime_type=payload.mime_type,
                view_id=view_id,
                view_type=payload.view_type,
                config=self.config,
            )
            validation_ms += (time.perf_counter() - validation_started) * 1000
            metadata.append(validated.metadata)

            quality, elapsed_quality = assess_image_quality(validated.original_bgr, self.config)
            quality_ms += elapsed_quality
            qualities[view_id] = quality
            warnings.extend(f"{view_id}: {warning}" for warning in quality.warnings)

            profile = _profile(payload.view_type, input_kind)
            processed = preprocess(
                validated.original_bgr,
                profile,
                maximum_ocr_side=self.config.ocr_max_image_side,
            )
            preprocessing_results[view_id] = processed.metadata
            preprocessing_ms += processed.metadata.elapsed_ms

            nutrition_inference = self.nutrition_detector.infer(validated.original_bgr)
            detection_ms += nutrition_inference.elapsed_ms
            models.append(nutrition_inference.metadata)
            if nutrition_inference.error_code:
                warnings.append(
                    f"{view_id}: custom nutrition detector unavailable "
                    f"({nutrition_inference.error_code})."
                )

            inference = self.detector.infer(validated.original_bgr)
            detection_ms += inference.elapsed_ms
            if inference.metadata.loaded:
                models.append(inference.metadata)
            if inference.error_code and input_kind == InputKind.MEAL:
                warnings.append(f"{view_id}: pretrained YOLO unavailable ({inference.error_code}).")

            view_regions = regions_from_yolo(inference.detections, view_id)
            custom_nutrition_regions = nutrition_regions_from_custom_yolo(
                nutrition_inference.detections, view_id
            )
            view_regions.extend(custom_nutrition_regions)
            if input_kind in {
                InputKind.IMAGE,
                InputKind.PRODUCT,
                InputKind.OCR,
                InputKind.BARCODE,
            } and not any(region.region_type == "product" for region in view_regions):
                view_regions.append(
                    full_frame_product_region(
                        validated.metadata.width, validated.metadata.height, view_id
                    )
                )

            barcode_results, barcode_elapsed = decode_barcodes(
                validated.original_bgr, view_id=view_id
            )
            qr_results, qr_elapsed = decode_qr(validated.original_bgr, view_id=view_id)
            barcode_qr_ms += barcode_elapsed + qr_elapsed
            barcodes.extend(barcode_results)
            qr_codes.extend(qr_results)
            for barcode in barcode_results:
                if barcode.bounding_box is not None:
                    view_regions.append(
                        Region(
                            region_id=f"region-{uuid4().hex[:12]}",
                            region_type="barcode",
                            bounding_box=barcode.bounding_box,
                            method=DetectionMethod.BARCODE_DETECTOR,
                            confidence=barcode.confidence,
                            source_view_id=view_id,
                        )
                    )
            for qr in qr_results:
                if qr.bounding_box is not None:
                    view_regions.append(
                        Region(
                            region_id=f"region-{uuid4().hex[:12]}",
                            region_type="qr_code",
                            bounding_box=qr.bounding_box,
                            method=DetectionMethod.BARCODE_DETECTOR,
                            confidence=1.0 if qr.decoded else None,
                            source_view_id=view_id,
                        )
                    )

            ocr = self.ocr.run(
                processed.image,
                languages=language_list,
                profile=profile,
            )
            ocr_results[view_id] = ocr
            ocr_ms += sum(attempt.elapsed_ms for attempt in ocr.attempts)
            if ocr.selected_engine is None:
                warnings.append(f"{view_id}: no local OCR engine produced text.")

            extraction_started = time.perf_counter()
            nutrition_region = max(
                custom_nutrition_regions,
                key=lambda region: region.confidence or 0.0,
                default=None,
            )
            if nutrition_region is None:
                nutrition_region = text_region(
                    ocr.lines,
                    terms=NUTRITION_TERMS,
                    region_type="nutrition_table",
                    view_id=view_id,
                    stop_terms=NUTRITION_STOP_TERMS,
                )
            ingredient_region = text_region(
                ocr.lines,
                terms=INGREDIENT_TERMS,
                region_type="ingredient_list",
                view_id=view_id,
                stop_terms=INGREDIENT_STOP_TERMS,
            )
            if ingredient_region is None:
                ingredient_region = text_region(
                    ocr.lines,
                    terms=ALLERGEN_TERMS,
                    region_type="ingredient_list",
                    view_id=view_id,
                    stop_terms=INGREDIENT_STOP_TERMS,
                    max_lines=4,
                )
            full_page_ingredient_extraction = (
                extract_ingredients(ocr.lines, ingredient_region)
                if ingredient_region is not None
                else None
            )
            extraction_ms += (time.perf_counter() - extraction_started) * 1000
            if nutrition_region is not None:
                if nutrition_region not in view_regions:
                    view_regions.append(nutrition_region)
                crop_source = (
                    validated.original_bgr
                    if nutrition_region.method == DetectionMethod.CUSTOM_MODEL
                    else processed.image
                )
                crop = _crop_region(crop_source, nutrition_region)
                table_processed = preprocess(
                    crop,
                    PreprocessProfile.NUTRITION_TABLE,
                    maximum_ocr_side=self.config.ocr_max_image_side,
                )
                preprocessing_results[f"{view_id}:nutrition"] = table_processed.metadata
                preprocessing_ms += table_processed.metadata.elapsed_ms
                table_ocr = self.ocr.run(
                    table_processed.image,
                    languages=language_list,
                    profile=PreprocessProfile.NUTRITION_TABLE,
                )
                ocr_results[f"{view_id}:nutrition"] = table_ocr
                ocr_ms += sum(attempt.elapsed_ms for attempt in table_ocr.attempts)
                local_region = _full_crop_region(
                    table_processed.image.shape[1],
                    table_processed.image.shape[0],
                    view_id,
                    "nutrition_table",
                )
                full_frame_nutrition_region = _full_crop_region(
                    processed.image.shape[1],
                    processed.image.shape[0],
                    view_id,
                    "nutrition_table",
                )
                nutrition_extraction_started = time.perf_counter()
                nutrition_extraction = extract_nutrition(table_ocr.lines, local_region).model_copy(
                    update={"region": nutrition_region}
                )
                nutrition_extraction = merge_nutrition_evidence(
                    nutrition_extraction,
                    extract_nutrition(ocr.lines, nutrition_region),
                )
                nutrition_extraction = merge_nutrition_evidence(
                    nutrition_extraction,
                    extract_nutrition(ocr.lines, full_frame_nutrition_region),
                )
                extraction_ms += (time.perf_counter() - nutrition_extraction_started) * 1000
                if selected_nutrition is None or (nutrition_extraction.confidence or 0) > (
                    selected_nutrition.confidence or 0
                ):
                    selected_nutrition = nutrition_extraction
            else:
                nutrition_extraction_started = time.perf_counter()
                full_frame_nutrition_region = _full_crop_region(
                    processed.image.shape[1],
                    processed.image.shape[0],
                    view_id,
                    "nutrition_table",
                )
                fallback_nutrition = extract_nutrition(ocr.lines, full_frame_nutrition_region)
                extraction_ms += (time.perf_counter() - nutrition_extraction_started) * 1000
                if len(fallback_nutrition.table_rows) >= 2 and (
                    selected_nutrition is None
                    or (fallback_nutrition.confidence or 0) > (selected_nutrition.confidence or 0)
                ):
                    selected_nutrition = fallback_nutrition
            if ingredient_region is not None:
                view_regions.append(ingredient_region)
                assert full_page_ingredient_extraction is not None
                if _can_reuse_full_page_ingredient_evidence(full_page_ingredient_extraction):
                    ingredient_extraction = full_page_ingredient_extraction
                else:
                    crop = _crop_region(processed.image, ingredient_region)
                    ingredient_processed = preprocess(
                        crop,
                        PreprocessProfile.INGREDIENT_LIST,
                        maximum_ocr_side=self.config.ocr_max_image_side,
                    )
                    preprocessing_results[f"{view_id}:ingredients"] = ingredient_processed.metadata
                    preprocessing_ms += ingredient_processed.metadata.elapsed_ms
                    ingredient_ocr = self.ocr.run(
                        ingredient_processed.image,
                        languages=language_list,
                        profile=PreprocessProfile.INGREDIENT_LIST,
                    )
                    ocr_results[f"{view_id}:ingredients"] = ingredient_ocr
                    ocr_ms += sum(attempt.elapsed_ms for attempt in ingredient_ocr.attempts)
                    local_region = _full_crop_region(
                        ingredient_processed.image.shape[1],
                        ingredient_processed.image.shape[0],
                        view_id,
                        "ingredient_list",
                    )
                    ingredient_extraction_started = time.perf_counter()
                    ingredient_extraction = extract_ingredients(
                        ingredient_ocr.lines, local_region
                    ).model_copy(update={"region": ingredient_region})
                    ingredient_extraction = merge_ingredient_allergen_evidence(
                        ingredient_extraction,
                        full_page_ingredient_extraction,
                    )
                    extraction_ms += (time.perf_counter() - ingredient_extraction_started) * 1000
                if selected_ingredients is None or (ingredient_extraction.confidence or 0) > (
                    selected_ingredients.confidence or 0
                ):
                    selected_ingredients = ingredient_extraction
            candidate_extraction_started = time.perf_counter()
            front_lines = ocr.lines
            if view_regions:
                non_front_boxes = [
                    r.bounding_box
                    for r in view_regions
                    if r.region_type in ("nutrition_table", "ingredient_list")
                    and r.bounding_box is not None
                ]
                if non_front_boxes:
                    front_lines = [
                        line
                        for line in ocr.lines
                        if not (
                            line.bounding_box is not None
                            and any(
                                b.x
                                <= (line.bounding_box.x + line.bounding_box.width / 2)
                                <= b.x + b.width
                                and b.y
                                <= (line.bounding_box.y + line.bounding_box.height / 2)
                                <= b.y + b.height
                                for b in non_front_boxes
                            )
                        )
                    ]
            view_brands, view_products = extract_front_candidates(front_lines, view_id)
            brands.extend(view_brands)
            products.extend(view_products)
            dates.extend(extract_dates(ocr.lines, view_id))
            categories.extend(recognize_categories(ocr.lines, inference.detections, view_id))
            if input_kind == InputKind.MEAL:
                items.extend(meal_items(inference.detections, view_id))
            extraction_ms += (time.perf_counter() - candidate_extraction_started) * 1000
            all_regions.extend(view_regions)

        nutrition = selected_nutrition or NutritionExtraction()
        ingredients = selected_ingredients or IngredientExtraction()
        portions = [unknown_portion(item.item_id) for item in items]
        if input_kind == InputKind.MEAL and not portions:
            portions = [unknown_portion()]
        lookup_status = "NOT_FOUND"
        if barcodes:
            lookup_status, _ = self.lookup.find(barcodes[0].value)

        first_quality = qualities[metadata[0].view_id]
        ocr_confidences = [
            item.confidence for item in ocr_results.values() if item.confidence is not None
        ]
        barcode_confidences = [item.confidence for item in barcodes if item.confidence is not None]
        region_confidences = [
            item.confidence for item in all_regions if item.confidence is not None
        ]
        category_confidence = categories[0].confidence if categories else None
        confidence = aggregate_scan_confidence(
            quality=first_quality,
            ocr_confidence=(sum(ocr_confidences) / len(ocr_confidences))
            if ocr_confidences
            else None,
            barcode_confidence=(
                sum(barcode_confidences) / len(barcode_confidences) if barcode_confidences else None
            ),
            region_confidences=region_confidences,
            category_confidence=category_confidence,
            nutrition_confidence=nutrition.confidence if nutrition.table_rows else 0.05,
            ingredient_confidence=ingredients.confidence if ingredients.raw_text else 0.1,
            allergen_confidence=(
                ingredients.allergen_confidence if ingredients.allergen_text else 0.1
            ),
            product_confidence=products[0].confidence if products else 0.1,
        )
        manual = _manual_review_fields(
            products=products,
            brands=brands,
            barcodes=barcodes,
            nutrition=nutrition,
            ingredients=ingredients,
            categories=categories,
            input_kind=input_kind,
            items=items,
        )
        insights = compose_scan_insights(
            nutrition=nutrition,
            ingredients=ingredients,
            brand_candidates=brands,
            product_name_candidates=products,
        )
        total_ms = (time.perf_counter() - started) * 1000
        return R3ScanResult(
            scan_id=scan_id,
            trace_id=trace,
            status="COMPLETED_WITH_WARNINGS" if warnings or manual else "COMPLETED",
            input_kind=input_kind,
            input_metadata=metadata,
            image_quality=qualities,
            preprocessing=preprocessing_results,
            regions=all_regions,
            barcode_results=barcodes,
            qr_results=qr_codes,
            ocr_results=ocr_results,
            nutrition=nutrition,
            ingredients=ingredients,
            brand_candidates=brands,
            product_name_candidates=products,
            date_candidates=dates,
            category_candidates=categories,
            meal_items=items,
            portion_estimates=portions,
            local_product_lookup_status=lookup_status,  # type: ignore[arg-type]
            confidence_summary=confidence,
            warnings=list(dict.fromkeys(warnings)),
            manual_review_fields=manual,
            models=models,
            timings=Timing(
                validation_ms=validation_ms,
                quality_ms=quality_ms,
                preprocessing_ms=preprocessing_ms,
                detection_ms=detection_ms,
                barcode_qr_ms=barcode_qr_ms,
                ocr_ms=ocr_ms,
                extraction_ms=extraction_ms,
                total_ms=total_ms,
            ),
            insights=insights,
        )


def _profile(view_type: ViewType, input_kind: InputKind) -> PreprocessProfile:
    if view_type == ViewType.NUTRITION:
        return PreprocessProfile.NUTRITION_TABLE
    if view_type == ViewType.INGREDIENTS:
        return PreprocessProfile.INGREDIENT_LIST
    if input_kind == InputKind.BARCODE:
        return PreprocessProfile.BARCODE
    if input_kind == InputKind.MEAL:
        return PreprocessProfile.MEAL
    if input_kind == InputKind.OCR:
        return PreprocessProfile.OCR_LABEL
    return PreprocessProfile.GENERAL_PRODUCT


def _crop_region(image: np.ndarray, region: Region) -> np.ndarray:
    array = np.asarray(image)
    box = region.bounding_box
    x1 = max(0, min(array.shape[1] - 1, int(box.x)))
    y1 = max(0, min(array.shape[0] - 1, int(box.y)))
    x2 = max(x1 + 1, min(array.shape[1], int(box.x + box.width)))
    y2 = max(y1 + 1, min(array.shape[0], int(box.y + box.height)))
    return array[y1:y2, x1:x2].copy()


def _full_crop_region(
    width: int,
    height: int,
    view_id: str,
    region_type: Literal["nutrition_table", "ingredient_list"],
) -> Region:
    return Region(
        region_id=f"region-{uuid4().hex[:12]}",
        region_type=region_type,
        bounding_box=Box(x=0, y=0, width=width, height=height),
        method=DetectionMethod.OCR_LAYOUT,
        confidence=None,
        source_view_id=view_id,
    )


def _can_reuse_full_page_ingredient_evidence(extraction: IngredientExtraction) -> bool:
    """Avoid a redundant crop pass only when both critical signals are already strong."""
    return bool(
        extraction.raw_text.strip()
        and extraction.allergen_text.strip()
        and (extraction.confidence or 0.0) >= 0.9
        and (extraction.allergen_confidence or 0.0) >= 0.9
    )


def _manual_review_fields(**values: object) -> list[ManualReviewField]:
    fields: list[ManualReviewField] = []
    checks = (
        ("product_name", values["products"], "No reliable product-name candidate."),
        ("brand", values["brands"], "No reliable brand candidate."),
        ("barcode", values["barcodes"], "No barcode was decoded."),
        (
            "nutrition_text",
            getattr(values["nutrition"], "raw_table_text", ""),
            "No nutrition table was extracted.",
        ),
        (
            "ingredient_text",
            getattr(values["ingredients"], "raw_text", ""),
            "No ingredient list was extracted.",
        ),
        ("food_category", values["categories"], "No reliable food category was identified."),
    )
    for field, value, reason in checks:
        if not value:
            fields.append(ManualReviewField(field=field, reason=reason, current_value=None))
    if values["input_kind"] == InputKind.MEAL and not values["items"]:
        fields.append(
            ManualReviewField(
                field="meal_item",
                reason="The pretrained general detector found no supported COCO food class.",
            )
        )
    fields.append(
        ManualReviewField(
            field="serving_amount",
            reason="Enter a serving because pixels alone do not provide a reliable physical scale.",
        )
    )
    return fields
