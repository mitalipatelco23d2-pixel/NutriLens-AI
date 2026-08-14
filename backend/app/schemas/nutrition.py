from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


NutritionBasis = Literal["per_100g", "per_100ml", "per_serving", "unknown"]


class ManualNutritionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    basis: Literal["per_100g"] = "per_100g"
    energy_100g: float = Field(ge=0, le=10_000, description="Energy in kJ per 100 g")
    fat_100g: float = Field(ge=0, le=100)
    saturated_fat_100g: float = Field(ge=0, le=100)
    sugars_100g: float = Field(ge=0, le=100)
    fiber_100g: float = Field(ge=0, le=100)
    proteins_100g: float = Field(ge=0, le=100)
    salt_100g: float = Field(ge=0, le=100)
    sodium_100g: float = Field(ge=0, le=100)

    @field_validator("energy_100g", "fat_100g", "saturated_fat_100g", "sugars_100g", "fiber_100g", "proteins_100g", "salt_100g", "sodium_100g")
    @classmethod
    def finite_numbers_only(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("value must be finite")
        return value

    @model_validator(mode="after")
    def validate_relationships(self) -> "ManualNutritionRequest":
        if self.saturated_fat_100g > self.fat_100g:
            raise ValueError("saturated fat cannot exceed total fat")
        if self.sodium_100g > self.salt_100g:
            raise ValueError("sodium cannot exceed salt")
        return self

    def model_features(self) -> dict[str, float]:
        return self.model_dump(exclude={"basis"})


class NutrientValue(BaseModel):
    value: float
    unit: str
    source_value: float
    source_unit: str
    basis: NutritionBasis
    qualifier: Literal["less_than"] | None = None


class HealthScoreResult(BaseModel):
    performed: bool
    value: float | None = None
    model_id: str = "legacy_development_health_score_model"
    detail: str | None = None


class ManualScoreResponse(BaseModel):
    status: Literal["success"] = "success"
    basis: Literal["per_100g"] = "per_100g"
    health_score: HealthScoreResult


class ImageAnalysisResponse(BaseModel):
    status: Literal["success", "partial"]
    basis: NutritionBasis
    extracted_nutrition: dict[str, NutrientValue]
    normalized_nutrition: dict[str, float]
    ingredients: list[str]
    allergens: list[str] = Field(default_factory=list)
    missing_required_fields: list[str]
    warnings: list[str]
    health_score: HealthScoreResult
    ocr: "OcrMetadata"
    integrations: dict[str, "IntegrationStatus"]
    extensions: dict[str, dict] = Field(default_factory=dict)
    raw_text: str | None = None


from .common import IntegrationStatus, OcrMetadata  # noqa: E402

ImageAnalysisResponse.model_rebuild()
