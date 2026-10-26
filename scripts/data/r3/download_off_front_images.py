"""Download and extract the complete official OFF front-image classification dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.data.r3.common import REPO_ROOT
from scripts.data.r3.off_embedded import acquire_off_embedded_dataset

REPO_ID = "openfoodfacts/front_image_classification"
REVISION = "872e9daf55358396d1e50952bbec7e3c0b0ef8d9"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination",
        type=Path,
        default=REPO_ROOT / "data/external/r3/openfoodfacts/front-image-classification",
    )
    args = parser.parse_args()
    summary = acquire_off_embedded_dataset(
        dataset_id="OFF-R3-FRONT-IMAGE-CLASSIFICATION",
        repo_id=REPO_ID,
        revision=REVISION,
        destination=args.destination,
        kind="front",
        license_name="AGPL-3.0 dataset card; OFF images CC-BY-SA-3.0",
        dataset_version="HF commit pinned",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
