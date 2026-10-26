"""Build compact exact-label links from the R4 ingredient vocabulary to FoodOn."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

PINNED_RUNTIME_SHA256 = "010d492ebb4291561630f252759f837010942bdafe6dcff31ec8b213a196442b"


def _normalized(value: str) -> str:
    return " ".join(value.casefold().split())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_links(foodon_path: Path, r4_path: Path) -> dict[str, Any]:
    foodon_terms: dict[str, list[dict[str, str]]] = defaultdict(list)
    source_version = "unknown"
    with foodon_path.open(encoding="utf-8") as handle:
        for line in handle:
            node = json.loads(line)
            uri = str(node["uri"])
            if "/FOODON_" not in uri or bool(node.get("deprecated")):
                continue
            source_version = str(node["lineage"]["source_version"])
            for localized in [*node.get("labels", []), *node.get("synonyms", [])]:
                language = str(localized.get("language", "und"))
                if language not in {"en", "und", ""}:
                    continue
                text = str(localized.get("text", "")).strip()
                term = _normalized(text)
                if term:
                    foodon_terms[term].append(
                        {"uri": uri, "label": text, "language": language or "und"}
                    )

    with gzip.open(r4_path, "rt", encoding="utf-8") as handle:
        r4_bundle = json.load(handle)
    mappings: list[dict[str, Any]] = []
    for ingredient in r4_bundle["sections"]["ingredients"]:
        terms = list(
            dict.fromkeys(
                str(value)
                for value in [
                    ingredient["canonical_name"],
                    *ingredient["english_names"],
                    *ingredient["english_synonyms"],
                ]
                if value
            )
        )
        matched_by_uri: dict[str, dict[str, str]] = {}
        for term in terms:
            for match in foodon_terms.get(_normalized(term), []):
                matched_by_uri.setdefault(
                    match["uri"],
                    {
                        **match,
                        "matched_term": term,
                        "match_method": "EXACT_NORMALIZED_LABEL",
                    },
                )
        if not matched_by_uri:
            continue
        mappings.append(
            {
                "taxonomy_id": ingredient["taxonomy_id"],
                "canonical_name": ingredient["canonical_name"],
                "foodon_matches": sorted(matched_by_uri.values(), key=lambda item: item["uri"])[:5],
            }
        )
    mappings.sort(key=lambda item: item["taxonomy_id"])
    return {
        "schema_version": "0.1.0",
        "method": "EXACT_NORMALIZED_ENGLISH_OR_UNTAGGED_LABEL_LINK_V1",
        "source_dataset": "FOODON",
        "source_version": source_version,
        "source_checksums": {
            foodon_path.as_posix(): _sha256(foodon_path),
            r4_path.as_posix(): _sha256(r4_path),
        },
        "limitations": [
            "Exact lexical identity does not prove full semantic equivalence.",
            "At most five FoodOn classes are retained for an ambiguous ingredient term.",
            "Unmatched runtime ingredients remain explicitly unlinked.",
        ],
        "mappings": mappings,
    }


def verify_runtime_artifact(path: Path, r4_path: Path) -> dict[str, Any]:
    """Verify the reviewed release artifact without claiming a raw-source rebuild."""
    if _sha256(path) != PINNED_RUNTIME_SHA256:
        raise ValueError("FoodOn release artifact checksum mismatch; review and rebuild required.")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        bundle: dict[str, Any] = json.load(handle)
    if bundle.get("source_checksums", {}).get(r4_path.as_posix()) != _sha256(r4_path):
        raise ValueError("FoodOn artifact references a different R4 taxonomy bundle.")
    if (
        bundle.get("source_dataset") != "FOODON"
        or bundle.get("schema_version") != "0.1.0"
        or bundle.get("method") != "EXACT_NORMALIZED_ENGLISH_OR_UNTAGGED_LABEL_LINK_V1"
        or not bundle.get("mappings")
    ):
        raise ValueError("FoodOn release artifact metadata is invalid.")
    return {
        "status": "PASS",
        "validation_scope": "PINNED_ARTIFACT_AND_TRACKED_R4_SOURCE_ONLY",
        "raw_foodon_rebuilt": False,
        "linked_ingredients": len(bundle["mappings"]),
        "sha256": PINNED_RUNTIME_SHA256,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--foodon",
        type=Path,
        default=Path("data/interim/r2-v0.1.0/full/ontology/foodon_nodes.jsonl"),
    )
    parser.add_argument(
        "--r4",
        type=Path,
        default=Path("data/runtime/r4-taxonomies-v0.1.0.json.gz"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/runtime/foodon-links-v0.1.0.json.gz"),
    )
    validation_mode = parser.add_mutually_exclusive_group()
    validation_mode.add_argument(
        "--check",
        action="store_true",
        help="Rebuild in memory and fail when the tracked runtime bundle is stale.",
    )
    validation_mode.add_argument(
        "--verify-artifact",
        action="store_true",
        help="Verify pinned tracked bytes/R4 source; does not rebuild ignored raw FoodOn data.",
    )
    args = parser.parse_args()
    if args.verify_artifact:
        print(json.dumps(verify_runtime_artifact(args.output, args.r4), sort_keys=True))
        return
    bundle = build_links(args.foodon, args.r4)
    if args.check:
        if not args.output.exists():
            raise SystemExit(f"Missing runtime bundle: {args.output}")
        with gzip.open(args.output, "rt", encoding="utf-8") as handle:
            tracked = json.load(handle)
        if tracked != bundle:
            raise SystemExit(
                "FoodOn runtime links are stale; run scripts/build_foodon_runtime_links.py"
            )
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "linked_ingredients": len(bundle["mappings"]),
                    "sha256": _sha256(args.output),
                },
                sort_keys=True,
            )
        )
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with (
        args.output.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed,
    ):
        compressed.write(payload.encode("utf-8"))
    print(
        json.dumps(
            {
                "output": args.output.as_posix(),
                "linked_ingredients": len(bundle["mappings"]),
                "sha256": _sha256(args.output),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
