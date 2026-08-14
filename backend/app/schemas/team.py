from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class OcrLineContract(BaseModel):
    text: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class OcrContract(BaseModel):
    engine: Literal["tesseract"]
    raw_text: str | None
    lines: list[OcrLineContract]
    mean_confidence: float | None = Field(default=None, ge=0, le=1)
    selected_rotation: Literal[0, 90, 180, 270]
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalyzeTextRequest(BaseModel):
    raw_text: str = Field(min_length=1, max_length=100_000)
    lines: list[OcrLineContract] = Field(default_factory=list)


class TeamOcrSummary(BaseModel):
    engine: Literal["tesseract"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    rotation: Literal[0, 90, 180, 270]


class TeamAnalysisResponse(BaseModel):
    request_id: str
    status: Literal["success", "partial_success"]
    ocr: TeamOcrSummary | None = None
    analysis: dict[str, Any]
    health: dict[str, Any] | None = None
    explanation: dict[str, Any] | None = None
    integrations: dict[str, dict[str, Any]]
    warnings: list[str]
