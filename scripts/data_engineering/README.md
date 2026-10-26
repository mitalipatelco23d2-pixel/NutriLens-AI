# R2 data-engineering pipeline

This package transforms only checksum-verified, locally downloaded R1 sources. It never downloads
data, modifies `data/raw` or `data/external`, trains a model, creates embeddings, or populates a
production graph/index.

## Run

From the repository root with the project Python environment active:

```powershell
python scripts/data_engineering/run_r2_pipeline.py --mode sample
python scripts/data_engineering/run_r2_pipeline.py --mode full
python scripts/validate_r2.py
```

Sample mode caps each source at 200 source records where applicable. Full mode processes all and
only the 11 locally acquired R1 artifacts; it does not acquire gated inputs. Both modes verify the
input SHA-256 values before processing, verify raw immutability afterwards, produce versioned
interim/processed/quarantine outputs, create an output manifest and SHA-256 list, and generate a
deterministic USDA split manifest with seed `20260808`.

## Commands

| Command | Purpose |
|---|---|
| `run_r2_pipeline.py` | Ordered sample/full orchestration and manifests |
| `normalize_taxonomies.py` | Stream an OFF taxonomy into canonical JSONL |
| `parse_usda.py` | Parse Foundation Foods, nutrients and portions |
| `parse_foodon.py` | Extract ontology nodes and subclass edges |
| `normalize_density.py` | Parse the FAO/INFOODS density workbook |
| `normalize_products.py` | Normalize a supplied product JSONL source conservatively |
| `normalize_nutrition.py` | Validate supplied canonical nutrition JSONL |
| `normalize_images.py` | Validate local image metadata and detect checksum duplicates |
| `normalize_recipes.py` | Normalize a supplied recipe JSONL source |
| `validate_dataset.py` | Validate JSONL against a named canonical Pydantic model |
| `generate_splits.py` | Generate stable group-based split CSV files |
| `generate_quality_report.py` | Verify a manifest and summarize bytes/records by role |
| `generate_schemas.py` | Generate the 15 versioned JSON Schemas |
| `run_fixture_pipeline.py` | Tiny explicitly synthetic, non-nutrition CI software fixture |

Every command supports `--help`. Invalid records are rejected to a quarantine JSONL with their
source snapshot and reason; no rejected source record is silently discarded. Product, image,
annotation, OCR, recipe, and population adapters/schemas are ready, but produce no asserted real
records while their corresponding R1 inputs remain unavailable or gated.

## Versions and storage

- Dataset version: `0.1.0`
- Pipeline version: `0.1.0`
- Schema version: `1.0.0`
- Payload root: `data/{interim,processed,quality/quarantine}/r2-v0.1.0/{sample,full}`
- Machine schemas: `data/schemas/r2-v1.0.0`
- Governance artifacts: `data/manifests`, `data/checksums`, `data/quality`, `data/splits`

Generated payloads are intentionally Git-ignored. Small governance manifests, schemas, reports,
and split manifests are tracked so a clean checkout can validate the contract without carrying
source or transformed data.
