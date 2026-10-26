from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.data_engineering.generate_schemas import MODELS, generate
from scripts.data_engineering.io_utils import output_metadata, sha256_file, write_csv, write_jsonl
from scripts.data_engineering.run_fixture_pipeline import run
from scripts.data_engineering.schemas import ProductRecord


def test_all_canonical_json_schemas_generate(tmp_path: Path) -> None:
    outputs = generate(tmp_path)
    assert len(outputs) == len(MODELS) == 15
    for output in outputs:
        schema = json.loads(output.read_text(encoding="utf-8"))
        assert schema["x-nutrilens-schema-version"] == "1.0.0"


def test_output_manifest_metadata_preserves_checksum(tmp_path: Path) -> None:
    output = tmp_path / "records.jsonl"
    write_jsonl(output, [{"record": "fixture"}])
    metadata = output_metadata(output, 1, role="PROCESSED")
    manifest = tmp_path / "manifest.csv"
    write_csv(manifest, list(metadata), [metadata])
    with manifest.open(encoding="utf-8", newline="") as source:
        row = next(csv.DictReader(source))
    assert row["sha256"] == sha256_file(output)
    assert row["record_count"] == "1"


def test_ci_fixture_pipeline_is_explicitly_non_nutrition(tmp_path: Path) -> None:
    output = tmp_path / "fixture-result.json"
    result = run(output)
    assert result["synthetic_non_nutrition_fixture"] is True
    assert result["models_trained"] == 0
    assert result["leakage_groups"] == []


def test_product_schema_rejects_unknown_fields() -> None:
    schema = ProductRecord.model_json_schema()
    assert schema["additionalProperties"] is False
