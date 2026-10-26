"""Conservative server classification for untrusted Android OCR evidence."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import StrEnum

from ai.food_understanding.extraction import (
    extract_ingredients,
    extract_nutrition,
    merge_ingredient_allergen_evidence,
    merge_nutrition_evidence,
)
from ai.food_understanding.nutrition_consistency import inconsistent_serving_rows
from ai.food_understanding.schemas import (
    Box,
    DetectionMethod,
    IngredientExtraction,
    NutritionExtraction,
    OCRLine,
    Region,
)
from ai.vision.regions import (
    ALLERGEN_TERMS,
    INGREDIENT_STOP_TERMS,
    INGREDIENT_TERMS,
    NUTRITION_STOP_TERMS,
    NUTRITION_TERMS,
    text_region,
)
from backend.client_inference_contract import (
    AndroidClientInferenceMode,
    ClientOcrEvidence,
)


class ClientEvidenceDecision(StrEnum):
    ACCEPTED = "CLIENT_EVIDENCE_ACCEPTED"
    FALLBACK_REQUIRED = "SERVER_FALLBACK_REQUIRED"
    INVALID = "CLIENT_EVIDENCE_INVALID"
    CONTRACT_UNSUPPORTED = "CLIENT_CONTRACT_UNSUPPORTED"


@dataclass(frozen=True)
class ClientEvidenceGatePolicy:
    min_positioned_lines: int = 6
    min_positioned_ratio: float = 0.65
    min_nutrition_rows: int = 4
    min_major_nutrients: int = 3
    min_nutrition_confidence: float = 0.58


@dataclass(frozen=True)
class ClientEvidenceGateResult:
    decision: ClientEvidenceDecision
    reasons: tuple[str, ...]
    nutrition_basis: str
    nutrition_row_count: int
    major_nutrient_count: int
    nutrition_confidence: float | None
    ingredient_evidence_present: bool
    explicit_allergen_evidence_present: bool
    positioned_line_count: int
    canonical_line_count: int
    nutrition: NutritionExtraction | None = None
    ingredients: IngredientExtraction | None = None


_MAJOR_NUTRIENTS = {
    "energy",
    "protein",
    "carbohydrate",
    "total sugar",
    "added sugar",
    "total fat",
    "saturated fat",
    "sodium",
}
_EXPLICIT_ALLERGEN_LINE = re.compile(
    r"^\s*(?:may\s+contains?|contains?|all?ergens?(?:\s+information)?)\b", re.I
)
_QUALIFIED_ALLERGEN = re.compile(
    r"\b(?:may\s+(?:also\s+)?contain|traces?\s+of|free[\s-]*from|"
    r"(?:does\s+not|do\s+not|not)\s+contain|contains?\s+no|no\s+allergens?|"
    r"(?:no|without)\s+(?:milk|soy|soya|nuts?|peanuts?|wheat|gluten|egg|fish|shellfish)|"
    r"(?:milk|soy|soya|nuts?|peanuts?|wheat|gluten|egg|fish|shellfish|allergen)[\s-]*free)\b",
    re.I,
)
_MAX_SERVING_SIZE = {
    "ml": 1_000.0,
    "g": 1_000.0,
    "l": 1.0,
    "kg": 1.0,
    "": 1_000.0,
}

_NUTRIENT_PER_100_MAX = {
    "energy": 950.0,
    "fat": 105.0,
    "protein": 105.0,
    "carbohydrates": 105.0,
    "sugars": 105.0,
    "added sugars": 105.0,
    "fiber": 105.0,
    "sodium": 45_000.0,
}

_GENERAL_VALUE_LIMITS = {
    "kcal": 5_000.0,
    "kj": 21_000.0,
    "g": 1_000.0,
    "mg": 50_000.0,
    "mcg": 500_000.0,
    "ml": 1_000.0,
    "%": 5_000.0,
    "": 50_000.0,
}


def _ocr_lines(evidence: ClientOcrEvidence) -> list[OCRLine]:
    lines: list[OCRLine] = []
    for block in evidence.blocks:
        for line in block.lines:
            box = line.bounds
            lines.append(
                OCRLine(
                    text=line.text,
                    confidence=None,
                    bounding_box=(
                        Box(
                            x=box.left,
                            y=box.top,
                            width=box.right - box.left,
                            height=box.bottom - box.top,
                        )
                        if box is not None
                        else None
                    ),
                )
            )
    return lines


def _full_region(evidence: ClientOcrEvidence, region_type: str) -> Region:
    return Region(
        region_id=f"client-full-{region_type}",
        region_type=region_type,  # type: ignore[arg-type]
        bounding_box=Box(
            x=0,
            y=0,
            width=evidence.image_width,
            height=evidence.image_height,
        ),
        method=DetectionMethod.OCR_LAYOUT,
        confidence=0.35,
        source_view_id="client-android-ocr",
    )


def _has_implausible_value(nutrition: NutritionExtraction) -> bool:
    if nutrition.serving_size_value:
        try:
            val = float(nutrition.serving_size_value)
            unit = (nutrition.serving_size_unit or "").lower().strip()
            max_serving = _MAX_SERVING_SIZE.get(unit, _MAX_SERVING_SIZE[""])
            if not math.isfinite(val) or val <= 0 or val > max_serving:
                return True
        except (TypeError, ValueError):
            return True

    for row in nutrition.table_rows:
        raw_canonical = getattr(row, "canonical_label", None) or getattr(row, "label", None) or ""
        canonical = str(raw_canonical).lower()
        values = getattr(row, "values", [])
        units = getattr(row, "units", [])
        for index, raw_value in enumerate(values):
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                return True
            unit = units[index].lower() if index < len(units) else ""
            if not math.isfinite(value) or value < 0:
                return True
            limit = _GENERAL_VALUE_LIMITS.get(unit, _GENERAL_VALUE_LIMITS[""])
            if value > limit:
                return True
            # Check 100g/ml physical limits when row basis indicates 100g or 100ml
            is_per_100 = nutrition.basis in ("PER_100_G", "PER_100_ML") or (
                index < len(nutrition.table_columns) and "100" in nutrition.table_columns[index]
            )
            if is_per_100:
                for nutrient_key, max_100 in _NUTRIENT_PER_100_MAX.items():
                    if nutrient_key in canonical and value > max_100:
                        return True
    return False


def _has_ambiguous_value_columns(nutrition: NutritionExtraction) -> bool:
    """Reject rows carrying more amount columns than the parsed headers describe."""
    declared_amount_columns = sum(1 for column in nutrition.table_columns if "%" not in column)
    if declared_amount_columns == 0:
        return False
    observed_amount_columns = max(
        (
            sum(
                1
                for index, _value in enumerate(row.values)
                if index >= len(row.units) or row.units[index] != "%"
            )
            for row in nutrition.table_rows
        ),
        default=0,
    )
    return observed_amount_columns > declared_amount_columns


def classify_client_evidence(
    evidence: ClientOcrEvidence,
    *,
    verified_image_sha256: str,
    verified_image_width: int,
    verified_image_height: int,
    rollout_mode: AndroidClientInferenceMode,
    policy: ClientEvidenceGatePolicy | None = None,
) -> ClientEvidenceGateResult:
    """Classify evidence without persisting it or making it authoritative."""
    policy = policy or ClientEvidenceGatePolicy()
    invalid_reasons: list[str] = []
    if evidence.source_image_sha256 != verified_image_sha256:
        invalid_reasons.append("SOURCE_IMAGE_SHA256_MISMATCH")
    if (evidence.image_width, evidence.image_height) != (
        verified_image_width,
        verified_image_height,
    ):
        invalid_reasons.append("SOURCE_IMAGE_DIMENSIONS_MISMATCH")
    if invalid_reasons:
        return ClientEvidenceGateResult(
            decision=ClientEvidenceDecision.INVALID,
            reasons=tuple(invalid_reasons),
            nutrition_basis="UNKNOWN",
            nutrition_row_count=0,
            major_nutrient_count=0,
            nutrition_confidence=None,
            ingredient_evidence_present=False,
            explicit_allergen_evidence_present=False,
            positioned_line_count=0,
            canonical_line_count=len(evidence.canonical_lines()),
        )

    lines = _ocr_lines(evidence)
    positioned_count = sum(line.bounding_box is not None for line in lines)
    nutrition_region = text_region(
        lines,
        terms=NUTRITION_TERMS,
        region_type="nutrition_table",
        view_id="client-android-ocr",
        stop_terms=NUTRITION_STOP_TERMS,
        max_lines=80,
    )
    ingredient_region = text_region(
        lines,
        terms=INGREDIENT_TERMS | ALLERGEN_TERMS,
        region_type="ingredient_list",
        view_id="client-android-ocr",
        stop_terms=INGREDIENT_STOP_TERMS,
        max_lines=16,
    )
    full_nutrition = extract_nutrition(lines, _full_region(evidence, "nutrition_table"))
    nutrition = extract_nutrition(lines, nutrition_region)
    if nutrition_region is None:
        nutrition = full_nutrition
    else:
        nutrition = merge_nutrition_evidence(nutrition, full_nutrition)
    full_ingredients = extract_ingredients(lines, _full_region(evidence, "ingredient_list"))
    ingredients = extract_ingredients(lines, ingredient_region)
    if ingredient_region is None:
        ingredients = full_ingredients
    else:
        ingredients = merge_ingredient_allergen_evidence(ingredients, full_ingredients)

    row_names = {row.canonical_label or row.label for row in nutrition.table_rows}
    major_count = len(row_names & _MAJOR_NUTRIENTS)
    canonical_text_lines = evidence.canonical_lines()
    has_explicit_allergen_line = any(
        _EXPLICIT_ALLERGEN_LINE.search(line) for line in canonical_text_lines
    )
    reasons: list[str] = []
    if rollout_mode is AndroidClientInferenceMode.DISABLED:
        reasons.append("ROLLOUT_DISABLED")
    if evidence.orientation_degrees != 0:
        reasons.append("ORIENTATION_REQUIRES_SERVER_FALLBACK")
    if len(lines) < policy.min_positioned_lines:
        reasons.append("INSUFFICIENT_OCR_LINES")
    positioned_ratio = positioned_count / len(lines) if lines else 0.0
    if positioned_ratio < policy.min_positioned_ratio:
        reasons.append("INSUFFICIENT_POSITIONED_LINES")
    if nutrition_region is None:
        reasons.append("NUTRITION_REGION_NOT_FOUND")
    if nutrition.basis == "UNKNOWN":
        reasons.append("NUTRITION_BASIS_UNKNOWN")
    if len(nutrition.table_rows) < policy.min_nutrition_rows:
        reasons.append("INSUFFICIENT_NUTRIENT_ROWS")
    if major_count < policy.min_major_nutrients:
        reasons.append("INSUFFICIENT_MAJOR_NUTRIENTS")
    if nutrition.confidence is None or nutrition.confidence < policy.min_nutrition_confidence:
        reasons.append("NUTRITION_CONFIDENCE_LOW")
    if has_explicit_allergen_line and not ingredients.allergen_text:
        reasons.append("EXPLICIT_ALLERGEN_EVIDENCE_LOST")
    if _QUALIFIED_ALLERGEN.search(" ".join(canonical_text_lines)):
        # R4 currently consumes an unqualified allergen-text field. Until that
        # contract supports negation/precautionary statements, do not fast-path
        # evidence whose qualifier could be erased downstream.
        reasons.append("QUALIFIED_ALLERGEN_EVIDENCE_REQUIRES_SERVER_REVIEW")
    elif ingredients.allergen_text:
        statements = [line for line in canonical_text_lines if _EXPLICIT_ALLERGEN_LINE.search(line)]
        complete_statements = [
            line for line in statements if re.search(r"\bcontains?\b", line, re.I)
        ]
        if complete_statements:
            ingredients = ingredients.model_copy(
                update={"allergen_text": "\n".join(complete_statements)}
            )
    if inconsistent_serving_rows(nutrition):
        reasons.append("INCONSISTENT_SERVING_NUTRIENT_VALUES")
    if _has_ambiguous_value_columns(nutrition):
        reasons.append("AMBIGUOUS_NUTRITION_VALUE_COLUMNS")
    if _has_implausible_value(nutrition):
        reasons.append("IMPLAUSIBLE_NUTRIENT_VALUE")

    return ClientEvidenceGateResult(
        decision=(
            ClientEvidenceDecision.ACCEPTED
            if not reasons
            else ClientEvidenceDecision.FALLBACK_REQUIRED
        ),
        reasons=tuple(reasons),
        nutrition_basis=nutrition.basis,
        nutrition_row_count=len(nutrition.table_rows),
        major_nutrient_count=major_count,
        nutrition_confidence=nutrition.confidence,
        ingredient_evidence_present=bool(ingredients.raw_text),
        explicit_allergen_evidence_present=bool(ingredients.allergen_text),
        positioned_line_count=positioned_count,
        canonical_line_count=len(lines),
        nutrition=nutrition,
        ingredients=ingredients,
    )
