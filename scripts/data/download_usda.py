"""Acquire the small USDA Foundation Foods release selected for R1."""

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data.download_dataset import acquire

if __name__ == "__main__":
    acquire("USDA-FOUNDATION")
