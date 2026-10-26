"""Streaming canonical product adapter for future permitted JSONL/CSV/TSV exports."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data_engineering.io_utils import sha256_file, write_jsonl
from scripts.data_engineering.products import normalize_product
from scripts.data_engineering.schemas import Lineage, ProductRecord


def _rows(path: Path, input_format: str) -> Iterator[dict[str, Any]]:
    if input_format == "jsonl":
        with path.open(encoding="utf-8") as source:
            for line in source:
                if line.strip():
                    yield json.loads(line)
        return
    delimiter = "\t" if input_format == "tsv" else ","
    with path.open(encoding="utf-8", newline="") as source:
        yield from csv.DictReader(source, delimiter=delimiter)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--format", choices=("jsonl", "csv", "tsv"), required=True)
    parser.add_argument("--source-dataset", required=True)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--license-status", required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    checksum = sha256_file(args.input)

    def normalized_records() -> Iterator[ProductRecord]:
        for index, row in enumerate(_rows(args.input, args.format), start=1):
            if args.limit is not None and index > args.limit:
                break
            source_id = str(row.get("source_product_id", index))
            lineage = Lineage(
                source_dataset=args.source_dataset,
                source_record_id=source_id,
                source_version=args.source_version,
                source_url=args.source_url,
                input_checksum=checksum,
                processing_timestamp=datetime.now(UTC),
                license_status=args.license_status,
            )
            yield normalize_product(row, lineage)

    count = write_jsonl(args.output, normalized_records())
    print(f"Wrote {count} canonical products to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
