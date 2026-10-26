# R1 dataset collection and governance

R1 identifies what NutriLens X needs, where it comes from, whether it may be used, how it can be
acquired, where it is stored, which frozen module consumes it, and what remains missing. R2 now
transforms only the permitted local R1 artifacts into versioned, validated, lineage-preserving
interim and processed datasets. R2 does not train, embed, index, or implement later AI systems.

## Canonical records

- `dataset-catalogue.csv`: 57 datasets, ontologies, evidence sources, and custom collection plans.
- `license-register.csv`: one rights record for every catalogue row.
- `module-dataset-matrix.csv`: required/optional data coverage for exactly 15 frozen modules.
- `evidence-corpus-manifest.csv`: authoritative sources for later citation, RAG, and explanation.
- `data/manifests/downloaded-artifacts.csv`: local acquisition provenance and SHA-256 values.
- `outputs/r1-dataset-governance/r1-dataset-governance.xlsx`: review-friendly workbook generated
  from the same register data.

The catalogue distinguishes `DATASET`, `ONTOLOGY`, `REGULATORY_REFERENCE`,
`SCIENTIFIC_REFERENCE`, and `KNOWLEDGE_SOURCE`. A guideline, regulation, or webpage is not
mislabelled as an ML dataset.

## Acquisition statuses

- `AVAILABLE`: official access exists, but no required local artifact has been acquired.
- `DOWNLOADED`: the listed local file exists and has a provenance/checksum record.
- `PARTIALLY_DOWNLOADED`: a deliberately bounded subset exists; no current R1 row uses this.
- `REGISTRATION_REQUIRED`: provider registration or approval is required.
- `MANUAL_DOWNLOAD_REQUIRED`: access or terms require a human-controlled step.
- `LICENSE_REVIEW_REQUIRED`: use is blocked until rights are clarified.
- `UNAVAILABLE`: no currently valid official acquisition route was verified.
- `DEFERRED`: a custom dataset is specified but collection belongs to a later release.
- `NOT_REVIEWED`: allowed by the schema but no R1 source remains in this state.

## Storage and immutability

`SMALL`, `MEDIUM`, `LARGE`, and `VERY_LARGE` describe acquisition impact; size notes in the
catalogue are authoritative because thresholds cannot replace provider-reported compressed and
expanded sizes. Automated R1 downloads are bounded by per-source byte caps. Large/full downloads
need an explicit flag or manual action. Dataset payloads are Git-ignored.

`data/raw/` and `data/external/` contain original bytes and must never be manually edited. R2
transformations write versioned artifacts to `data/interim/`, `data/processed/`, and
`data/quality/quarantine`, retaining source ID, release, licence and checksum lineage. Payloads are
ignored by Git while their schemas, manifests, versions, reports, checksums and splits are tracked.

## Licensing and privacy

Academic availability does not imply unrestricted redistribution or commercial use. The license
register records provider terms separately and uses `REQUIRES_LEGAL_REVIEW` whenever rights are
unclear. Restricted sources are not automatically acquired. Regulatory and scientific PDFs are
stored only as research references; their copyright is not transferred to this project.

R1 collects no user profiles, health records, or identifiable person-level data. Population
sources are aggregate. NFHS microdata is registration-gated and excluded from automatic ingest;
only approved aggregate reports may be considered without a dedicated privacy review.

## Reproducible workflow

```powershell
python scripts/data/download_dataset.py --list
python scripts/data/download_dataset.py --all-small
python scripts/data/download_dataset.py --dataset FOODON
python scripts/data/verify_downloads.py
python scripts/validate_r1.py
```

For a clean Git checkout without ignored payloads, CI runs
`python scripts/validate_r1.py --governance-only`. Missing, unavailable, registered, or disputed
sources stay visible in the catalogue and gap report; they are never replaced with fabricated
URLs, licenses, values, or translations.

## R2 engineering records

- [Starting-state audit](R2_AUDIT.md)
- [Architecture and flow](R2_ARCHITECTURE.md)
- [Data-engineering standards](data-engineering-standards.md)
- [Canonical schemas](canonical-schemas.md) and [data dictionary](data-dictionary.md)
- [Annotation guidelines](annotation-guidelines.md) and [split policy](split-policy.md)
- [Computed statistics](R2_DATASET_STATISTICS.md) and [quality report](R2_DATA_QUALITY_REPORT.md)
- [R2 status](R2_STATUS.md) and [completion report](R2_COMPLETION_REPORT.md)
