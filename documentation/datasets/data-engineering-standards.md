# R2 data-engineering standards

## Storage and reproducibility

- `data/raw` and `data/external` are immutable originals. Pipelines open them read-only and compare
  their SHA-256 values to the R1 acquisition manifest before processing and after completion.
- `data/interim` contains reproducible, source-faithful representations. `data/processed` contains
  schema-valid canonical data. `data/quality/quarantine` preserves rejected records and reasons.
- Every output is regenerated from code and a recorded input manifest. Payloads are Git-ignored;
  schemas, output manifests, checksums, versions, reports, and split manifests are tracked.
- Every canonical source-backed record carries dataset ID, original record ID, source version/URL,
  input checksum, pipeline/schema version, processing time, and licence review status.

## Fidelity rules

- A transformation must not silently discard a record. Invalid or duplicate inputs are preserved
  in quarantine with the rule, stage, failure reason, and source snapshot.
- Missing is never zero. `UNKNOWN`, `NOT_REPORTED`, `NOT_APPLICABLE`, and `INVALID` are explicit.
- Reported, converted, derived, and estimated values are distinct. Original value/unit are kept;
  derived values never overwrite reported values. R2 does not manufacture estimates.
- Units and measurement bases are explicit. Serving-to-100 g conversion is prohibited unless a
  real serving mass/volume is supplied.
- Unicode and whitespace normalization preserve the original product, brand, ingredient, recipe,
  and transcription text. Ingredient order is unchanged. Matching keys are separate fields.
- Deterministic E-number/INS, bracket, separator, and percentage formatting is preprocessing only;
  final ingredient entity extraction is R4 work.
- No medical inference, risk claim, translation, product equivalence, scientific conclusion, or
  missing numeric value is created during R2.

## Validation and governance

- Canonical models use Pydantic with unknown fields forbidden; versioned JSON Schemas are generated
  from the same models.
- Numeric ranges, units, identifiers, barcodes, image readability, ontology URIs, language/Unicode,
  uniqueness, lineage, checksums, split leakage, licensing, and privacy are validated as relevant.
- Duplicate classes are `EXACT_DUPLICATE`, `LIKELY_DUPLICATE`, `SOURCE_VARIANT`, and
  `NOT_DUPLICATE`. Only deterministic source duplicates are quarantined; ambiguous records remain.
- Outliers are review flags, not automatic deletions. Supported classes are `VALIDATED_OUTLIER`,
  `SUSPECT_OUTLIER`, and `INVALID`.
- The transparent score is: 25% schema compliance + 20% provenance + 15% licensing + 20%
  completeness + 10% uniqueness + 10% unit validity. It measures the engineered record contract,
  not scientific truth, clinical safety, representativeness, or fitness for every model.
- Only R1 sources with local `DOWNLOADED` evidence and verified checksums enter the pipeline.
  Registration, manual-download, licence-review, unavailable, and deferred gates remain enforced.
- Person-level health/account data and unreviewed PII are prohibited. Custom images require rights
  or consent metadata. Suspected PII must be quarantined and reviewed rather than copied onward.

## Versioning

Every release records `dataset_name`, `dataset_version`, `source_version`, `pipeline_version`,
`created_at`, `input_manifest`, `output_manifest`, and `schema_version`. R2 begins at dataset and
pipeline `0.1.0`, schema `1.0.0`; split seed `20260808` is stable.
