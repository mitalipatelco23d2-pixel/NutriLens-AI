# R2 starting-state audit

Audit date: 2026-08-08. This audit was completed before transforming the R1 payloads. R1 had 57
catalogue rows, 57 licence rows, 59 module mappings, 15 header-only custom templates, and 11 local
artifacts totalling 54,054,088 bytes (51.55 MiB). `scripts/validate_r1.py` and
`scripts/data/verify_downloads.py` passed, and the 11 input SHA-256 values were snapshotted for the
R2 immutability check.

## Locally available and usable now

| Dataset | Bytes | Format | R2 use | Priority |
|---|---:|---|---|---:|
| FOODON | 40,429,965 | OWL/XML | Class, label, synonym and subclass-edge extraction | 1 |
| USDA-FOUNDATION | 3,825,517 | ZIP containing 24 CSV tables | Food, nutrient, nutrition and portion normalization | 1 |
| OFF-TAX-CATEGORIES | 3,625,338 | OFF taxonomy text | Canonical category taxonomy | 1 |
| OFF-TAX-INGREDIENTS | 2,645,385 | OFF taxonomy text | Canonical ingredient taxonomy | 1 |
| OFF-TAX-ADDITIVES | 1,114,125 | OFF taxonomy text | Canonical additive taxonomy and source codes | 1 |
| OFF-TAX-COUNTRIES | 1,092,770 | OFF taxonomy text | Canonical country taxonomy | 2 |
| OFF-TAX-LABELS | 1,028,080 | OFF taxonomy text | Canonical label taxonomy | 2 |
| FAO-DENSITY | 131,549 | XLSX | Density, partial-reference and category-row normalization | 1 |
| OFF-TAX-ALLERGENS | 75,083 | OFF taxonomy text | Canonical allergen taxonomy | 1 |
| WHO-HEALTHY-DIET | 74,727 | PDF | Evidence metadata and citation record only | 2 |
| OFF-TAX-NOVA | 11,549 | OFF taxonomy text | Canonical NOVA taxonomy | 2 |

All 11 are `DOWNLOADED`, privacy-screened as no PII expected, checksum verified, and have an R1
licence record. OFF transformations retain ODbL provenance; FoodOn retains CC BY attribution
metadata; USDA retains its source citation; WHO is treated as a reference, not freely reusable
training text.

## Gated or unavailable inputs

| Input family | R1 state | R2 decision |
|---|---|---|
| Full OFF products | Available, not downloaded under the large-download policy | Product adapter/schema only; no product rows fabricated |
| Indian packaged-food images | Deferred / no rights-cleared payload | Image and annotation contracts only |
| Indian multilingual OCR images | Deferred / no payload | OCR adapter/schema only |
| Recipe1M+ | `REGISTRATION_REQUIRED` | No access bypass and no output |
| RecipeDB and public CV corpora | `MANUAL_DOWNLOAD_REQUIRED` or terms-gated | Adapter/schema only where relevant |
| WHO GHO and several scientific/regulatory sources | `LICENSE_REVIEW_REQUIRED` | No transformation |
| NFHS-5 microdata | Registration and privacy restricted | Excluded; population schema accepts aggregates only |
| R1 custom tables | Header-only, `DEFERRED` | Raw templates remain immutable; canonical schemas are separate |

## Expected transformation path

`R1 catalogue/licence/manifest → immutable local source → interim source-faithful rows → canonical
processed JSONL → schema/semantic validation → quarantine + quality report → deterministic split
manifest → version/output/checksum manifests`.

The audit found no legitimate local product export, image corpus, OCR annotations, recipe payload,
or population-statistics payload. Their missing outputs are source-availability states, not filled
with synthetic nutrition, products, translations, scientific text, images, or annotations.
