"""Inspect local images for corruption, dimensions, format, zero bytes, and duplicate hashes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data_engineering.images import duplicate_checksums, inspect_image
from scripts.data_engineering.io_utils import write_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = sorted(path for path in args.input_dir.rglob("*") if path.is_file())
    inspections = [inspect_image(path) for path in paths]
    count = write_jsonl(
        args.output,
        (
            {
                "path": inspection.path.as_posix(),
                "valid": inspection.valid,
                "format": inspection.format,
                "width": inspection.width,
                "height": inspection.height,
                "checksum": inspection.checksum,
                "failure_reason": inspection.failure_reason,
            }
            for inspection in inspections
        ),
    )
    duplicates = duplicate_checksums(inspections)
    print(f"Inspected {count} images; duplicate checksum groups: {len(duplicates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
