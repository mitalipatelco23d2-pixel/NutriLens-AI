# R2 canonical schemas

Schema version `1.0.0` is defined by strict Pydantic models in
`scripts/data_engineering/schemas.py`. The generated JSON Schemas in
`data/schemas/r2-v1.0.0` are the machine-readable interchange contract. Unknown fields are rejected.

| Schema | Purpose | Current real output |
|---|---|---|
| `product` | Products, source IDs, barcode, original/normalized names, availability and lineage | None; full OFF products not local |
| `nutrition` | Per-100 g/ml or serving nutrients with original/normalized value and missingness | 395 USDA records |
| `ingredient-synonym` | Evidence-backed canonical name/synonym/language/review mapping | None; R1 template remains header-only |
| `taxonomy` | OFF ingredient, additive, allergen, category, label, NOVA and country terms | 24,183 records |
| `ontology-node` | FoodOn URI, multilingual labels/synonyms and deprecation | 39,682 interim nodes |
| `ontology-edge` | FoodOn source/predicate/target relationships | 46,027 interim edges |
| `image-manifest` | Rights-aware local image metadata, dimensions, checksum, annotation and split | None; no eligible images |
| `detection-annotation` | Product/label/meal class and pixel bounding box | None; source unavailable |
| `ocr-annotation` | Text-region box, exact transcription, language and review state | None; source unavailable |
| `recipe` | Source-faithful recipe, ordered structured ingredients, steps and rights lineage | None; sources gated |
| `density` | FAO density or explicitly retained partial/category row | 665 records |
| `serving` | Reported amount, measure and gram weight with geographic/method context | 123 USDA records |
| `evidence-document` | Scientific/regulatory metadata, citation, checksum and RAG eligibility | 1 WHO record |
| `population` | Aggregate country/year/indicator/value/unit with explicit missingness | None; source gated |
| `quarantine` | Rejected source snapshot, rule, reason and processing stage | 85 records |

## Shared semantics

`Lineage` contains `source_dataset`, `source_record_id`, `source_version`, `source_url`,
`input_checksum`, `pipeline_version`, `schema_version`, `processing_timestamp`, and
`license_status`. Every source-backed canonical record uses it.

`NutrientValue` contains the original and normalized value/unit, source nutrient identifier,
normalization method, `REPORTED|CONVERTED|DERIVED|ESTIMATED` origin, quality flag, or one explicit
missing reason. A value and a missing reason cannot coexist. Negative normalized nutrient values
are invalid.

Missing reasons are `UNKNOWN`, `NOT_REPORTED`, `NOT_APPLICABLE`, and `INVALID`. Record-level
duplicate classes are `EXACT_DUPLICATE`, `LIKELY_DUPLICATE`, `SOURCE_VARIANT`, and
`NOT_DUPLICATE`; outlier review classes are `VALIDATED_OUTLIER`, `SUSPECT_OUTLIER`, and `INVALID`.

The R1 ingredient-synonym CSV is intentionally not edited because raw templates are immutable. Its
R2 `ingredient-synonym` schema supplies `canonical_id`, `canonical_name`, `synonym`, `language`,
`scientific_name`, `ingredient_category`, `source`, `evidence_reference`, `version`, and
`review_status` without fabricating a row.
