"""Download and extract the complete official OFF nutrition-table detection dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.data.r3.common import REPO_ROOT
from scripts.data.r3.off_embedded import acquire_off_embedded_dataset

REPO_ID = "openfoodfacts/nutrition-table-detection"
REVISION = "d59dcee85ecb44831831a85f7b345501db2b4071"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination",
        type=Path,
        default=REPO_ROOT / "data/external/r3/openfoodfacts/nutrition-table-detection",
    )
    args = parser.parse_args()
    summary = acquire_off_embedded_dataset(
        dataset_id="OFF-R3-NUTRITION-TABLE-DETECTION",
        repo_id=REPO_ID,
        revision=REVISION,
        destination=args.destination,
        kind="nutrition",
        license_name="CC-BY-SA-3.0",
        dataset_version="1.1",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
