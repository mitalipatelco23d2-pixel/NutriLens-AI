"""Verify an R2 output manifest and summarize record/byte totals by role."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data_engineering.io_utils import sha256_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    with args.manifest.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    roles: Counter[str] = Counter()
    records: Counter[str] = Counter()
    for row in rows:
        path = args.repo_root / row["path"]
        if not path.is_file() or sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"output verification failed: {row['path']}")
        roles[row["role"]] += int(row["size_bytes"])
        records[row["role"]] += int(row["record_count"])
    print(json.dumps({"bytes_by_role": roles, "records_by_role": records}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
