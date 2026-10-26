"""Versioned contracts for the R4 Ingredient Intelligence Engine."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """Strict base model used by R4 contracts."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class ParsedIngredient(ContractModel):
    """One ingredient parsed from an ingredient-list string."""

    original_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    position: int = Field(ge=1)
    percentage: float | None = Field(default=None, ge=0, le=100)
    depth: int = Field(default=0, ge=0)


class IngredientParseResult(ContractModel):
    """Structured output of the first R4 ingredient parsing stage."""

    contract_version: str = "4.0.0"
    raw_text: str
    cleaned_text: str
    ingredients: list[ParsedIngredient] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class IngredientTaxonomyMatch(ContractModel):
    """Taxonomy resolution metadata for one parsed ingredient."""

    matched: bool
    taxonomy_id: str | None = None
    canonical_name: str | None = None
    match_method: str = "NONE"
    source_dataset: str | None = None
    source_version: str | None = None


class ResolvedIngredient(ContractModel):
    """Parsed ingredient plus its taxonomy resolution."""

    ingredient: ParsedIngredient
    taxonomy: IngredientTaxonomyMatch


class AdditiveMatch(ContractModel):
    """Resolved additive evidence for one ingredient token."""

    matched: bool
    taxonomy_id: str | None = None
    canonical_name: str | None = None
    external_code: str | None = None
    functional_category: str | None = None
    match_method: str = "NONE"
    source_dataset: str | None = None
    source_version: str | None = None


class IngredientAdditiveResolution(ContractModel):
    """One parsed ingredient with additive resolution evidence."""

    ingredient: ParsedIngredient
    additive: AdditiveMatch


class AllergenMatch(ContractModel):
    """Resolved allergen evidence for one ingredient token."""

    matched: bool
    taxonomy_id: str | None = None
    canonical_name: str | None = None
    match_method: str = "NONE"
    source_dataset: str | None = None
    source_version: str | None = None
    evidence_source: str | None = None
    evidence_text: str | None = None


class IngredientAllergenResolution(ContractModel):
    """One parsed ingredient with allergen resolution evidence."""

    ingredient: ParsedIngredient
    allergen: AllergenMatch


class NovaEvidence(ContractModel):
    """One transparent piece of evidence used for NOVA classification."""

    ingredient_text: str
    evidence_type: str
    evidence_value: str
    source: str


class NovaClassification(ContractModel):
    """Explainable NOVA classification output for R4."""

    group_number: int | None = Field(default=None, ge=1, le=4)
    taxonomy_id: str | None = None
    canonical_name: str | None = None

    confidence: float | None = Field(default=None, ge=0, le=1)

    classification_method: str = "UNKNOWN"

    evidence: list[NovaEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    source_dataset: str | None = None
    source_version: str | None = None


class IngredientSignal(ContractModel):
    """Explainable ingredient-category signal detected by R4."""

    ingredient_text: str
    category: str
    matched_term: str
    evidence_source: str = "R4_RULESET"


class IngredientSignalResult(ContractModel):
    """Collection of transparent ingredient-category detections."""

    signals: list[IngredientSignal] = Field(default_factory=list)


class IngredientComplexity(ContractModel):
    """Transparent, non-ML ingredient-list complexity summary."""

    ingredient_count: int = Field(ge=0)
    compound_ingredient_count: int = Field(ge=0)
    additive_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)
    level: str
    method: str = "DETERMINISTIC_V1"


class ResultConfidence(ContractModel):
    """Confidence and provenance for the deterministic R4 result."""

    score: float = Field(ge=0, le=1)
    state: str
    resolved_ingredient_ratio: float = Field(ge=0, le=1)
    source_datasets: list[str] = Field(default_factory=list)
    method: str = "DETERMINISTIC_TAXONOMY"


class NutritionEvidenceRow(ContractModel):
    label: str
    values: list[str]
    units: list[str]


class NutritionContext(ContractModel):
    """R3-extracted nutrition evidence carried into R4 without re-observation."""

    basis: str = "UNKNOWN"
    rows: list[NutritionEvidenceRow] = Field(default_factory=list)
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    method: str = "R3_NUTRITION_EXTRACTION"
    state: str = "UNKNOWN"


class R4IngredientIntelligenceResult(ContractModel):
    """Top-level governed result contract for the R4 engine."""

    contract_version: str = "4.0.0"

    parse: IngredientParseResult

    ingredient_matches: list[ResolvedIngredient] = Field(default_factory=list)
    additives: list[IngredientAdditiveResolution] = Field(default_factory=list)
    allergens: list[IngredientAllergenResolution] = Field(default_factory=list)

    hidden_sugars: IngredientSignalResult = Field(default_factory=IngredientSignalResult)
    sodium_sources: IngredientSignalResult = Field(default_factory=IngredientSignalResult)
    oils_and_fats: IngredientSignalResult = Field(default_factory=IngredientSignalResult)
    sweeteners: IngredientSignalResult = Field(default_factory=IngredientSignalResult)
    preservatives: IngredientSignalResult = Field(default_factory=IngredientSignalResult)

    nova: NovaClassification = Field(default_factory=NovaClassification)
    complexity: IngredientComplexity
    confidence: ResultConfidence
    nutrition: NutritionContext = Field(default_factory=NutritionContext)

    warnings: list[str] = Field(default_factory=list)
