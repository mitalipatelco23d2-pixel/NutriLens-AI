# R2 data quality report

Full-run result: **PASS with documented source warnings**. All generated canonical JSONL records,
manifests, output checksums, lineage, privacy/licence gates, raw immutability, and deterministic
split leakage checks passed. Invalid inputs were quarantined rather than deleted.

## Checks run

- Pydantic and generated JSON Schema contract coverage for 15 canonical record types
- required ID/type/range/enum validation with unknown fields forbidden
- original/normalized nutrient values and units; negative/impossible values rejected
- explicit missingness and reported/converted/derived distinction
- GTIN string/check-digit logic and conservative product/ingredient normalization
- UTF-8/Unicode round-trip, language-code normalization, and source text preservation
- deterministic OFF ID/duplicate detection and FoodOn URI/hierarchy parsing
- image existence, zero-byte, header/format, dimensions and SHA duplicate utilities
- raw input and output SHA-256 verification; relative paths and record/byte counts
- complete lineage back to R1 dataset ID, source record, version, URL and input checksum
- privacy and licence gating; no person-level records and only R1 `DOWNLOADED` inputs
- seeded group splits and zero cross-split group leakage
- prohibited trained-model, embedding and index artifact scan

## Transparent engineering quality scores

Weights are 25 schema compliance, 20 provenance, 15 licensing, 20 completeness, 10 uniqueness,
and 10 unit validity. Scores are not scientific truth, clinical safety, representativeness, or
model-readiness guarantees beyond the documented R2 contract.

| Dataset | Score / 100 | Reason for deduction |
|---|---:|---|
| USDA Foundation | 96.0 | Source nutrient-field incompleteness |
| FAO/INFOODS Density | 96.0 | Source includes non-measurement/partial rows |
| OFF categories | 99.9 | 23 deterministic duplicate normalized IDs quarantined |
| OFF ingredients | 99.9 | 13 deterministic duplicate normalized IDs quarantined |
| OFF labels | 99.9 | 6 deterministic duplicate normalized IDs quarantined |
| Other four OFF taxonomies, FoodOn, WHO metadata | 100.0 | No pipeline-contract deduction |

## Failures, quarantine and outliers

There were no pipeline-stopping schema, integrity, privacy, licence, or leakage failures. The 85
quarantine rows comprise 42 deterministic OFF duplicate IDs and 43 invalid/unjoinable USDA
nutrient rows. Each contains the dataset, source record ID, stage, validation rule, reason, source
snapshot, and quarantine timestamp. No source record was silently dropped.

Two USDA nutrition records exceed conservative review thresholds. They remain in the dataset with
`SUSPECT_OUTLIER`-style flags; R2 does not automatically erase unusual but potentially legitimate
measurements. FoodOn has 404 of 39,682 classes without a direct label; URI nodes and edges are
retained because absence of a label is not proof the ontology class is invalid.

## Normalization decisions

- Mass uses mcg/mg/g/kg; volume uses mL/L; energy uses 1 kcal = 4.184 kJ.
- Sodium-derived salt is `sodium_mg × 2.5 / 1000` grams and is labelled `DERIVED`; it never
  overwrites a reported salt value.
- USDA records stay per 100 g as reported. Portions are separate and no serving-to-100 g value is
  inferred without known mass.
- Product/brand matching uses a separate Unicode-normalized, whitespace-collapsed case-fold key;
  original display text is preserved.
- Ingredient normalization changes only deterministic Unicode, spacing, separators, brackets,
  percentages, E-number and INS formatting. It does not perform final R4 entity extraction.
- OFF additive E-codes and source-declared functional classes are retained without attaching
  unsupported health-risk claims.
- OFF multilingual source text is preserved without machine translation. FoodOn OWL URIs remain
  stable, and no automatic USDA/OFF identity merge is performed.
- FAO rows without a direct g/mL value remain explicit partial references or category headers;
  no density is inferred.
- WHO text extraction is intentionally blocked pending copyright/reuse and later RAG-scope review;
  citation-ready metadata is complete.

## Remaining gaps and downstream risks

- Indian packaged-product and label-layout coverage remains absent; the full OFF product export is
  not local. Product schema/adapter readiness must not be mistaken for R3 scanner evidence.
- Scheduled-language support is structurally validated, but source coverage is uneven and absent
  for 5 of 22 scheduled languages. Even present counts are not expert-validated translations.
- USDA is US-centric; nutrient completeness varies, only 95/395 foods report both energy units,
  and household portions are not Indian serving standards.
- FAO density varies with preparation state and temperature; source context is incomplete.
- No rights-cleared images means image/OCR/meal quality, annotation agreement, visual duplicate,
  blur/lighting, and split behavior are unmeasured on real project images.
- Recipe, Indian population, custom synonym, and regulatory/additive evidence inputs remain access,
  licence, privacy, or collection gated.
- OFF taxonomy duplicate detection is deterministic ID equality, not a semantic merge. Ambiguous
  variants are preserved for later reviewed intelligence work.
