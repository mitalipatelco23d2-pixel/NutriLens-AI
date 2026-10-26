# R2 data dictionary

Unless stated otherwise, strings are UTF-8, IDs are stable strings, arrays default to empty, and
units are mandatory whenever a numeric measurement exists. `Nullable` means the field may be JSON
`null`; explicit missing-reason rules still apply.

## Shared lineage and value objects

| Field | Type/unit | Nullable | Meaning and transformation | Source / downstream use |
|---|---|---:|---|---|
| `lineage.source_dataset` | string | No | R1 Dataset ID, unchanged | R1 catalogue; all downstream auditing |
| `lineage.source_record_id` | string | No | Original row/class/food/document ID | Source; trace-back and grouping |
| `lineage.source_version` | string | No | Acquired source release/snapshot | R1 acquisition manifest; reproducibility |
| `lineage.source_url` | URI string | Yes | Provider URL | R1 manifest; attribution |
| `lineage.input_checksum` | 64-char SHA-256 | No | Hash of immutable input artifact | R1 manifest; integrity |
| `lineage.pipeline_version` | string | No | R2 code contract, currently `0.1.0` | Pipeline; reproducibility |
| `lineage.schema_version` | string | No | Canonical contract, currently `1.0.0` | Schema generator; consumers |
| `lineage.processing_timestamp` | UTC datetime | No | Time the record was transformed | Pipeline; run audit |
| `lineage.license_status` | string | No | R1 licence review state | Licence register; use gate |
| `source_nutrient_id` | string | Yes | Provider nutrient ID, unchanged | USDA; nutrient mapping audit |
| `original_value`, `original_unit` | number, string | Yes | Provider-reported measurement | Source; fidelity |
| `normalized_value`, `normalized_unit` | nonnegative number, unit | Yes | Deterministically canonicalized value | R3+ features |
| `normalization_method` | string | Yes | Exact conversion or derivation formula | Pipeline; audit |
| `value_origin` | enum | Yes | `REPORTED`, `CONVERTED`, `DERIVED`, `ESTIMATED` | Pipeline; downstream filtering |
| `missing_reason` | enum | Yes | `UNKNOWN`, `NOT_REPORTED`, `NOT_APPLICABLE`, `INVALID` | Source/validation; safe missingness |
| `quality_flag` | string | No | Value-level status, e.g. `VALID` | Validation; review |

## Product and nutrition

| Field(s) | Type/unit | Nullable | Meaning and transformation | Source / downstream use |
|---|---|---:|---|---|
| `product_id`, `source_product_id` | string | No | Canonical ID and unchanged provider ID | Future OFF/custom input; R3/R4 |
| `barcode`, `barcode_valid` | digit string, boolean | Yes | Leading zeros preserved; GTIN checksum result separate | Product source; lookup/quality |
| `product_name_original`, `brand_original` | string | Brand yes | Exact source text | Product source; audit/display |
| `product_name`, `brand` | string | Brand yes | Unicode-normalized and whitespace-collapsed display form | Product source; display |
| `product_name_match_key`, `brand_match_key` | case-folded string | Brand yes | Conservative deterministic matching key | Pipeline; duplicate candidates |
| `category`, `subcategory`, `country` | string | Yes | Source classifications, not inferred | Product source/taxonomy; filtering |
| `languages` | string array | No | Normalized source language tags | Product source; multilingual routing |
| `quantity`, `quantity_unit` | nonnegative number, unit | Yes | Pack quantity; value and unit travel together | Product source; serving logic |
| `serving_size`, `serving_unit` | nonnegative number, unit | Yes | Reported serving; no inferred 100 g conversion | Product source; R9/R10 |
| `ingredients_original` | string | Yes | Ordered source ingredient declaration | Product source; R4 |
| `ingredients_normalized_text` | string | Yes | Unicode/space/separator/bracket/E-number normalization | Pipeline; R4 preprocessing |
| `nutrition_available`, `ingredient_data_available`, `image_available` | boolean | No | Source evidence availability | Product source; workflow routing |
| `nova_group` | integer 1–4 | Yes | Source-supported NOVA only | Product source; later intelligence |
| `source_timestamp` | datetime | Yes | Provider record timestamp | Product source; version review |
| `data_quality_score` | 0–100 number | No | Documented weighted engineering score | Quality framework; filtering |
| `record_status` | string | No | Validation/review status | Pipeline; downstream gate |
| `food_id`, `food_name` | string | No | Stable food ID and normalized display description | USDA; R3/R7/R9 |
| `basis` | enum | No | `PER_100_G`, `PER_100_ML`, or `PER_SERVING` | Source/mapping; correct comparison |
| `energy_kj`, `energy_kcal` | NutrientValue | Yes | kJ or kcal on the stated basis | USDA; nutrition models |
| `protein_g`, `carbohydrates_g`, `sugars_g` | NutrientValue / g | Yes | Macronutrients on the stated basis | USDA; nutrition models |
| `total_fat_g`, `saturated_fat_g`, `fiber_g` | NutrientValue / g | Yes | Fat/fibre values on stated basis | USDA; nutrition models |
| `sodium_mg`, `salt_g` | NutrientValue / mg, g | Yes | Salt may be derived as sodium × 2.5; reported value never overwritten | USDA; R4/R6/R7 |
| `cholesterol_mg`, `calcium_mg`, `iron_mg`, `potassium_mg` | NutrientValue / mg | Yes | Micronutrients on stated basis | USDA; nutrition models |
| `vitamins` | map to NutrientValue | No | Provider vitamins keyed by canonical name when mapped | Nutrition sources; extensibility |
| `outlier_flags` | string array | No | Review-only semantic threshold flags | Validation; human review |

## Ingredient, taxonomy and ontology

| Field(s) | Type | Nullable | Meaning and transformation | Source / downstream use |
|---|---|---:|---|---|
| `canonical_id`, `canonical_name`, `synonym` | string | No | Reviewed synonym identity and term | Future sourced custom rows; R4/R5 |
| `language` | language tag | No | Source language; no generated translation | Source; multilingual routing |
| `scientific_name`, `ingredient_category`, `evidence_reference` | string | Yes | Source-backed context | Reviewed source; R4/R5 evidence |
| `source`, `version`, `review_status` | string | No | Provenance and review state | Source/reviewer; release gate |
| `taxonomy_id`, `taxonomy_type` | string | No | Stable OFF-derived ID and type | OFF taxonomies; R4/R5 |
| `localized_names`, `synonyms` | LocalizedText arrays | No | Source language/text pairs; `is_english_fallback` is explicit | OFF/FoodOn; multilingual lookup |
| `parent_ids` | string array | No | Source-declared parent IDs only | OFF; hierarchy |
| `external_code`, `functional_category` | string | Yes | Source-supported E/INS or functional code/category | OFF; additive lookup |
| `source_line` | positive integer | No | Starting line of source taxonomy block | OFF; trace-back |
| `uri` | URI string | No | FoodOn class identifier | FoodOn; later graph loading |
| `labels`, `synonyms` | LocalizedText arrays | No | OWL annotation text | FoodOn; R5 |
| `deprecated` | boolean | No | OWL deprecation marker | FoodOn; filtering |
| `edge_id` | string | No | Stable relationship ID | Pipeline; later graph loading |
| `source_uri`, `predicate`, `target_uri` | URI strings | No | OWL relationship triple | FoodOn; R5 graph input |

## Images and annotations

| Field(s) | Type/unit | Nullable | Meaning and transformation | Source / downstream use |
|---|---|---:|---|---|
| `image_id`, `source_dataset`, `source_record_id` | string | No | Stable manifest/source identity | Future rights-cleared images; R3 |
| `local_path` | repository path | No | Existing readable local file | Image manifest; loader |
| `image_type`, `product_id` | string | Product yes | Panel/capture type and product link | Capture manifest; R3 |
| `width`, `height` | positive integer / px | No | Header-extracted dimensions | Image file; validation/model input |
| `format`, `orientation` | string, integer | Orientation yes | Validated image encoding/orientation | Image file; preprocessing |
| `language` | language tag | Yes | Visible/source label language | Capture metadata; OCR routing |
| `rights_status`, `capture_source` | string | No | Rights/consent and origin | Capture manifest; licence gate |
| `checksum` | SHA-256 | No | File hash and duplicate grouping key | Image bytes; leakage prevention |
| `annotation_status`, `split`, `notes` | string/enum | Yes as defined | Annotation lifecycle and deterministic split | Review/split pipeline; R3 |
| `annotation_id`, `image_id` | string | No | Detection identity and image link | Annotation source; R3 |
| `label` | enum | No | Supported package/meal class | Human annotation; detector input |
| `bounding_box.{x,y,width,height}` | number / px | No | Top-left pixel box; positive dimensions | Human/source annotation; R3/OCR |
| `region_id`, `region_type` | string | No | OCR region identity/type | OCR annotation; R3 |
| `transcription` | string | No | Exact visible source text, never translated | Human/source annotation; OCR target |
| `annotation_source`, `source_annotation_id`, `confidence`, `review_status` | string/0–1 | Some | Origin, optional provider ID/confidence, human state | Annotation source/review; QA |

## Recipe, density, serving, evidence, population and quarantine

| Field(s) | Type/unit | Nullable | Meaning and transformation | Source / downstream use |
|---|---|---:|---|---|
| `recipe_id`, `title_original`, `title` | string | No | Stable source ID and original/normalized title | Future permitted recipe source; R10 |
| `cuisine`, `difficulty`, `dietary_tags` | string/array | Yes as defined | Source labels only | Recipe source; filtering |
| `ingredients[].sequence`, `text_original`, `name_normalized`, `quantity`, `unit` | structured list | Quantity/unit yes | Original ordering plus conservative name normalization | Recipe source; R10 |
| `steps` | string array | No | Ordered source instructions | Recipe source; R10 |
| `servings`, `preparation_minutes`, `cooking_minutes` | positive numbers | Yes | Reported values only | Recipe source; R10 |
| `source_url`, `review_status` | string | No | Recipe source and review gate | Recipe source; licensing |
| `density` | positive number / g/mL | Yes | Reported FAO density only | FAO; portion conversion |
| `specific_gravity_original` | string or number | Yes | Exact source cell value | FAO; audit |
| `temperature_or_condition`, `bibliography_id`, `quality_notes` | string | Yes | Source context/reference and notes | FAO; safe interpretation |
| `source_row` | positive integer | No | Original workbook row | FAO; trace-back |
| `record_status` | enum | No | `MEASUREMENT`, `PARTIAL_REFERENCE`, `CATEGORY_HEADER` | Pipeline; filtering |
| `serving_id`, `food_id` | string | No | Portion ID and food link | USDA; R9/R10 |
| `description`, `amount`, `measure_unit`, `gram_weight` | text/positive values | Yes | Reported portion description, count/unit and mass | USDA; serving conversion |
| `geographic_context`, `method` | string | Context yes | Applicability and source method | USDA; limitation tracking |
| `document_id`, `title`, `organization`, `document_type` | string | No | Evidence identity and bibliographic description | WHO/reference source; R7/R13 |
| `publication_date` | string | Yes | Source-reported date | Evidence source; citation |
| `topics` | string array | No | Neutral document topics | Curator/source; retrieval metadata |
| `language`, `source_url`, `local_path`, `checksum` | string | No | Language, source, local artifact and hash | R1/source; citation/integrity |
| `license_access`, `rag_eligibility`, `citation_metadata`, `text_extraction_status` | string/map | No | Rights and permitted downstream state | R1 licence/evidence source; gate |
| `record_id`, `country`, `year`, `indicator`, `unit` | string/integer | No | Aggregate population observation identity/dimensions | Future approved aggregate source; R12 |
| `value` | number | Yes | Aggregate source value; never imputed | Population source; R12 |
| `population_group` | string | Yes | Source aggregate stratum | Population source; R12 |
| `quality_flag`, `missing_reason` | string/enum | Missing reason yes | Exactly one of value or missing reason | Validation; safe analysis |
| `dataset_id`, `source_record_id` | string | ID yes | Rejected record origin | Any source; remediation |
| `processing_stage`, `validation_rule`, `failure_reason` | string | No | Exact rejection context | Validator/parser; QA |
| `source_snapshot` | object | No | Minimal rejected source record | Source; reproducible review |
| `quarantined_at` | UTC datetime | No | Rejection time | Pipeline; audit |
