from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class AnalysisContext:
    """Stable input available to optional team-owned pipeline extensions."""

    nutrition: dict[str, float]
    ingredients: list[str]
    allergens: list[str]
    health_score: float | None
    basis: str


class PipelineExtension(Protocol):
    """Adapter seam for health-risk, RAG, XAI, or later team modules."""

    key: str
    provider: str

    def analyze(self, context: AnalysisContext) -> dict[str, Any]: ...
