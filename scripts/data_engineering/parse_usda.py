"""Parse local USDA Foundation Foods into canonical nutrition and serving records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data_engineering.source_registry import load_sources, require_source
from scripts.data_engineering.usda import process_usda


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interim-output", type=Path, required=True)
    parser.add_argument("--processed-output", type=Path, required=True)
    parser.add_argument("--quarantine", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    source = require_source(load_sources(args.repo_root), "USDA-FOUNDATION")
    result = process_usda(
        source,
        args.interim_output,
        args.processed_output,
        args.quarantine,
        limit=args.limit,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
