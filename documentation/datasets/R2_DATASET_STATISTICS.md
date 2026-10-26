# R2 dataset statistics

Computed from the full local run on 2026-08-08. “Stage output” is the primary canonical entity
used in the transformation summary; associated interim long tables, ontology edges and servings
are shown separately. No number represents an unavailable or fabricated source.

## Processing totals

| Dataset | Input | Stage output | Rejected | Duplicates | Output bytes |
|---|---:|---:|---:|---:|---:|
| OFF additives | 668 | 668 | 0 | 0 | 4,348,143 |
| OFF allergens | 27 | 27 | 0 | 0 | 381,263 |
| OFF categories | 14,598 | 14,575 | 23 | 23 | 18,554,191 |
| OFF countries | 268 | 268 | 0 | 0 | 4,098,639 |
| OFF ingredients | 5,629 | 5,616 | 13 | 13 | 10,600,258 |
| OFF labels | 3,029 | 3,023 | 6 | 6 | 3,463,411 |
| OFF NOVA groups | 6 | 6 | 0 | 0 | 36,418 |
| USDA Foundation foods | 395 | 395 nutrition | 43 nutrient rows | 0 | 13,475,286 |
| FoodOn | 39,682 classes | 39,682 nodes | 0 | 0 | 63,145,661 |
| FAO/INFOODS Density | 665 | 665 | 0 | 0 | 518,662 |
| WHO Healthy Diet | 1 document | 1 metadata record | 0 | 0 | 1,380 |
| **Primary stage total** | — | **64,926** | **85** | **42** | — |

USDA output bytes include 395 source-reference foods (297,200 bytes), 16,965 long nutrient rows
(11,358,391), 395 canonical nutrition rows (1,737,205), and 123 serving rows (82,490). FoodOn
bytes include 39,682 nodes (27,050,434) and 46,027 edges (36,095,227).

Across the output manifest there are 26 payload files: 103,069 interim records / 74,801,252
bytes; 25,367 processed records / 43,822,060 bytes; 85 quarantine records / 35,713 bytes; and a
395-row split manifest / 14,288 bytes.

## Nutrition coverage

Coverage among 395 USDA canonical nutrition records:

| Field | Present | Coverage | Missing |
|---|---:|---:|---:|
| Calcium | 367 | 92.9% | 28 |
| Iron | 367 | 92.9% | 28 |
| Potassium | 367 | 92.9% | 28 |
| Protein | 353 | 89.4% | 42 |
| Sodium | 349 | 88.4% | 46 |
| Derived salt | 349 | 88.4% | 46 |
| Total fat | 341 | 86.3% | 54 |
| Carbohydrates | 312 | 79.0% | 83 |
| Fibre | 198 | 50.1% | 197 |
| Sugars | 149 | 37.7% | 246 |
| Saturated fat | 124 | 31.4% | 271 |
| Energy kcal | 95 | 24.1% | 300 |
| Energy kJ | 95 | 24.1% | 300 |
| Cholesterol | 89 | 22.5% | 306 |

Every missing nutrient is an explicit `NOT_REPORTED` value object, never numeric zero. Two USDA
records carry review-only nutrition outlier flags. The 43 quarantined USDA nutrient rows had an
unknown nutrient ID and/or no valid amount and were retained with source snapshots.

The largest USDA source categories are Vegetables (89), Fruits (56), Cereal Grains (43), Dairy and
Eggs (43), Legumes (42), Finfish/Shellfish (24), Nuts/Seeds (19), and Beef (15). The remaining 64
records span 11 smaller USDA categories.

## Language, density, annotations and splits

OFF localized names/synonyms contain 306 distinct source language tags. Seventeen of the 22
scheduled Indian language codes have at least one source term: Assamese 77, Bengali 795, Gujarati
259, Hindi 758, Kannada 421, Kashmiri 24, Malayalam 588, Marathi 465, Nepali 337, Odia 334,
Punjabi 491, Sanskrit 279, Santali 1, Sindhi 119, Tamil 777, Telugu 407, and Urdu 535. Bodo,
Dogri, Konkani, Maithili, and Manipuri have zero source terms. These are source counts, not claims
of translation completeness or quality.

FAO contains 500 direct density measurements, 106 specific-gravity/partial-reference rows, and 59
category headers. The explicit non-measurement/missing-density rate is 24.812%.

Annotation counts are all zero: source images 0, detection annotations 0, OCR annotations 0, and
meal annotations 0. Status is `BLOCKED_BY_DATA_AVAILABILITY`.

USDA deterministic split counts are 281 TRAIN, 62 VALIDATION, and 52 TEST with seed `20260808`;
group leakage count is zero. Sample-mode counts are 137/37/26 for 200 foods.

## Licensing states

All processed inputs came from the 11 R1 `DOWNLOADED` rows and retained their R1 licence review
status. Gated Recipe1M, RecipeDB, WHO GHO, NFHS microdata, full OFF products, custom images/OCR,
and other unavailable/manual/licence-review inputs contributed zero records.
