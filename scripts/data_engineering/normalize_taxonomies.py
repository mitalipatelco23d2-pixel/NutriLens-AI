"""Normalize one locally acquired OFF taxonomy into canonical JSONL."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data_engineering.io_utils import write_jsonl
from scripts.data_engineering.off_taxonomy import parse_taxonomy
from scripts.data_engineering.quarantine import Quarantine
from scripts.data_engineering.source_registry import load_sources, require_source


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--taxonomy-type", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quarantine", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    source = require_source(load_sources(args.repo_root), args.dataset_id)
    quarantine = Quarantine(args.dataset_id)
    count = write_jsonl(
        args.output,
        parse_taxonomy(
            source,
            args.taxonomy_type,
            limit=args.limit,
            quarantine=quarantine,
        ),
    )
    rejected = quarantine.write(args.quarantine)
    print(f"Wrote {count} taxonomy records; quarantined {rejected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
