"""NutriLens X R3 local Food Understanding Engine."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai.food_understanding.pipeline import FoodUnderstandingPipeline

__all__ = ["FoodUnderstandingPipeline"]


def __getattr__(name: str) -> Any:
    if name == "FoodUnderstandingPipeline":
        from ai.food_understanding.pipeline import FoodUnderstandingPipeline

        return FoodUnderstandingPipeline
    raise AttributeError(name)
