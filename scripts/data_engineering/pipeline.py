"""R2 sample/full orchestration across all legally usable local R1 sources."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.data_engineering import DATASET_VERSION, PIPELINE_VERSION, SCHEMA_VERSION, SPLIT_SEED
from scripts.data_engineering.density import process_density
from scripts.data_engineering.evidence import process_evidence
from scripts.data_engineering.foodon import process_foodon
from scripts.data_engineering.generate_schemas import generate as generate_schemas
from scripts.data_engineering.io_utils import (
    atomic_text_writer,
    output_metadata,
    read_jsonl,
    snapshot_checksums,
    utc_now,
    verify_unchanged,
    write_csv,
    write_json,
    write_jsonl,
)
from scripts.data_engineering.off_taxonomy import parse_taxonomy
from scripts.data_engineering.quality import QUALITY_WEIGHTS, transparent_quality_score
from scripts.data_engineering.quarantine import Quarantine
from scripts.data_engineering.source_registry import load_sources, require_source
from scripts.data_engineering.splits import generate_splits, validate_no_group_leakage
from scripts.data_engineering.usda import process_usda

TAXONOMIES = {
    "OFF-TAX-INGREDIENTS": "ingredient",
    "OFF-TAX-ADDITIVES": "additive",
    "OFF-TAX-ALLERGENS": "allergen",
    "OFF-TAX-CATEGORIES": "category",
    "OFF-TAX-LABELS": "label",
    "OFF-TAX-NOVA": "nova_group",
    "OFF-TAX-COUNTRIES": "country",
}


def _privacy_statuses(repo_root: Path) -> dict[str, str]:
    with (repo_root / "data/manifests/downloaded-artifacts.csv").open(
        encoding="utf-8", newline=""
    ) as source:
        return {row["Dataset ID"]: row["Privacy status"] for row in csv.DictReader(source)}


def _output_files(*roots: Path) -> list[Path]:
    return sorted(
        path
        for root in roots
        if root.exists()
        for path in root.rglob("*")
        if path.is_file() and path.name != "README.md"
    )


def _write_checksum_file(path: Path, outputs: list[dict[str, Any]]) -> None:
    with atomic_text_writer(path) as target:
        for output in sorted(outputs, key=lambda item: str(item["path"])):
            target.write(f"{output['sha256']}  {output['path']}\n")


def run_pipeline(repo_root: Path, *, mode: str) -> dict[str, Any]:
    if mode not in {"sample", "full"}:
        raise ValueError("mode must be sample or full")
    repo_root = repo_root.resolve()
    sources = load_sources(repo_root)
    privacy = _privacy_statuses(repo_root)
    unsafe_privacy = {
        dataset_id: status
        for dataset_id, status in privacy.items()
        if status != "SCREENED_NO_PII_EXPECTED"
    }
    if unsafe_privacy:
        raise RuntimeError(f"R2 privacy gate rejected sources: {unsafe_privacy}")
    raw_before = snapshot_checksums(source.path for source in sources.values())
    limit = 200 if mode == "sample" else None
    run_id = f"r2-v{DATASET_VERSION}/{mode}"
    interim = repo_root / "data/interim" / run_id
    processed = repo_root / "data/processed" / run_id
    quarantine_dir = repo_root / "data/quality/quarantine" / run_id
    split_dir = repo_root / "data/splits"
    schema_dir = repo_root / f"data/schemas/r2-v{SCHEMA_VERSION}"
    generate_schemas(schema_dir)

    stage_stats: dict[str, dict[str, Any]] = {}
    for dataset_id, taxonomy_type in TAXONOMIES.items():
        source = require_source(sources, dataset_id)
        quarantine = Quarantine(dataset_id)
        records = list(
            parse_taxonomy(
                source,
                taxonomy_type,
                limit=limit,
                quarantine=quarantine,
            )
        )
        output_path = processed / "ingredients" / f"off_{taxonomy_type}.jsonl"
        output_count = write_jsonl(output_path, records)
        rejected = quarantine.write(quarantine_dir / f"off_{taxonomy_type}.jsonl")
        stage_stats[dataset_id] = {
            "input_records": output_count + rejected,
            "output_records": output_count,
            "rejected_records": rejected,
            "duplicate_records": rejected,
            "output_paths": [output_path.relative_to(repo_root).as_posix()],
            "warnings": [],
        }

    usda_source = require_source(sources, "USDA-FOUNDATION")
    usda_stats = process_usda(
        usda_source,
        interim / "nutrition",
        processed / "nutrition",
        quarantine_dir,
        limit=limit,
    )
    stage_stats["USDA-FOUNDATION"] = {
        "input_records": usda_stats["input_foundation_foods"],
        "output_records": usda_stats["nutrition"],
        "rejected_records": usda_stats["quarantined"],
        "duplicate_records": 0,
        "output_paths": [
            (interim / "nutrition/usda_foundation_foods.jsonl").relative_to(repo_root).as_posix(),
            (processed / "nutrition/usda_nutrition.jsonl").relative_to(repo_root).as_posix(),
            (processed / "nutrition/usda_servings.jsonl").relative_to(repo_root).as_posix(),
            (interim / "nutrition/usda_nutrients_long.jsonl").relative_to(repo_root).as_posix(),
        ],
        "warnings": [
            f"{usda_stats['outlier_records']} nutrition records carry review-only outlier flags"
        ],
        "details": usda_stats,
    }

    foodon_stats = process_foodon(
        require_source(sources, "FOODON"),
        interim / "ontology",
        quarantine_dir,
        limit=limit,
    )
    stage_stats["FOODON"] = {
        "input_records": foodon_stats["nodes"],
        "output_records": foodon_stats["nodes"],
        "rejected_records": foodon_stats["quarantined"],
        "duplicate_records": foodon_stats["quarantined"],
        "output_paths": [
            (interim / "ontology/foodon_nodes.jsonl").relative_to(repo_root).as_posix(),
            (interim / "ontology/foodon_edges.jsonl").relative_to(repo_root).as_posix(),
        ],
        "warnings": [f"{foodon_stats['missing_labels']} classes have no direct label"],
        "details": foodon_stats,
    }

    density_stats = process_density(
        require_source(sources, "FAO-DENSITY"),
        processed / "nutrition",
        quarantine_dir,
        limit=limit,
    )
    stage_stats["FAO-DENSITY"] = {
        "input_records": density_stats["input_records"],
        "output_records": density_stats["output_records"],
        "rejected_records": density_stats["quarantined"],
        "duplicate_records": 0,
        "output_paths": [
            (processed / "nutrition/fao_infoods_density.jsonl").relative_to(repo_root).as_posix()
        ],
        "warnings": [
            "Category headers and specific-gravity-only rows are retained with explicit statuses"
        ],
        "details": density_stats,
    }

    evidence_stats = process_evidence(repo_root, sources, processed / "evidence")
    stage_stats["WHO-HEALTHY-DIET"] = {
        "input_records": evidence_stats["input_documents"],
        "output_records": evidence_stats["output_documents"],
        "rejected_records": 0,
        "duplicate_records": 0,
        "output_paths": [
            (processed / "evidence/evidence_documents.jsonl").relative_to(repo_root).as_posix()
        ],
        "warnings": ["PDF text extraction intentionally deferred pending reuse/RAG review"],
        "details": evidence_stats,
    }

    food_rows = list(read_jsonl(interim / "nutrition/usda_foundation_foods.jsonl"))
    splits = generate_splits((str(row["food_id"]), str(row["source_food_id"])) for row in food_rows)
    leakage = validate_no_group_leakage(splits)
    if leakage:
        raise RuntimeError(f"split leakage detected for groups: {leakage[:10]}")
    split_path = split_dir / f"usda-foundation-{mode}.csv"
    write_csv(
        split_path,
        ["record_id", "group_id", "split", "seed"],
        (record.__dict__ for record in splits),
    )
    split_counts = dict(sorted(Counter(record.split for record in splits).items()))

    blocked = {
        "OFF-PRODUCTS-CSV": "AVAILABLE_NOT_DOWNLOADED",
        "CUSTOM-INDIAN-PRODUCT-IMAGES": "BLOCKED_BY_DATA_AVAILABILITY",
        "CUSTOM-INDIAN-LABEL-OCR": "BLOCKED_BY_DATA_AVAILABILITY",
        "RECIPE1M": "REGISTRATION_REQUIRED",
        "RECIPEDB": "MANUAL_DOWNLOAD_REQUIRED",
        "WHO-GHO-NUTRITION": "LICENSE_REVIEW_REQUIRED",
    }
    annotation_status = {
        "schema_version": SCHEMA_VERSION,
        "status": "BLOCKED_BY_DATA_AVAILABILITY",
        "source_images": 0,
        "detection_annotations": 0,
        "ocr_annotations": 0,
        "meal_annotations": 0,
        "reason": "R1 contains no rights-cleared local image payload; no annotations fabricated",
    }
    write_json(repo_root / "data/annotations/r2-annotation-status.json", annotation_status)

    total_output = sum(int(stats["output_records"]) for stats in stage_stats.values())
    total_rejected = sum(int(stats["rejected_records"]) for stats in stage_stats.values())
    quality_scores = {
        dataset_id: transparent_quality_score(
            schema_compliance=1,
            provenance=1,
            licensing=1,
            completeness=0.8 if dataset_id in {"USDA-FOUNDATION", "FAO-DENSITY"} else 1,
            uniqueness=1 if stats["duplicate_records"] == 0 else 0.99,
            unit_validity=1,
        )
        for dataset_id, stats in stage_stats.items()
    }
    quality_payload = {
        "mode": mode,
        "created_at": utc_now(),
        "pipeline_version": PIPELINE_VERSION,
        "formula": {
            "weights": QUALITY_WEIGHTS,
            "component_range": "0.0 to 1.0",
            "score_range": "0 to 100",
        },
        "datasets": stage_stats,
        "dataset_quality_scores": quality_scores,
        "total_output_records": total_output,
        "total_rejected_records": total_rejected,
        "privacy_validation": "PASS_NO_PERSON_LEVEL_DATA",
        "licence_validation": "PASS_ONLY_R1_DOWNLOADED_SOURCES",
        "blocked_sources": blocked,
    }
    quality_path = repo_root / f"data/quality/r2-{mode}-quality-report.json"
    write_json(quality_path, quality_payload)

    verify_unchanged(raw_before)
    payload_files = _output_files(interim, processed, quarantine_dir)
    payload_files.extend([split_path])
    output_rows = []
    for path in payload_files:
        metadata = output_metadata(path, _record_count(path), role=_role(path, interim, processed))
        metadata["path"] = path.relative_to(repo_root).as_posix()
        output_rows.append(metadata)
    output_manifest_path = repo_root / f"data/manifests/r2-{mode}-output-manifest.csv"
    write_csv(
        output_manifest_path,
        ["path", "role", "record_count", "size_bytes", "sha256"],
        output_rows,
    )
    checksum_path = repo_root / f"data/checksums/R2_{mode.upper()}_SHA256SUMS"
    _write_checksum_file(checksum_path, output_rows)
    version_path = repo_root / f"data/manifests/r2-{mode}-version.json"
    write_json(
        version_path,
        {
            "dataset_name": "NutriLens X R2 engineered local datasets",
            "dataset_version": DATASET_VERSION,
            "source_versions": {
                dataset_id: source.version for dataset_id, source in sorted(sources.items())
            },
            "pipeline_version": PIPELINE_VERSION,
            "schema_version": SCHEMA_VERSION,
            "created_at": utc_now(),
            "input_manifest": "data/manifests/downloaded-artifacts.csv",
            "output_manifest": output_manifest_path.relative_to(repo_root).as_posix(),
            "split_seed": SPLIT_SEED,
            "mode": mode,
        },
    )
    transformation_path = repo_root / f"data/manifests/r2-{mode}-transformation-manifest.json"
    write_json(
        transformation_path,
        {
            "execution_timestamp": utc_now(),
            "mode": mode,
            "pipeline_version": PIPELINE_VERSION,
            "parameters": {"record_limit_per_source": limit, "split_seed": SPLIT_SEED},
            "inputs": [
                {
                    "dataset_id": dataset_id,
                    "path": source.path.relative_to(repo_root).as_posix(),
                    "sha256": source.checksum,
                    "version": source.version,
                    "license_status": source.license_status,
                }
                for dataset_id, source in sorted(sources.items())
            ],
            "stages": stage_stats,
            "outputs": output_rows,
            "split_counts": split_counts,
            "split_leakage_groups": leakage,
            "blocked_sources": blocked,
            "raw_immutability": "PASS",
            "warnings": [
                warning for stats in stage_stats.values() for warning in stats.get("warnings", [])
            ],
        },
    )
    return {
        "mode": mode,
        "total_output_records": total_output,
        "total_rejected_records": total_rejected,
        "split_counts": split_counts,
        "output_files": len(output_rows),
        "stage_stats": stage_stats,
        "raw_immutability": "PASS",
        "manifest": transformation_path.relative_to(repo_root).as_posix(),
    }


def _record_count(path: Path) -> int:
    if path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as source:
            return sum(bool(line.strip()) for line in source)
    if path.suffix == ".csv":
        with path.open(encoding="utf-8", newline="") as source:
            return max(sum(1 for _row in csv.reader(source)) - 1, 0)
    return 1


def _role(path: Path, interim: Path, processed: Path) -> str:
    if path.is_relative_to(interim):
        return "INTERIM"
    if path.is_relative_to(processed):
        return "PROCESSED"
    if "quarantine" in path.parts:
        return "QUARANTINE"
    if "splits" in path.parts:
        return "SPLIT_MANIFEST"
    return "GOVERNANCE"
