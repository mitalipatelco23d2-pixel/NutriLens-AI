"""Validate a JSONL file against one canonical R2 Pydantic schema."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data_engineering.generate_schemas import MODELS
from scripts.data_engineering.io_utils import read_jsonl


def validate_file(path: Path, model_name: str) -> int:
    model = MODELS[model_name]
    count = 0
    for row in read_jsonl(path):
        model.model_validate(row)
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--schema", choices=sorted(MODELS), required=True)
    args = parser.parse_args()
    count = validate_file(args.input, args.schema)
    print(f"Validated {count} records from {args.input} as {args.schema}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
