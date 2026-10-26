"""Generate a deterministic leakage-safe split CSV from record/group IDs."""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data_engineering.io_utils import write_csv
from scripts.data_engineering.splits import generate_splits, validate_no_group_leakage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--id-column", default="record_id")
    parser.add_argument("--group-column", default="group_id")
    parser.add_argument("--seed", type=int, default=20260808)
    args = parser.parse_args()
    with args.input.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    records = generate_splits(
        ((row[args.id_column], row[args.group_column]) for row in rows), seed=args.seed
    )
    leakage = validate_no_group_leakage(records)
    if leakage:
        raise RuntimeError(f"group leakage detected: {leakage[:10]}")
    write_csv(
        args.output,
        ["record_id", "group_id", "split", "seed"],
        (record.__dict__ for record in records),
    )
    print(f"Wrote {len(records)} deterministic split rows to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
