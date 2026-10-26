"""Canonical Pydantic schemas for R2 outputs and future source adapters."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MissingReason(StrEnum):
    UNKNOWN = "UNKNOWN"
    NOT_REPORTED = "NOT_REPORTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    INVALID = "INVALID"


class ValueOrigin(StrEnum):
    REPORTED = "REPORTED"
    CONVERTED = "CONVERTED"
    DERIVED = "DERIVED"
    ESTIMATED = "ESTIMATED"


class DuplicateClass(StrEnum):
    EXACT_DUPLICATE = "EXACT_DUPLICATE"
    LIKELY_DUPLICATE = "LIKELY_DUPLICATE"
    SOURCE_VARIANT = "SOURCE_VARIANT"
    NOT_DUPLICATE = "NOT_DUPLICATE"


class OutlierClass(StrEnum):
    VALIDATED_OUTLIER = "VALIDATED_OUTLIER"
    SUSPECT_OUTLIER = "SUSPECT_OUTLIER"
    INVALID = "INVALID"


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Lineage(CanonicalModel):
    source_dataset: str
    source_record_id: str
    source_version: str
    source_url: str | None = None
    input_checksum: str
    pipeline_version: str = "0.1.0"
    schema_version: str = "1.0.0"
    processing_timestamp: datetime
    license_status: str


class LocalizedText(CanonicalModel):
    language: str
    text: str
    is_english_fallback: bool = False


class NutrientValue(CanonicalModel):
    source_nutrient_id: str | None = None
    original_value: float | None = None
    original_unit: str | None = None
    normalized_value: float | None = Field(default=None, ge=0)
    normalized_unit: str | None = None
    normalization_method: str | None = None
    value_origin: ValueOrigin | None = None
    missing_reason: MissingReason | None = None
    quality_flag: str = "VALID"

    @model_validator(mode="after")
    def value_or_missingness(self) -> NutrientValue:
        if self.normalized_value is None and self.missing_reason is None:
            raise ValueError("missing nutrient values require an explicit missing_reason")
        if self.normalized_value is not None and self.missing_reason is not None:
            raise ValueError("a nutrient value cannot also carry a missing_reason")
        if self.normalized_value is not None and not self.normalized_unit:
            raise ValueError("normalized_unit is required when normalized_value exists")
        return self


class NutritionRecord(CanonicalModel):
    food_id: str
    food_name: str
    basis: Literal["PER_100_G", "PER_100_ML", "PER_SERVING"] = "PER_100_G"
    energy_kj: NutrientValue | None = None
    energy_kcal: NutrientValue | None = None
    protein_g: NutrientValue | None = None
    carbohydrates_g: NutrientValue | None = None
    sugars_g: NutrientValue | None = None
    total_fat_g: NutrientValue | None = None
    saturated_fat_g: NutrientValue | None = None
    fiber_g: NutrientValue | None = None
    sodium_mg: NutrientValue | None = None
    salt_g: NutrientValue | None = None
    cholesterol_mg: NutrientValue | None = None
    calcium_mg: NutrientValue | None = None
    iron_mg: NutrientValue | None = None
    potassium_mg: NutrientValue | None = None
    vitamins: dict[str, NutrientValue] = Field(default_factory=dict)
    outlier_flags: list[str] = Field(default_factory=list)
    data_quality_score: float = Field(ge=0, le=100)
    lineage: Lineage


class ProductRecord(CanonicalModel):
    product_id: str
    source_product_id: str
    barcode: str | None = None
    barcode_valid: bool | None = None
    product_name_original: str
    product_name: str
    product_name_match_key: str
    brand_original: str | None = None
    brand: str | None = None
    brand_match_key: str | None = None
    category: str | None = None
    subcategory: str | None = None
    country: str | None = None
    languages: list[str] = Field(default_factory=list)
    quantity: float | None = Field(default=None, ge=0)
    quantity_unit: str | None = None
    serving_size: float | None = Field(default=None, ge=0)
    serving_unit: str | None = None
    ingredients_original: str | None = None
    ingredients_normalized_text: str | None = None
    nutrition_available: bool
    ingredient_data_available: bool
    image_available: bool
    nova_group: int | None = Field(default=None, ge=1, le=4)
    source_timestamp: datetime | None = None
    data_quality_score: float = Field(ge=0, le=100)
    record_status: str
    lineage: Lineage


class IngredientSynonymRecord(CanonicalModel):
    canonical_id: str
    canonical_name: str
    synonym: str
    language: str
    scientific_name: str | None = None
    ingredient_category: str | None = None
    source: str
    evidence_reference: str | None = None
    version: str
    review_status: str


class TaxonomyRecord(CanonicalModel):
    taxonomy_id: str
    taxonomy_type: str
    canonical_name: str
    localized_names: list[LocalizedText]
    synonyms: list[LocalizedText]
    parent_ids: list[str]
    external_code: str | None = None
    functional_category: str | None = None
    source_line: int
    record_status: str = "VALID"
    lineage: Lineage


class OntologyNode(CanonicalModel):
    uri: str
    labels: list[LocalizedText]
    synonyms: list[LocalizedText]
    deprecated: bool = False
    lineage: Lineage


class OntologyEdge(CanonicalModel):
    edge_id: str
    source_uri: str
    predicate: str
    target_uri: str
    lineage: Lineage


class ImageManifestRecord(CanonicalModel):
    image_id: str
    source_dataset: str
    source_record_id: str
    local_path: str
    image_type: str
    product_id: str | None = None
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    format: str
    orientation: int | None = None
    language: str | None = None
    rights_status: str
    capture_source: str
    checksum: str
    annotation_status: str
    split: Literal["TRAIN", "VALIDATION", "TEST"] | None = None
    notes: str | None = None


class BoundingBox(CanonicalModel):
    x: float = Field(ge=0)
    y: float = Field(ge=0)
    width: float = Field(gt=0)
    height: float = Field(gt=0)


class DetectionAnnotation(CanonicalModel):
    annotation_id: str
    image_id: str
    label: Literal[
        "product",
        "nutrition_table",
        "ingredient_list",
        "barcode",
        "qr_code",
        "brand_logo",
        "expiry_or_date_region",
        "food_item",
        "plate_or_container",
        "reference_object",
    ]
    bounding_box: BoundingBox
    annotation_source: str
    review_status: str


class OCRAnnotation(CanonicalModel):
    image_id: str
    region_id: str
    bounding_box: BoundingBox
    transcription: str
    language: str
    region_type: str
    annotation_source: str
    source_annotation_id: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    review_status: str


class RecipeIngredient(CanonicalModel):
    sequence: int = Field(ge=1)
    text_original: str
    name_normalized: str
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = None


class RecipeRecord(CanonicalModel):
    recipe_id: str
    title_original: str
    title: str
    cuisine: str | None = None
    ingredients: list[RecipeIngredient]
    steps: list[str]
    servings: float | None = Field(default=None, gt=0)
    preparation_minutes: int | None = Field(default=None, ge=0)
    cooking_minutes: int | None = Field(default=None, ge=0)
    difficulty: str | None = None
    dietary_tags: list[str] = Field(default_factory=list)
    source_url: str
    review_status: str
    lineage: Lineage


class DensityRecord(CanonicalModel):
    food_id: str
    food_name: str
    density: float | None = Field(default=None, gt=0)
    density_unit: Literal["g/mL"] | None = None
    specific_gravity_original: str | float | None = None
    temperature_or_condition: str | None = None
    bibliography_id: str | None = None
    source_row: int
    record_status: Literal["MEASUREMENT", "PARTIAL_REFERENCE", "CATEGORY_HEADER"]
    quality_notes: str | None = None
    lineage: Lineage


class ServingRecord(CanonicalModel):
    serving_id: str
    food_id: str
    description: str | None = None
    amount: float | None = Field(default=None, gt=0)
    measure_unit: str | None = None
    gram_weight: float | None = Field(default=None, gt=0)
    geographic_context: str | None = None
    method: str
    lineage: Lineage


class EvidenceDocument(CanonicalModel):
    document_id: str
    title: str
    organization: str
    publication_date: str | None = None
    document_type: str
    topics: list[str]
    language: str
    source_url: str
    local_path: str
    checksum: str
    license_access: str
    rag_eligibility: str
    citation_metadata: dict[str, str]
    text_extraction_status: str
    lineage: Lineage


class PopulationRecord(CanonicalModel):
    record_id: str
    country: str
    year: int
    indicator: str
    value: float | None
    unit: str
    population_group: str | None = None
    quality_flag: str
    missing_reason: MissingReason | None = None
    lineage: Lineage

    @model_validator(mode="after")
    def population_value_or_missing(self) -> PopulationRecord:
        if (self.value is None) == (self.missing_reason is None):
            raise ValueError("provide exactly one of value or missing_reason")
        return self


class QuarantineRecord(CanonicalModel):
    dataset_id: str
    source_record_id: str | None = None
    processing_stage: str
    validation_rule: str
    failure_reason: str
    source_snapshot: dict[str, Any]
    quarantined_at: datetime
