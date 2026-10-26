"""Build a deterministic compact R4 runtime bundle from governed R2 taxonomies."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

FILES = {
    "ingredients": "off_ingredient.jsonl",
    "additives": "off_additive.jsonl",
    "allergens": "off_allergen.jsonl",
    "nova": "off_nova_group.jsonl",
}


def _english(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    return [
        str(value["text"])
        for value in values
        if isinstance(value, dict) and value.get("language") == "en" and value.get("text")
    ]


def _compact(record: dict[str, Any]) -> dict[str, Any]:
    lineage = record.get("lineage") or {}
    return {
        "taxonomy_id": record["taxonomy_id"],
        "canonical_name": record["canonical_name"],
        "external_code": record.get("external_code"),
        "functional_category": record.get("functional_category"),
        "english_names": _english(record.get("localized_names")),
        "english_synonyms": _english(record.get("synonyms")),
        "parent_ids": record.get("parent_ids") or [],
        "source_dataset": lineage.get("source_dataset", ""),
        "source_version": lineage.get("source_version", ""),
    }


def build(source: Path, destination: Path) -> None:
    sections: dict[str, list[dict[str, Any]]] = {}
    checksums: dict[str, str] = {}
    for section, filename in FILES.items():
        path = source / filename
        checksums[filename] = hashlib.sha256(path.read_bytes()).hexdigest()
        records: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                record = json.loads(line)
                if record.get("record_status") == "VALID":
                    records.append(_compact(record))
        sections[section] = records
    payload = {
        "bundle_version": "r4-runtime-v0.1.0",
        "pipeline": "scripts/build_r4_runtime_bundle.py",
        "source_checksums": checksums,
        "sections": sections,
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        destination.open("wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed,
    ):
        compressed.write(encoded)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source", type=Path, default=Path("data/processed/r2-v0.1.0/full/ingredients")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/runtime/r4-taxonomies-v0.1.0.json.gz")
    )
    args = parser.parse_args()
    build(args.source, args.output)


if __name__ == "__main__":
    main()
