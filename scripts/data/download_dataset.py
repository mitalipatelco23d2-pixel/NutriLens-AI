"""CLI for R1 automated acquisitions declared in acquisition_registry.json."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import NotRequired, TypedDict, cast

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.data.safe_download import download, resolve_destination

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = Path(__file__).with_name("acquisition_registry.json")
MANIFEST_PATH = REPO_ROOT / "data/manifests/downloaded-artifacts.csv"
CHECKSUM_PATH = REPO_ROOT / "data/checksums/SHA256SUMS"
MANIFEST_FIELDS = [
    "Dataset ID",
    "Filename",
    "Source URL",
    "Download date UTC",
    "Version",
    "Size bytes",
    "SHA-256",
    "Local path",
    "Privacy status",
]


class RegistryEntry(TypedDict):
    url: str
    destination: str
    version: str
    storage_class: str
    max_bytes: int
    expected_magic_hex: NotRequired[str]
    expected_sha256: str


def load_registry() -> dict[str, RegistryEntry]:
    return cast(dict[str, RegistryEntry], json.loads(REGISTRY_PATH.read_text(encoding="utf-8")))


def _read_manifest() -> list[dict[str, str]]:
    if not MANIFEST_PATH.exists():
        return []
    with MANIFEST_PATH.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def _write_manifest(row: dict[str, str]) -> None:
    rows = [
        existing
        for existing in _read_manifest()
        if existing["Dataset ID"] != row["Dataset ID"]
        or existing["Local path"] != row["Local path"]
    ]
    rows.append(row)
    rows.sort(key=lambda item: (item["Dataset ID"], item["Local path"]))
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=MANIFEST_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    CHECKSUM_PATH.parent.mkdir(parents=True, exist_ok=True)
    checksum_lines = [f"{item['SHA-256']}  {item['Local path']}" for item in rows]
    CHECKSUM_PATH.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")


def acquire(dataset_id: str, *, force: bool = False) -> None:
    registry = load_registry()
    if dataset_id not in registry:
        raise KeyError(f"Unknown dataset ID: {dataset_id}")
    entry = registry[dataset_id]
    destination = resolve_destination(REPO_ROOT, entry["destination"])
    result = download(
        entry["url"],
        destination,
        max_bytes=entry["max_bytes"],
        force=force,
        expected_magic=bytes.fromhex(entry.get("expected_magic_hex", "")) or None,
        expected_sha256=entry["expected_sha256"],
    )
    relative = result.path.relative_to(REPO_ROOT).as_posix()
    _write_manifest(
        {
            "Dataset ID": dataset_id,
            "Filename": result.path.name,
            "Source URL": entry["url"],
            "Download date UTC": datetime.now(UTC).isoformat(timespec="seconds"),
            "Version": entry["version"],
            "Size bytes": str(result.size_bytes),
            "SHA-256": result.sha256,
            "Local path": relative,
            "Privacy status": "SCREENED_NO_PII_EXPECTED",
        }
    )
    action = "Reused" if result.reused_existing else "Downloaded"
    print(f"{action} {dataset_id}: {relative} ({result.size_bytes:,} bytes)")
    print(f"SHA-256: {result.sha256}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", action="append", help="Dataset ID; repeat as needed")
    parser.add_argument("--all-small", action="store_true", help="Acquire all SMALL entries")
    parser.add_argument("--all-safe", action="store_true", help="Acquire all registry entries")
    parser.add_argument("--list", action="store_true", help="List available automated entries")
    parser.add_argument("--force", action="store_true", help="Replace an existing final file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    registry = load_registry()
    if args.list:
        for dataset_id, entry in sorted(registry.items()):
            print(f"{dataset_id:24} {entry['storage_class']:6} {entry['destination']}")
        return 0

    selected = list(args.dataset or [])
    if args.all_small:
        selected.extend(
            dataset_id
            for dataset_id, entry in registry.items()
            if entry["storage_class"] == "SMALL"
        )
    if args.all_safe:
        selected.extend(registry)
    selected = list(dict.fromkeys(selected))
    if not selected:
        raise SystemExit("Select --dataset ID, --all-small, --all-safe, or --list")
    for dataset_id in selected:
        acquire(dataset_id, force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
