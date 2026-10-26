# R2 — Dataset Engineering Completion Report

Verified 2026-08-08. Dataset/pipeline version `0.1.0`; schema version `1.0.0`.

## A. Starting state

R1 supplied 57 catalogue/licence records, 59 module mappings across the frozen 15 modules, 15
immutable header-only custom templates, and 11 checksum-verified local artifacts totalling
54,054,088 bytes (51.55 MiB): seven OFF taxonomies, USDA Foundation Foods, FoodOn OWL,
FAO/INFOODS Density, and a WHO Healthy Diet PDF. The R2 audit confirmed their formats, licences,
privacy states, sizes and intended transformations before processing.

Full OFF products, Indian product/OCR images, recipes, population data and several references were
not permitted local inputs because they remain available-but-not-downloaded, deferred,
registration-required, manual-download-required, unavailable, or licence-review-required. No gate
was bypassed.

## B. Processing pipelines created

| Pipeline | Purpose |
|---|---|
| R1-aware source registry | Accept only `DOWNLOADED`, checksum-matching sources and attach licence lineage |
| Top-level sample/full runner | Execute ordered transformations, raw checks, quality, splits, versions and manifests |
| OFF streaming taxonomy parser | Normalize ingredients, additives, allergens, categories, labels, NOVA and countries |
| USDA ZIP parser | Extract foods, long nutrients, canonical nutrition and reported portions without archive extraction |
| FoodOn streaming OWL parser | Extract URI nodes, multilingual labels/synonyms and subclass edges |
| FAO XLSX parser | Preserve measurements, partial references and category rows without inferred densities |
| Evidence metadata processor | Produce citation/rights metadata without RAG chunking, embeddings or unapproved text reuse |
| Product/text/ingredient normalizers | Preserve originals and create conservative display/matching/preprocessing forms |
| Unit and nutrient utilities | Canonical mass/volume/energy conversion and explicit sodium/salt derivation |
| Image validator | Detect missing/zero/corrupt/unsupported files, dimensions and SHA duplicates |
| Annotation converters | Validate canonical boxes and export reusable YOLO/COCO structures |
| Recipe and population adapters | Validate future source-backed records; produce no rows without permitted inputs |
| Quality/quarantine tools | Transparent scores, duplicates, missingness, distributions, outliers and reject preservation |
| Deterministic splitter | Stable group hashing and leakage validation |
| JSON Schema/manifest validators | Generate/verify schema, payload, checksum, lineage, count, version and forbidden-artifact rules |

## C. Canonical schemas

Fifteen strict Pydantic and JSON Schema contracts at `1.0.0` were created: product, nutrition,
ingredient synonym, taxonomy, ontology node, ontology edge, image manifest, detection annotation,
OCR annotation, recipe, density, serving, evidence document, population, and quarantine. Shared
lineage, localized-text, nutrient-value, bounding-box and recipe-ingredient objects enforce their
nested fields. The immutable R1 synonym template was not edited; the new canonical schema contains
the required evidence/review fields and no fabricated seed row.

## D. Dataset processing summary

| Dataset | Input | Output | Rejected | Duplicate | Output size |
|---|---:|---:|---:|---:|---:|
| OFF additives | 668 | 668 | 0 | 0 | 4,348,143 B |
| OFF allergens | 27 | 27 | 0 | 0 | 381,263 B |
| OFF categories | 14,598 | 14,575 | 23 | 23 | 18,554,191 B |
| OFF countries | 268 | 268 | 0 | 0 | 4,098,639 B |
| OFF ingredients | 5,629 | 5,616 | 13 | 13 | 10,600,258 B |
| OFF labels | 3,029 | 3,023 | 6 | 6 | 3,463,411 B |
| OFF NOVA | 6 | 6 | 0 | 0 | 36,418 B |
| USDA Foundation | 395 foods | 395 nutrition + 123 servings + 16,965 long nutrients | 43 nutrient rows | 0 | 13,475,286 B |
| FoodOn | 39,682 classes | 39,682 nodes + 46,027 edges | 0 | 0 | 63,145,661 B |
| FAO Density | 665 | 665 | 0 | 0 | 518,662 B |
| WHO Healthy Diet | 1 document | 1 metadata record | 0 | 0 | 1,380 B |

Primary stage output is 64,926 records with 85 rejected/quarantined inputs. The manifest contains
103,069 interim records / 74,801,252 bytes, 25,367 processed records / 43,822,060 bytes, 85
quarantine records / 35,713 bytes, and 395 split rows / 14,288 bytes.

## E. Normalization summary

- Mass/volume aliases normalize mcg/µg/μg, mg, g, kg, mL and L; energy uses exactly 4.184 kJ/kcal.
- USDA source nutrient IDs, original numbers/units and per-100-g basis remain. Missing values are
  `NOT_REPORTED`, never zero. Reported, converted, derived and estimated origins are separate.
- Salt derived from sodium uses `salt_g = sodium_mg × 2.5 / 1000`; it never overwrites a report.
- Product/brand originals remain beside conservative Unicode/whitespace display and case-folded
  matching forms. Barcodes stay strings and have a separate GTIN validity result.
- Ingredient preprocessing preserves order/original text and deterministically normalizes Unicode,
  spacing, separators, brackets, percentages, E-numbers and INS notation only.
- OFF source multilingual names/synonyms, parent relations, additive E-codes and declared
  functional categories are retained. Language tags are normalized safely; no translation is
  generated. FoodOn URIs remain unchanged.

## F. Annotation summary

Image-manifest, packaged-food/meal detection, bounding-box and OCR transcription schemas exist.
YOLO line and COCO JSON conversions are tested. Annotation guidance covers target definitions,
ambiguous/partial/overlapping/occluded/glare/multilingual/truncated/low-resolution cases and
exclusions.

Actual source images, detection annotations, OCR annotations and meal annotations are all zero and
marked `BLOCKED_BY_DATA_AVAILABILITY`. This is correct because R1 contains no rights-cleared image
payload; no image or annotation was fabricated.

## G. Quality summary

Schema/semantic, unit, missingness, barcode, Unicode, image, URI, ID, checksum, licence, privacy,
lineage and split checks pass. The transparent quality formula is 25% schema + 20% provenance +
15% licence + 20% completeness + 10% uniqueness + 10% unit validity. USDA and FAO score 96.0;
three OFF taxonomies with duplicate source IDs score 99.9; the remaining pipeline contracts score
100. These are engineering scores, not clinical/scientific quality claims.

USDA coverage ranges from 92.9% for calcium/iron/potassium to 22.5% for cholesterol; exact rates
are in the statistics report. Two USDA records retain review-only outlier flags. Forty-two OFF
duplicate IDs and 43 invalid/unjoinable USDA nutrient rows make up the 85-row quarantine. FoodOn
retains 404 URI classes without direct labels. No unusual-but-possibly-valid row is automatically
deleted.

## H. Dataset splits

Stable SHA-256 group hashing uses seed `20260808` and a documented default 70/15/15 policy. USDA
produced 281 TRAIN, 62 VALIDATION and 52 TEST records; the 200-row sample produced 137/37/26. Zero
group IDs cross splits. A repeat generation produced byte-identical SHA-256
`682d501fa7d493f03eb323869560f3adb7570b83ee8458565665d8e55694ffd7`.

Image/OCR/product/recipe/population split files are correctly absent because eligible real inputs
are absent.

## I. Provenance/versioning

Every source-backed canonical record carries dataset/source record ID, source URL/version, original
input SHA-256, pipeline/schema version, processing timestamp and R1 licence review state. Version
metadata points to the R1 input manifest and relative R2 output manifest. Both sample and full runs
produce transformation manifests, output record/size/SHA manifests and checksum lists. Full payload
validation and all 11 raw post-run checksum comparisons pass.

## J. Testing

- R1 governance/local acquisition validator: PASS; all 11 downloads match size and SHA-256.
- Sample pipeline: PASS in 2.6 s on the final warm-cache run; 1,634 primary records, 13 quarantine rows, raw immutability PASS.
- Full pipeline: PASS in 109.3 s; 64,926 primary records, 85 quarantine rows, raw immutability PASS.
- R2 payload/schema/manifest/lineage/split validator: PASS; output-manifest verification PASS.
- Python: Ruff check PASS, Ruff format PASS (55 files), strict mypy PASS (50 files), pytest **44 passed**.
- CI fixture: PASS; one explicitly synthetic non-nutrition software record, zero trained models.
- Capability register: PASS; 145 unique capabilities across exactly 15 modules.
- Web: ESLint PASS, TypeScript PASS, Vitest **3 passed**, Next.js production build PASS.
- Flutter: format PASS (0 changed), analyzer PASS, regular suite **3 passed / 1 live case skipped**;
  separately enabled live health test **1 passed**.
- Docker/health: Compose config PASS; web, API, PostgreSQL, MongoDB, Neo4j and Redis all healthy;
  API health and web HTTP 200 PASS.
- Pre-commit: PASS across every non-ignored repository file.

## K. Known limitations

- No full OFF product export or representative Indian packaged-product dataset is local.
- No rights-cleared Indian label/meal images or OCR annotations exist; real visual QA is blocked.
- OFF contains source terms for 17/22 scheduled Indian languages, but coverage is uneven and not
  expert-validated; Bodo, Dogri, Konkani, Maithili and Manipuri have zero terms.
- USDA nutrition and portions are US-centric and incomplete; only deterministic mappings are made.
- FAO density coverage/context is incomplete; 165 rows are partial references or category headers.
- Recipe, Indian population, regulatory and custom knowledge sources remain gated by access,
  licence, privacy review or future collection.
- WHO is metadata/citation-only; text extraction and RAG remain out of R2 scope.
- Deterministic duplicate/outlier flags need later human/domain review and are not medical claims.

## L. Capability register update

Exactly one capability record changed: `NLX-113` (Dataset management). Its overall status remains
`TESTED`; its evidence now points to this R2 completion report and its note records implemented,
tested schemas, transformations, quality/quarantine, lineage, checksums, versions and safe splits.
No scanner, OCR, ingredient intelligence, health, recommendation or other model capability was
promoted.

## M. R2 exit checklist

| Criterion | Result | Evidence / explanation |
|---|---|---|
| R1 remains valid; raw data immutable; checksums match | PASS | R1/download validators and before/after hashes |
| R2 audit and required data layers | PASS | Audit plus interim/processed/annotations/splits/schemas/quality |
| Engineering, missing-value and sodium/salt standards | PASS | Standards and tested normalization utilities |
| Product schema and conservative product/brand normalization | PASS | Pydantic/JSON Schema and adapter tests |
| Nutrition schema, units and explicit value origins | PASS | USDA canonical output and tests |
| Ingredient preprocessing and synonym schema | PASS | Original/order preservation; no fabricated synonym row |
| OFF taxonomy transformations | PASS | All seven local taxonomy files processed |
| USDA transformation | PASS | Full foods/nutrients/nutrition/servings outputs |
| FoodOn transformation | PASS | Full URI nodes and edges |
| Image validation and manifest schema | PASS | Integrity/dimension/duplicate utilities tested |
| Real image annotation set | BLOCKED_BY_SOURCE_AVAILABILITY | Zero rights-cleared R1 images; not a critical engineering gap |
| Detection/OCR schemas, converters and guidelines | PASS | Machine schemas, YOLO/COCO utilities and guidance |
| Recipe canonical schema/adapter | PASS | Tested contract; real source remains access-gated |
| Density and serving schemas/processing | PASS | Full FAO and USDA outputs |
| Evidence metadata processing | PASS | WHO citation/rights metadata; no embeddings/chunks |
| Population aggregate schema | PASS | Explicit missingness/PII-safe contract; source gated |
| Duplicate, validation, outlier and quarantine workflows | PASS | 85 preserved rejects; two review flags |
| Quality framework and reports | PASS | Transparent formula and computed full report |
| Split policy and deterministic available-data split | PASS | Byte-reproducible USDA split; zero leakage |
| Versioning, transformation manifests and output checksums | PASS | Sample/full version, manifest and SHA artifacts |
| Mandatory source lineage | PASS | Full record validation to R1 IDs/checksums |
| Data dictionary and human/machine schema documentation | PASS | Data dictionary, schema guide and 15 JSON Schemas |
| Statistics and data-quality reports | PASS | Computed reports, no invented counts |
| Licence and privacy validation | PASS | Only permitted R1 downloads; no person-level data |
| Sample and full-local modes | PASS | Both executed successfully |
| Processing scripts and CLI documentation | PASS | Modular commands, `--help`, README |
| R2 tests; R0/R1 regression checks; CI | PASS | Exact results in section J; CI updated lightly |
| ₹0/open-source/local constraint | PASS | Python/Pydantic/stdlib; no paid service |
| No model training/indexing/later application work | PASS | Artifact scan and scope review |
| No fabricated product/nutrition/evidence/annotation data | PASS | Real outputs only; CI fixture explicitly non-data |

The sole blocked row is a non-critical source availability condition expressly permitted by the R2
definition: the engineering schemas, converters and guidelines are complete, while false image
annotations are prohibited.

## N. Final determination

**R2 — DATASET ENGINEERING: 100% COMPLETE**
