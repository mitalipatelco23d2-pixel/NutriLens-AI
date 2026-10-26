"""Evaluate untrusted Android ML Kit evidence with the governed R3/R4 parsers.

This is an offline shadow-validation tool. It does not persist evidence, spend
quota, submit a scan, or make client OCR authoritative. JSON is accepted on
stdin (or from ``--input``) and a compact JSON evaluation is written to stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from ai.food_understanding.extraction import (
    extract_dates,
    extract_front_candidates,
    extract_ingredients,
    extract_nutrition,
    merge_ingredient_allergen_evidence,
    merge_nutrition_evidence,
)
from ai.food_understanding.schemas import Box, DetectionMethod, OCRLine, Region
from ai.vision.regions import (
    ALLERGEN_TERMS,
    INGREDIENT_STOP_TERMS,
    INGREDIENT_TERMS,
    NUTRITION_STOP_TERMS,
    NUTRITION_TERMS,
    text_region,
)
from backend.r4_api import get_r4_service


def _box(
    payload: dict[str, Any] | None,
    image_width: int,
    image_height: int,
) -> Box | None:
    if not payload:
        return None
    left = max(0, min(int(payload["left"]), image_width))
    top = max(0, min(int(payload["top"]), image_height))
    right = max(0, min(int(payload["right"]), image_width))
    bottom = max(0, min(int(payload["bottom"]), image_height))
    if right <= left or bottom <= top:
        return None
    return Box(
        x=left,
        y=top,
        width=right - left,
        height=bottom - top,
    )


def _safe_text(value: Any) -> str:
    """Replace malformed UTF-16 surrogates emitted by some OCR fixtures."""
    return str(value or "").encode("utf-8", errors="replace").decode("utf-8")


def _lines(result: dict[str, Any]) -> list[OCRLine]:
    image_width = int(result["image_width"])
    image_height = int(result["image_height"])
    return [
        OCRLine(
            text=_safe_text(line["text"]),
            bounding_box=_box(line.get("bounds"), image_width, image_height),
        )
        for block in result.get("blocks", [])
        for line in block.get("lines", [])
        if line.get("text", "").strip()
    ]


def _full_region(
    result: dict[str, Any],
    view_id: str,
    region_type: Literal["nutrition_table", "ingredient_list"],
) -> Region:
    return Region(
        region_id=f"{view_id}-full-{region_type}",
        region_type=region_type,
        bounding_box=Box(
            x=0,
            y=0,
            width=result["image_width"],
            height=result["image_height"],
        ),
        method=DetectionMethod.OCR_LAYOUT,
        confidence=0.35,
        source_view_id=view_id,
    )


def _evaluate_pass(
    fixture: str,
    pass_name: str,
    result: dict[str, Any],
    r4_service: Any,
) -> dict[str, Any]:
    started = perf_counter()
    view_id = f"android-{fixture}-{pass_name}"
    lines = _lines(result)
    nutrition_region = text_region(
        lines,
        terms=NUTRITION_TERMS,
        region_type="nutrition_table",
        view_id=view_id,
        stop_terms=NUTRITION_STOP_TERMS,
        max_lines=80,
    )
    ingredient_region = text_region(
        lines,
        terms=INGREDIENT_TERMS | ALLERGEN_TERMS,
        region_type="ingredient_list",
        view_id=view_id,
        stop_terms=INGREDIENT_STOP_TERMS,
        max_lines=16,
    )

    full_nutrition = extract_nutrition(lines, _full_region(result, view_id, "nutrition_table"))
    nutrition = extract_nutrition(lines, nutrition_region)
    if nutrition_region is None:
        nutrition = full_nutrition
    else:
        nutrition = merge_nutrition_evidence(nutrition, full_nutrition)

    full_ingredients = extract_ingredients(lines, _full_region(result, view_id, "ingredient_list"))
    ingredients = extract_ingredients(lines, ingredient_region)
    if ingredient_region is None:
        ingredients = full_ingredients
    else:
        ingredients = merge_ingredient_allergen_evidence(ingredients, full_ingredients)

    brands, products = extract_front_candidates(lines, view_id)
    dates = extract_dates(lines, view_id)
    r4 = r4_service.analyze(ingredients, nutrition)
    matched_allergens = [
        {
            "canonical_name": item.allergen.canonical_name,
            "match_method": item.allergen.match_method,
            "evidence_source": item.allergen.evidence_source,
            "evidence_text": item.allergen.evidence_text,
        }
        for item in r4.allergens
        if item.allergen.matched
    ]
    elapsed_ms = round((perf_counter() - started) * 1_000, 3)
    return {
        "image": {
            "width": result["image_width"],
            "height": result["image_height"],
            "transformation": result.get("test_transformation", "NONE"),
        },
        "timings_ms": {
            "decode": result.get("image_decode_ms"),
            "ocr": result.get("ocr_inference_ms"),
            "r3_r4_shadow": elapsed_ms,
        },
        "evidence": {
            "line_count": len(lines),
            "nutrition_region_found": nutrition_region is not None,
            "ingredient_region_found": ingredient_region is not None,
        },
        "nutrition": {
            "basis": nutrition.basis,
            "serving_size_value": nutrition.serving_size_value,
            "serving_size_unit": nutrition.serving_size_unit,
            "confidence": nutrition.confidence,
            "rows": [
                {
                    "canonical_label": row.canonical_label,
                    "raw_label": row.raw_label,
                    "values": row.values,
                    "raw_values": row.raw_values,
                    "units": row.units,
                    "match_confidence": row.match_confidence,
                    "confidence": row.confidence,
                }
                for row in nutrition.table_rows
            ],
        },
        "ingredients": {
            "raw_text": ingredients.raw_text,
            "allergen_text": ingredients.allergen_text,
            "confidence": ingredients.confidence,
            "allergen_confidence": ingredients.allergen_confidence,
        },
        "r4": {
            "parsed_ingredients": [item.original_text for item in r4.parse.ingredients],
            "matched_allergens": matched_allergens,
            "confidence": r4.confidence.model_dump(mode="json"),
        },
        "candidates": {
            "brand": [item.model_dump(mode="json") for item in brands],
            "product": [item.model_dump(mode="json") for item in products],
        },
        "dates": [item.model_dump(mode="json") for item in dates],
    }


def evaluate(report: dict[str, Any]) -> dict[str, Any]:
    r4_service = get_r4_service()
    results = []
    for fixture in report.get("fixtures", []):
        passes = {
            name: _evaluate_pass(
                fixture=fixture["fixture"],
                pass_name=name,
                result=fixture[name],
                r4_service=r4_service,
            )
            for name in ("cold", "warm")
            if name in fixture
        }
        results.append(
            {
                "fixture": fixture["fixture"],
                "source_image_sha256": fixture["source_image_sha256"],
                "recognizer_init_ms": fixture.get("recognizer_init_ms"),
                "passes": passes,
            }
        )
    return {
        "evaluation_mode": "OFFLINE_SHADOW_ONLY",
        "server_result_authoritative": True,
        "client_inference_contract_version": report.get("client_inference_contract_version"),
        "platform": report.get("platform"),
        "source": report.get("source"),
        "ocr_provider": report.get("ocr_provider"),
        "ocr_provider_version": report.get("ocr_provider_version"),
        "fixtures": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    raw = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
    json.dump(evaluate(json.loads(raw)), sys.stdout, indent=2)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
