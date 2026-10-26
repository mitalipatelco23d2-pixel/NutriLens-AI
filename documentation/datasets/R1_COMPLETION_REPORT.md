# R1 dataset collection completion report

Verification date: 2026-08-08
Scope: R1 collection, governance, provenance, rights, acquisition, schemas, and gaps only
Cost introduced: ₹0

## A. Dataset audit

Before R1, `data/` contained only R0 boundary folders and placeholder README files. There were no
dataset payloads, sample files, catalogues, license records, evidence manifests, custom
dictionaries, acquisition scripts, or checksum records. `databases/`, `ai/`, and `reports/`
contained no populated data assets. No existing dataset was duplicated and no accidental large
dataset was tracked. The detailed pre-change record is `R1_AUDIT.md`.

## B. Sources added

The catalogue contains 57 rows across the required groups:

- Product/nutrition: Open Food Facts CSV/JSONL, seven OFF taxonomies, OFF images, and USDA
  Foundation, Branded, and FNDDS releases.
- Knowledge/ontology: FoodOn, FoodKG construction resources, and Wikidata lexemes.
- Computer vision/OCR: GroceryStoreDataset, SKU-110K, TextOCR, SynthText, COCO-Text, and two
  Indian product/label collection plans.
- Recipes/cooking: Recipe1M+, RecipeDB, Recipe Commons, and a custom Indian recipe plan.
- Scientific/regulatory: WHO healthy-diet/sugar/sodium guidance, ICMR-NIN DGI/IFCT/RDA,
  FSSAI labelling/additives, EFSA OpenFoodTox, and FDA additive/allergen/label references.
- Population/research: FAOSTAT, WHO GHO, and NFHS-5/DHS.
- Serving/language: FAO/INFOODS Density DB, Unicode CLDR, and BHASHINI/ULCA catalogue.
- Custom future data: the 15 frozen minimum schemas for synonyms, sugars, sodium, fats/oils,
  additives, preservatives, allergens, suitability rules, alternatives, servings, density,
  multilingual terms, evidence, Indian images, and Indian recipes.

Each source is classified as a dataset, ontology, regulatory reference, scientific reference, or
knowledge source. Provider pages and regulations are not represented as ML training data.

## C. Acquisition status

| Status | Count | Meaning in this R1 state |
|---|---:|---|
| `DOWNLOADED` | 11 | Local artifact, manifest row, byte size, and SHA-256 all verified |
| `AVAILABLE` | 16 | Official route documented; not required locally for R1 |
| `MANUAL_DOWNLOAD_REQUIRED` | 6 | Human-controlled terms/site or multi-layer acquisition |
| `REGISTRATION_REQUIRED` | 2 | Recipe1M+ and NFHS-5 approval flows |
| `LICENSE_REVIEW_REQUIRED` | 5 | Rights must be resolved before ingest/reuse |
| `DEFERRED` | 16 | Custom schemas exist; actual collection belongs later |
| `UNAVAILABLE` | 1 | SynthText has no verified current official download |
| `PARTIALLY_DOWNLOADED` / `NOT_REVIEWED` | 0 | No source is ambiguously left in these states |

The 11 local artifacts are seven OFF taxonomies, USDA Foundation Foods April 2026, the stable
FoodOn OWL snapshot, the WHO healthy-diet PDF, and FAO/INFOODS Density DB v2.0. An FSSAI URL that
returned an HTML application shell was rejected and reclassified as manual rather than recorded
as a PDF download.

## D. Storage summary

Total verified local source payload: **54,054,088 bytes (51.55 MiB)**. Payloads are Git-ignored.

| Catalogue category | Local bytes | MiB |
|---|---:|---:|
| Food ontology | 40,429,965 | 38.56 |
| Product taxonomies | 4,664,967 | 4.45 |
| Food composition | 3,825,517 | 3.65 |
| Ingredient taxonomy | 2,645,385 | 2.52 |
| Additive taxonomy | 1,114,125 | 1.06 |
| Geography taxonomy | 1,092,770 | 1.04 |
| Serving/density | 131,549 | 0.13 |
| Allergen taxonomy | 75,083 | 0.07 |
| Scientific/regulatory | 74,727 | 0.07 |

No large or very-large dataset was automatically acquired. Original bytes remain untouched.

## E. Licensing summary

The license register has one row for every catalogue entry: 17 `VERIFIED`, 11
`VERIFIED_RESTRICTED`, 3 `VERIFIED_WITH_CAVEATS`, 5 `PARTIALLY_VERIFIED`, 5
`REQUIRES_LEGAL_REVIEW`, and 16 `PENDING_CUSTOM_COLLECTION`. Twenty-four sources explicitly allow
academic use; additional reference/research sources have source-specific conditions. Commercial
rights are separately tracked and never inferred from academic access.

Important restrictions remain visible: OFF database share-alike duties; image-specific rights;
SKU-110K non-commercial academic use; RecipeDB non-commercial share-alike; Recipe1M+/NFHS
registration; WHO/FSSAI/ICMR reference/reproduction limits; and item-specific BHASHINI/Recipe
Commons terms. This is a governance success, not an unresolved R1 defect: restricted material is
blocked until its stated gate is satisfied.

## F. Module coverage

| # | Frozen module | Identified R1 support |
|---:|---|---|
| 1 | Food Understanding Engine | OFF products/images, GroceryStoreDataset, SKU-110K, TextOCR, Indian image/OCR plans |
| 2 | Ingredient Intelligence Engine | OFF ingredient/additive/allergen taxonomies, FSSAI additives, custom synonym/sugar/sodium schemas |
| 3 | Food Knowledge Intelligence | FoodOn, FoodKG, Wikidata lexemes |
| 4 | Personalized Health Intelligence | WHO guidance, ICMR guidance/RDA, suitability-rule schema |
| 5 | Explainable AI Engine | Evidence schema, WHO sugar/sodium, EFSA OpenFoodTox |
| 6 | Recommendation Intelligence Engine | OFF products, USDA Foundation, alternatives schema |
| 7 | Personal Nutrition Intelligence | USDA Foundation, ICMR IFCT, OFF products |
| 8 | Smart Cooking & Pantry Intelligence | RecipeDB, Recipe1M+, Indian recipe schema, FNDDS, FAO density, serving/density schemas |
| 9 | Nutrition Analytics & Visualization | OFF products, USDA Foundation, FAOSTAT |
| 10 | Population & Research Intelligence | FAOSTAT, WHO GHO, registration-gated NFHS-5 |
| 11 | AI Nutrition Assistant | Evidence corpus, WHO healthy-diet, FSSAI labelling |
| 12 | Data & AI Infrastructure | OFF countries, FoodOn, CLDR, BHASHINI catalogue |
| 13 | Backend Services | OFF products and USDA Foundation integration inputs |
| 14 | Cross-Platform User Experience | Indian image plan, CLDR, multilingual terminology schema |
| 15 | Security, Privacy & Cloud Infrastructure | NFHS privacy gate, OFF image rights, custom image consent/rights manifest |

The matrix contains 59 mappings and exactly the 15 frozen module names. Data availability does not
mark any downstream engine or model implemented.

## G. Custom dataset requirements

Fifteen header-only templates define later collection for Indian product images and label OCR,
Indian recipes, ingredient synonyms, hidden sugar/sodium, fats/oils, additives, preservatives,
allergens, health-suitability rules, alternatives, serving sizes, density, all 22 scheduled Indian
languages plus English, and the evidence corpus. All templates include source/reference,
version, and review fields; claim-bearing schemas include evidence fields. No fake row,
translation, nutrition value, density, medical rule, or annotation was inserted.

## H. Dataset gaps

Sixteen explicit gaps are tracked in `dataset-gaps.md`. The highest-risk gaps are rights-cleared
Indian packaging images, Indian nutrition-table OCR labels, uneven scheduled-language coverage,
Indian ingredient synonyms, India-specific portions/densities, permissioned Indian recipes, and
clinically reviewed suitability evidence. Workarounds and target roadmap releases are recorded
without starting those later releases.

## I. Verification

- R1 governance/local acquisition validation: pass; 57 unique catalogue IDs, 57 license rows,
  59 valid module mappings, 15 custom templates, and exactly 15 module names.
- Download verification: pass; 11/11 artifacts match recorded byte sizes and SHA-256 hashes.
- Python: Ruff check/format pass; strict mypy pass; pytest **13 passed**.
- Web: ESLint pass; TypeScript pass; Vitest **3 passed**; Next.js production build pass;
  production dependency audit reports **0 vulnerabilities**.
- Flutter: format pass; analyzer reports no issues; normal suite **3 passed, 1 intentionally
  skipped live case**; separately enabled live API test **1 passed**; debug bundle build pass.
- Infrastructure: Docker Compose config valid; API, web, PostgreSQL, MongoDB, Neo4j, and Redis all
  healthy; live API health contract passed.
- Capability register: 145 unique capabilities across exactly 15 modules; only `NLX-113` gained
  honest R1 evidence/status.
- Storage/Git: payloads are ignored; no unintended large source payload is a tracked candidate.

## J. R1 final checklist

| Exit item | Result |
|---|---|
| Existing assets audited; working R0 preserved | PASS |
| R1 folder structure and immutable raw/external boundary | PASS |
| Master catalogue and standardized categories/statuses | PASS |
| OFF products, seven taxonomies, and bounded image strategy | PASS |
| USDA FoodData Central releases documented; Foundation acquired | PASS |
| FoodOn acquired; FoodKG access represented accurately | PASS |
| GroceryStoreDataset and actual SKU-110K data route documented | PASS |
| TextOCR, SynthText, and COCO-Text current access documented | PASS |
| Recipe datasets and Indian recipe schema documented | PASS |
| WHO, ICMR-NIN, FSSAI, EFSA, and FDA references documented | PASS |
| Population/research sources documented without private ingest | PASS |
| Indian product-image and multilingual-label plans | PASS |
| All 15 required custom schema templates | PASS |
| Evidence corpus manifest and schema | PASS |
| One-to-one dataset license register | PASS |
| Complete 15-module dataset matrix | PASS |
| Dataset gap report | PASS |
| Large-download, missing-source, privacy, and raw immutability policies | PASS |
| Safe cross-platform download/manual-acquisition instructions | PASS |
| Provenance manifest and checksums | PASS |
| Catalogue/license/matrix/manifest/checksum validators | PASS |
| R1 automated tests and all R0 suites | PASS |
| No unintended large data in Git; no paid service | PASS |
| No R2 processing and no fabricated source/license/data | PASS |

## K. Final determination

Every applicable R1 exit criterion passes. Restricted, registration-gated, unavailable, and
license-unclear sources are correctly documented states and have safe future actions; none is
misrepresented as locally usable data.

**R1 — DATASET COLLECTION: 100% COMPLETE**
