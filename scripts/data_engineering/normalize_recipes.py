"""Normalize a permitted recipe JSONL source without generation or recommendation logic."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data_engineering.io_utils import sha256_file, write_jsonl
from scripts.data_engineering.recipes import normalize_recipe
from scripts.data_engineering.schemas import Lineage, RecipeRecord


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-dataset", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--license-status", required=True)
    args = parser.parse_args()
    checksum = sha256_file(args.input)

    def normalized_records() -> Iterator[RecipeRecord]:
        with args.input.open(encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                row = json.loads(line)
                lineage = Lineage(
                    source_dataset=args.source_dataset,
                    source_record_id=str(row.get("recipe_id", "")),
                    source_version=args.source_version,
                    source_url=args.source_url,
                    input_checksum=checksum,
                    processing_timestamp=datetime.now(UTC),
                    license_status=args.license_status,
                )
                yield normalize_recipe(row, lineage)

    count = write_jsonl(args.output, normalized_records())
    print(f"Wrote {count} canonical recipes to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
