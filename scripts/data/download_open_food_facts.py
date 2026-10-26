"""Storage-gated Open Food Facts export helper.

The full exports are intentionally not in the automated registry. This command prints the exact
official source and requires an explicit full-mode flag before delegating to safe_download.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data.safe_download import download

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORTS = {
    "csv": (
        "https://static.openfoodfacts.org/data/en.openfoodfacts.org.products.csv.gz",
        "data/external/open_food_facts/products_csv/en.openfoodfacts.org.products.csv.gz",
        2_000_000_000,
    ),
    "jsonl": (
        "https://static.openfoodfacts.org/data/openfoodfacts-products.jsonl.gz",
        "data/external/open_food_facts/products_jsonl/openfoodfacts-products.jsonl.gz",
        15_000_000_000,
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=EXPORTS, default="csv")
    parser.add_argument("--mode", choices=("instructions", "full"), default="instructions")
    parser.add_argument("--allow-large", action="store_true")
    parser.add_argument("--sha256", help="Trusted SHA-256 published out of band")
    args = parser.parse_args()
    url, relative, limit = EXPORTS[args.format]
    if args.mode != "full" or not args.allow_large:
        print(f"Official URL: {url}")
        print(f"Destination: {relative}")
        print("Full export is LARGE/VERY_LARGE. Re-run with --mode full --allow-large.")
        return 0
    if not args.sha256:
        raise SystemExit("--sha256 is required for a full acquisition")
    result = download(
        url, REPO_ROOT / relative, max_bytes=limit, expected_sha256=args.sha256.lower()
    )
    print(f"Acquired {result.path} ({result.size_bytes:,} bytes; SHA-256 {result.sha256})")
    print("Add this artifact to the provenance manifest before marking it DOWNLOADED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
