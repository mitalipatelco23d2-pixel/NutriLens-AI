"""Validate R1 dataset governance and, by default, local downloaded artifacts."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.r1_validation import validate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--governance-only",
        action="store_true",
        help="Validate tracked governance without requiring Git-ignored dataset payloads",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    errors = validate(root, require_downloads=not args.governance_only)
    if errors:
        print(f"R1 validation failed with {len(errors)} issue(s):")
        for error in errors:
            print(f"- {error}")
        return 1

    import csv

    with (root / "documentation/datasets/dataset-catalogue.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        statuses = Counter(row["Acquisition status"] for row in csv.DictReader(source))
    scope = "governance" if args.governance_only else "governance and local acquisitions"
    print(f"R1 {scope} validated successfully: {dict(sorted(statuses.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
