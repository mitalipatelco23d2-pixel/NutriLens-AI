"""Versioned API routes for governed R4 Ingredient Intelligence."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ai.food_understanding.schemas import IngredientExtraction
from ai.food_understanding.store import ScanNotFoundError
from ai.ingredient_intelligence.schemas import R4IngredientIntelligenceResult
from ai.ingredient_intelligence.service import IngredientIntelligenceService
from ai.ingredient_intelligence.taxonomy import (
    load_additive_taxonomy,
    load_allergen_taxonomy,
    load_ingredient_taxonomy,
    load_nova_taxonomy,
    load_runtime_bundle,
)
from backend.auth import User, current_user
from backend.r3_api import get_owned_scan_result

router = APIRouter(prefix="/api/v1/ingredient-intelligence", tags=["R4 Ingredient Intelligence"])
DATA_ROOT = Path("data/processed/r2-v0.1.0")
RUNTIME_BUNDLE = Path("data/runtime/r4-taxonomies-v0.1.0.json.gz")


class IngredientAnalysisRequest(BaseModel):
    """Manual or corrected R3-equivalent ingredient input."""

    raw_text: str = Field(max_length=50_000)
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)


@lru_cache(maxsize=1)
def get_r4_service() -> IngredientIntelligenceService:
    """Load the governed R2 taxonomies once per API process."""

    if RUNTIME_BUNDLE.is_file():
        ingredients, additives, allergens, nova = load_runtime_bundle(RUNTIME_BUNDLE)
        return IngredientIntelligenceService(ingredients, additives, allergens, nova)
    full = DATA_ROOT / "full" / "ingredients"
    return IngredientIntelligenceService(
        ingredient_entries=load_ingredient_taxonomy(full / "off_ingredient.jsonl"),
        additive_entries=load_additive_taxonomy(full / "off_additive.jsonl"),
        allergen_entries=load_allergen_taxonomy(full / "off_allergen.jsonl"),
        nova_entries=load_nova_taxonomy(full / "off_nova_group.jsonl"),
    )


@router.post("/analyze", response_model=R4IngredientIntelligenceResult)
def analyze_ingredients(payload: IngredientAnalysisRequest) -> R4IngredientIntelligenceResult:
    """Analyze supplied/corrected text without performing OCR."""

    extraction = IngredientExtraction(
        raw_text=payload.raw_text,
        confidence=payload.extraction_confidence,
    )
    return get_r4_service().analyze(extraction)


@router.post("/scan/{scan_id}", response_model=R4IngredientIntelligenceResult)
def analyze_scan_ingredients(
    scan_id: str, user: Annotated[User, Depends(current_user)]
) -> R4IngredientIntelligenceResult:
    """Run R4 directly from the persisted R3 IngredientExtraction contract."""

    try:
        scan = get_owned_scan_result(scan_id, user)
    except ScanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scan not found or already deleted.") from exc
    return get_r4_service().analyze(scan.ingredients, scan.nutrition)
