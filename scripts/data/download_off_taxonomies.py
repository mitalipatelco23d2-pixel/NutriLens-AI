"""Acquire all small official Open Food Facts taxonomies used in R1."""

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data.download_dataset import acquire

DATASET_IDS = (
    "OFF-TAX-INGREDIENTS",
    "OFF-TAX-ADDITIVES",
    "OFF-TAX-ALLERGENS",
    "OFF-TAX-CATEGORIES",
    "OFF-TAX-LABELS",
    "OFF-TAX-NOVA",
    "OFF-TAX-COUNTRIES",
)


if __name__ == "__main__":
    for dataset_id in DATASET_IDS:
        acquire(dataset_id)
