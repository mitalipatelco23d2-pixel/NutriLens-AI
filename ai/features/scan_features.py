"""Leakage-resistant deterministic R3/R4 feature engineering."""

from __future__ import annotations

from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

FEATURE_CONTRACT_VERSION: Final = "1.0.0"
FEATURE_NAMES: Final[tuple[str, ...]] = (
    "r3_confidence",
    "ocr_character_count",
    "barcode_count",
    "product_candidate_count",
    "ingredient_count",
    "resolved_ingredient_ratio",
    "additive_count",
    "allergen_signal_count",
    "hidden_sugar_signal_count",
    "sodium_source_signal_count",
    "oil_fat_signal_count",
    "sweetener_signal_count",
    "preservative_signal_count",
    "unresolved_ingredient_count",
    "compound_ingredient_count",
    "nova_group",
)


class ScanFeatureVector(BaseModel):
    """Stable numeric features without raw text, images, identity, or labels."""

    model_config = ConfigDict(frozen=True)

    contract_version: str = FEATURE_CONTRACT_VERSION
    source_contracts: dict[str, str]
    values: dict[str, float] = Field(min_length=len(FEATURE_NAMES), max_length=len(FEATURE_NAMES))
    ordered_names: tuple[str, ...] = FEATURE_NAMES
    method: str = "DETERMINISTIC_R3_R4_FEATURES_V1"
    limitations: tuple[str, ...] = (
        "Features describe extraction evidence and must not be treated as medical outcomes.",
        "A training pipeline must split by source group before fitting to prevent leakage.",
        "Raw OCR, ingredient text, image bytes, scan identifiers, and user "
        "identifiers are excluded.",
    )

    def ordered_values(self) -> tuple[float, ...]:
        return tuple(self.values[name] for name in self.ordered_names)


def build_scan_features(scan: Any, intelligence: Any) -> ScanFeatureVector:
    """Create one bounded numeric vector from validated R3 and R4 contracts."""

    ocr_results = getattr(scan, "ocr_results", {})
    ocr_characters = sum(len(getattr(result, "text", "")) for result in ocr_results.values())
    confidence = getattr(getattr(scan, "confidence_summary", None), "numeric_score", None)
    nova_group = getattr(getattr(intelligence, "nova", None), "group_number", None)
    complexity = intelligence.complexity
    values = {
        "r3_confidence": _bounded(confidence, 0, 1),
        "ocr_character_count": _bounded(ocr_characters, 0, 50_000),
        "barcode_count": _bounded(len(getattr(scan, "barcode_results", [])), 0, 100),
        "product_candidate_count": _bounded(
            len(getattr(scan, "product_name_candidates", [])), 0, 100
        ),
        "ingredient_count": _bounded(complexity.ingredient_count, 0, 500),
        "resolved_ingredient_ratio": _bounded(
            intelligence.confidence.resolved_ingredient_ratio, 0, 1
        ),
        "additive_count": _bounded(complexity.additive_count, 0, 500),
        "allergen_signal_count": _bounded(
            sum(1 for item in intelligence.allergens if item.allergen.matched), 0, 500
        ),
        "hidden_sugar_signal_count": _bounded(len(intelligence.hidden_sugars.signals), 0, 500),
        "sodium_source_signal_count": _bounded(len(intelligence.sodium_sources.signals), 0, 500),
        "oil_fat_signal_count": _bounded(len(intelligence.oils_and_fats.signals), 0, 500),
        "sweetener_signal_count": _bounded(len(intelligence.sweeteners.signals), 0, 500),
        "preservative_signal_count": _bounded(len(intelligence.preservatives.signals), 0, 500),
        "unresolved_ingredient_count": _bounded(complexity.unresolved_count, 0, 500),
        "compound_ingredient_count": _bounded(complexity.compound_ingredient_count, 0, 500),
        "nova_group": _bounded(nova_group, 0, 4),
    }
    return ScanFeatureVector(
        source_contracts={
            "r3": str(getattr(scan, "contract_version", "UNKNOWN")),
            "r4": str(getattr(intelligence, "contract_version", "UNKNOWN")),
        },
        values=values,
    )


def _bounded(value: int | float | None, minimum: float, maximum: float) -> float:
    if value is None:
        return minimum
    return float(max(minimum, min(float(value), maximum)))
