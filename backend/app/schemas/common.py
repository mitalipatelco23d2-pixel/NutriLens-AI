from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    status: Literal["error"] = "error"
    error: ErrorDetail


class DependencyStatus(BaseModel):
    ready: bool
    detail: str
    metadata: dict[str, Any] | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    dependencies: dict[str, DependencyStatus]


class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"
    service: str = "nutrilens-backend"


class IntegrationStatus(BaseModel):
    status: Literal["fallback", "not_configured", "available", "error"]
    provider: str
    detail: str | None = None


class OcrMetadata(BaseModel):
    engine: str = "tesseract"
    language: str
    preprocessing_applied: bool
    mean_confidence: float | None = Field(default=None, ge=0, le=100)
    selected_rotation: Literal[0, 90, 180, 270] = 0
    selected_psm: int = Field(default=6, ge=3, le=13)
    attempted_psms: list[int] = Field(default_factory=lambda: [6, 11])
    candidate_count: int = Field(default=1, ge=1)
    selected_region: Literal["full", "dense_text_crop", "nutrition_table"] = "full"
    image_width: int = Field(gt=0)
    image_height: int = Field(gt=0)
