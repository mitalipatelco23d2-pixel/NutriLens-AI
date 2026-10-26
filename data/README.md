# Data workspace

This directory contains the immutable R1 collection boundary and the reproducible R2 engineered
layers. Source and transformed payloads are ignored by Git; governance, schemas, provenance,
versions, checksums, quality reports and split manifests are versioned.

- `raw/`: immutable source files or original project-collected material. Never edit in place.
- `external/`: immutable third-party archives, ontologies, taxonomies, and references.
- `manifests/`: machine-readable acquisition provenance.
- `licenses/`: local license notices or review records when redistribution permits them.
- `checksums/`: integrity records for acquired files.
- `interim/`: source-faithful versioned R2 transformations.
- `processed/`: schema-valid versioned AI-ready R2 datasets.
- `annotations/`: annotation contracts and availability status.
- `splits/`: deterministic leakage-safe split manifests.
- `schemas/`: Pydantic-generated JSON Schemas.
- `quality/`: quality summaries and invalid-record quarantine.

Run `python scripts/validate_r1.py` for the acquisition boundary and `python scripts/validate_r2.py`
for transformed payload integrity, schemas, lineage, manifests, checksums and splits.
