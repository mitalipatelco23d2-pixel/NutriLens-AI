"""Run a tiny synthetic non-nutrition software fixture through core R2 utilities for CI."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data_engineering.io_utils import write_json
from scripts.data_engineering.normalization import normalize_display_text
from scripts.data_engineering.quality import transparent_quality_score
from scripts.data_engineering.schemas import Lineage, ProductRecord
from scripts.data_engineering.splits import generate_splits, validate_no_group_leakage


def run(output: Path) -> dict[str, object]:
    lineage = Lineage(
        source_dataset="SYNTHETIC_SOFTWARE_TEST_FIXTURE",
        source_record_id="fixture-001",
        source_version="1",
        source_url="https://example.invalid/not-a-real-dataset",
        input_checksum="0" * 64,
        processing_timestamp=datetime.now(UTC),
        license_status="TEST_FIXTURE_ONLY",
    )
    product = ProductRecord(
        product_id="fixture:001",
        source_product_id="fixture-001",
        product_name_original="  Software   Fixture  ",
        product_name=normalize_display_text("  Software   Fixture  "),
        product_name_match_key="software fixture",
        nutrition_available=False,
        ingredient_data_available=False,
        image_available=False,
        data_quality_score=transparent_quality_score(
            schema_compliance=1,
            provenance=1,
            licensing=1,
            completeness=0,
            uniqueness=1,
            unit_validity=1,
        ),
        record_status="SYNTHETIC_TEST_FIXTURE_NOT_DATA",
        lineage=lineage,
    )
    splits = generate_splits([("fixture-001", "fixture-family")])
    leakage = validate_no_group_leakage(splits)
    result: dict[str, object] = {
        "synthetic_non_nutrition_fixture": True,
        "schema_valid_records": 1,
        "normalized_name": product.product_name,
        "split": splits[0].split,
        "leakage_groups": leakage,
        "models_trained": 0,
    }
    write_json(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output)
    print(f"R2 CI fixture pipeline passed: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
