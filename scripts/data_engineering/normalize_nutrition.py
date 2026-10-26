"""Exercise deterministic nutrient unit conversion and optional sodium/salt derivation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data_engineering.normalization import (
    derive_salt_from_sodium,
    derive_sodium_from_salt,
    normalize_reported_value,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--value", type=float, required=True)
    parser.add_argument("--source-unit", required=True)
    parser.add_argument("--target-unit", required=True)
    parser.add_argument("--derive", choices=("salt-from-sodium", "sodium-from-salt"))
    args = parser.parse_args()
    value = normalize_reported_value(args.value, args.source_unit, args.target_unit)
    result = value
    if args.derive == "salt-from-sodium":
        result = derive_salt_from_sodium(value)
    elif args.derive == "sodium-from-salt":
        result = derive_sodium_from_salt(value)
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
