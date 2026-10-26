"""Validate R2 governance, manifests, checksums, lineage, splits, and local outputs."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.data_engineering import (
    DATASET_VERSION,
    PIPELINE_VERSION,
    SCHEMA_VERSION,
    SPLIT_SEED,
)
from scripts.data_engineering.generate_schemas import MODELS
from scripts.data_engineering.io_utils import read_jsonl, sha256_file
from scripts.data_engineering.splits import SplitRecord, validate_no_group_leakage
from scripts.r1_validation import validate as validate_r1


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def _checksum_rows(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        checksum, output_path = line.split(maxsplit=1)
        rows[output_path.strip()] = checksum
    return rows


def validate(repo_root: Path, *, require_payloads: bool = True) -> list[str]:
    repo_root = repo_root.resolve()
    errors = [
        f"R1: {error}" for error in validate_r1(repo_root, require_downloads=require_payloads)
    ]
    schema_dir = repo_root / f"data/schemas/r2-v{SCHEMA_VERSION}"
    for schema_name in MODELS:
        path = schema_dir / f"{schema_name}.schema.json"
        if not path.is_file():
            errors.append(f"missing JSON Schema: {path.relative_to(repo_root)}")
            continue
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"invalid JSON Schema {path.name}: {exc}")
            continue
        if schema.get("x-nutrilens-schema-version") != SCHEMA_VERSION:
            errors.append(f"wrong schema version: {path.name}")

    annotation_status_path = repo_root / "data/annotations/r2-annotation-status.json"
    if not annotation_status_path.is_file():
        errors.append("missing annotation availability status")
    else:
        status = json.loads(annotation_status_path.read_text(encoding="utf-8"))
        if status.get("status") != "BLOCKED_BY_DATA_AVAILABILITY":
            errors.append("annotation status must remain blocked until real images exist")
        if any(
            status.get(field) != 0
            for field in ("source_images", "detection_annotations", "ocr_annotations")
        ):
            errors.append("annotation counts conflict with R1 image availability")

    modes = ("sample", "full") if require_payloads else ("sample",)
    for mode in modes:
        transformation_path = repo_root / f"data/manifests/r2-{mode}-transformation-manifest.json"
        output_manifest_path = repo_root / f"data/manifests/r2-{mode}-output-manifest.csv"
        version_path = repo_root / f"data/manifests/r2-{mode}-version.json"
        checksum_path = repo_root / f"data/checksums/R2_{mode.upper()}_SHA256SUMS"
        required_governance = (
            transformation_path,
            output_manifest_path,
            version_path,
            checksum_path,
        )
        if any(not path.is_file() for path in required_governance):
            errors.append(f"missing {mode} transformation/output/version/checksum governance")
            continue
        transformation = json.loads(transformation_path.read_text(encoding="utf-8"))
        if transformation.get("raw_immutability") != "PASS":
            errors.append(f"{mode}: raw immutability not recorded as PASS")
        if transformation.get("pipeline_version") != PIPELINE_VERSION:
            errors.append(f"{mode}: transformation pipeline version mismatch")
        if transformation.get("parameters", {}).get("split_seed") != SPLIT_SEED:
            errors.append(f"{mode}: transformation split seed mismatch")
        for source in transformation.get("inputs", []):
            source_path = repo_root / source["path"]
            if require_payloads and (
                not source_path.is_file() or sha256_file(source_path) != source["sha256"]
            ):
                errors.append(f"{mode}: source checksum mismatch: {source['path']}")
        output_rows = _csv_rows(output_manifest_path)
        if not output_rows:
            errors.append(f"{mode}: output manifest is empty")
        output_checksums = {row["path"]: row["sha256"] for row in output_rows}
        if _checksum_rows(checksum_path) != output_checksums:
            errors.append(f"{mode}: checksum list differs from output manifest")
        version = json.loads(version_path.read_text(encoding="utf-8"))
        expected_version = {
            "dataset_version": DATASET_VERSION,
            "pipeline_version": PIPELINE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "mode": mode,
            "split_seed": SPLIT_SEED,
            "input_manifest": "data/manifests/downloaded-artifacts.csv",
            "output_manifest": output_manifest_path.relative_to(repo_root).as_posix(),
        }
        for field, expected in expected_version.items():
            if version.get(field) != expected:
                errors.append(f"{mode}: version metadata mismatch for {field}")
        for row in output_rows:
            if Path(row["path"]).is_absolute():
                errors.append(f"{mode}: output manifest path must be repository-relative")
            path = repo_root / row["path"]
            if require_payloads and (
                not path.is_file()
                or sha256_file(path) != row["sha256"]
                or str(path.stat().st_size) != row["size_bytes"]
            ):
                errors.append(f"{mode}: output checksum/size mismatch: {row['path']}")

    if require_payloads:
        lineage_sources = {
            row["Dataset ID"]: row
            for row in _csv_rows(repo_root / "data/manifests/downloaded-artifacts.csv")
        }
        split_path = repo_root / "data/splits/usda-foundation-full.csv"
        if not split_path.is_file():
            errors.append("missing full USDA split manifest")
        else:
            split_rows = _csv_rows(split_path)
            splits = [
                SplitRecord(row["record_id"], row["group_id"], row["split"], int(row["seed"]))
                for row in split_rows
            ]
            leakage = validate_no_group_leakage(splits)
            if leakage:
                errors.append(f"full split leakage detected: {leakage[:10]}")

        validation_targets = {
            "usda_nutrition.jsonl": "nutrition",
            "usda_servings.jsonl": "serving",
            "fao_infoods_density.jsonl": "density",
            "foodon_nodes.jsonl": "ontology-node",
            "foodon_edges.jsonl": "ontology-edge",
            "evidence_documents.jsonl": "evidence-document",
        }
        for path in (repo_root / "data").rglob("*.jsonl"):
            target_model_name: str | None
            if "quarantine" in path.parts:
                target_model_name = "quarantine"
            elif path.name.startswith("off_"):
                target_model_name = "taxonomy"
            else:
                target_model_name = validation_targets.get(path.name)
            if target_model_name and "r2-v0.1.0" in path.parts and "full" in path.parts:
                model = MODELS[target_model_name]
                try:
                    for row in read_jsonl(path):
                        model.model_validate(row)
                        if target_model_name == "quarantine":
                            continue
                        lineage = row.get("lineage")
                        if not isinstance(lineage, dict):
                            raise ValueError("source-backed record has no lineage object")
                        source = lineage_sources.get(str(lineage.get("source_dataset")))
                        if source is None:
                            raise ValueError("lineage source_dataset is absent from R1 manifest")
                        if lineage.get("input_checksum") != source["SHA-256"]:
                            raise ValueError("lineage input checksum differs from R1 manifest")
                        if lineage.get("source_version") != source["Version"]:
                            raise ValueError("lineage source version differs from R1 manifest")
                        if lineage.get("pipeline_version") != PIPELINE_VERSION:
                            raise ValueError("lineage pipeline version mismatch")
                        if lineage.get("schema_version") != SCHEMA_VERSION:
                            raise ValueError("lineage schema version mismatch")
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    errors.append(f"schema validation failed for {path.name}: {exc}")

    prohibited_suffixes = {".pt", ".pth", ".onnx", ".faiss", ".index", ".embeddings"}
    # Keep the historical R2 validator scoped to R2-owned payloads. Later releases
    # legitimately create ignored local model artifacts and validate Git tracking
    # separately; treating those as R2 contents makes the frozen R2 check order-dependent.
    prohibited = [
        path.relative_to(repo_root).as_posix()
        for path in (repo_root / "data").rglob("*")
        if path.is_file()
        and "r2-v0.1.0" in path.parts
        and path.suffix.lower() in prohibited_suffixes
    ]
    if prohibited:
        errors.append(f"R2 contains prohibited model/index artifacts: {prohibited}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--governance-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    errors = validate(root, require_payloads=not args.governance_only)
    if errors:
        print(f"R2 validation failed with {len(errors)} issue(s):")
        for error in errors:
            print(f"- {error}")
        return 1
    scope = "governance" if args.governance_only else "governance and local payloads"
    print(f"R2 {scope} validated successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
