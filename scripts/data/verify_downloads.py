"""Verify every R1 acquisition manifest entry against the local file and SHA-256."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data.safe_download import resolve_destination, sha256_file

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "data/manifests/downloaded-artifacts.csv"


def verify() -> list[str]:
    errors: list[str] = []
    if not MANIFEST.exists():
        return ["Acquisition manifest does not exist"]
    with MANIFEST.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source))
    if not rows:
        return ["Acquisition manifest has no records"]
    for row in rows:
        dataset_id = row.get("Dataset ID", "<missing ID>")
        try:
            path = resolve_destination(REPO_ROOT, row.get("Local path", ""))
        except ValueError as exc:
            errors.append(f"{dataset_id}: {exc}")
            continue
        if not path.is_file():
            errors.append(f"{dataset_id}: missing local file {path}")
            continue
        if str(path.stat().st_size) != row.get("Size bytes"):
            errors.append(f"{dataset_id}: byte size differs from manifest")
        if sha256_file(path) != row.get("SHA-256"):
            errors.append(f"{dataset_id}: SHA-256 differs from manifest")
    return errors


def main() -> int:
    errors = verify()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("All downloaded R1 artifacts match their size and SHA-256 manifest records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
