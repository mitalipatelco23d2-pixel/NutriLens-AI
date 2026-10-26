"""Validation library for R1 dataset governance and acquisition provenance."""

from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import urlparse

from scripts.data.safe_download import resolve_destination, sha256_file

MODULES = {
    1: "Food Understanding Engine",
    2: "Ingredient Intelligence Engine",
    3: "Food Knowledge Intelligence",
    4: "Personalized Health Intelligence",
    5: "Explainable AI Engine",
    6: "Recommendation Intelligence Engine",
    7: "Personal Nutrition Intelligence",
    8: "Smart Cooking & Pantry Intelligence",
    9: "Nutrition Analytics & Visualization",
    10: "Population & Research Intelligence",
    11: "AI Nutrition Assistant",
    12: "Data & AI Infrastructure",
    13: "Backend Services",
    14: "Cross-Platform User Experience",
    15: "Security, Privacy & Cloud Infrastructure",
}
ACQUISITION_STATUSES = {
    "NOT_REVIEWED",
    "AVAILABLE",
    "DOWNLOADED",
    "PARTIALLY_DOWNLOADED",
    "REGISTRATION_REQUIRED",
    "MANUAL_DOWNLOAD_REQUIRED",
    "LICENSE_REVIEW_REQUIRED",
    "UNAVAILABLE",
    "DEFERRED",
}
SOURCE_TYPES = {
    "DATASET",
    "ONTOLOGY",
    "REGULATORY_REFERENCE",
    "SCIENTIFIC_REFERENCE",
    "KNOWLEDGE_SOURCE",
}
STORAGE_CLASSES = {"SMALL", "MEDIUM", "LARGE", "VERY_LARGE"}
CATEGORIES = {
    "ADDITIVE_TAXONOMY",
    "ALLERGEN_TAXONOMY",
    "COMPUTER_VISION",
    "CUSTOM_COLLECTION",
    "FOOD_COMPOSITION",
    "FOOD_ONTOLOGY",
    "GEOGRAPHY_TAXONOMY",
    "INGREDIENT_TAXONOMY",
    "KNOWLEDGE_GRAPH",
    "MULTILINGUAL",
    "OCR",
    "POPULATION_STATISTICS",
    "PRODUCT_NUTRITION",
    "PRODUCT_TAXONOMY",
    "RECIPES",
    "SCIENTIFIC_REGULATORY",
    "SERVING_DENSITY",
}
CATALOGUE_FIELDS = {
    "Dataset ID",
    "Dataset name",
    "Source type",
    "Category",
    "Provider",
    "Official source URL",
    "Access method",
    "License",
    "License verified?",
    "Commercial-use status",
    "Research-use restriction",
    "Registration required?",
    "Approximate size",
    "Storage class",
    "File format",
    "Main fields/classes",
    "Languages",
    "Geographic coverage",
    "Indian-food relevance",
    "Primary module number",
    "Primary NutriLens module",
    "Related modules",
    "Intended use",
    "Acquisition status",
    "Version/release",
    "Checksum status",
    "Local path",
    "Privacy status",
    "Risks/limitations",
}
TEMPLATE_PATHS = (
    "data/raw/custom/ingredient_synonyms/ingredient-synonyms.csv",
    "data/raw/custom/hidden_sugars/hidden-sugars.csv",
    "data/raw/custom/hidden_sodium/hidden-sodium.csv",
    "data/raw/custom/fats_and_oils/fats-and-oils.csv",
    "data/raw/custom/additive_intelligence/additive-intelligence.csv",
    "data/raw/custom/preservative_intelligence/preservative-intelligence.csv",
    "data/raw/custom/allergen_mapping/allergen-mapping.csv",
    "data/raw/custom/health_suitability_rules/health-suitability-rules.csv",
    "data/raw/custom/ingredient_alternatives/ingredient-alternatives.csv",
    "data/raw/custom/serving_size_knowledge/serving-size-knowledge.csv",
    "data/raw/custom/density_knowledge/density-knowledge.csv",
    "data/raw/custom/multilingual/multilingual-nutrition-terms.csv",
    "data/raw/custom/evidence_corpus/evidence-corpus.csv",
    "data/raw/custom/indian_product_images/indian-product-image-manifest.csv",
    "data/raw/custom/indian_recipe_knowledge/indian-recipe-knowledge.csv",
)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        return [], []
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        return list(reader.fieldnames or []), list(reader)


def duplicate_values(rows: list[dict[str, str]], field: str) -> set[str]:
    values = [row.get(field, "") for row in rows]
    return {value for value in values if value and values.count(value) > 1}


def invalid_values(rows: list[dict[str, str]], field: str, allowed: set[str]) -> set[str]:
    return {row.get(field, "") for row in rows if row.get(field, "") not in allowed}


def missing_license_ids(
    catalogue: list[dict[str, str]], licences: list[dict[str, str]]
) -> set[str]:
    licence_ids = {row.get("Dataset ID", "") for row in licences}
    return {
        row.get("Dataset ID", "") for row in catalogue if row.get("Dataset ID") not in licence_ids
    }


def _valid_reference(root: Path, value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return True
    try:
        return resolve_destination(root, value).exists()
    except ValueError:
        return False


def validate(root: Path, *, require_downloads: bool = True) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    docs = root / "documentation/datasets"
    catalogue_fields, catalogue = read_csv(docs / "dataset-catalogue.csv")
    _, licences = read_csv(docs / "license-register.csv")
    _, mappings = read_csv(docs / "module-dataset-matrix.csv")
    _, evidence = read_csv(docs / "evidence-corpus-manifest.csv")
    _, manifest = read_csv(root / "data/manifests/downloaded-artifacts.csv")

    missing_fields = CATALOGUE_FIELDS - set(catalogue_fields)
    if missing_fields:
        errors.append(f"Catalogue is missing columns: {sorted(missing_fields)}")
    if not catalogue:
        errors.append("Catalogue has no dataset/source rows")
        return errors

    duplicates = duplicate_values(catalogue, "Dataset ID")
    if duplicates:
        errors.append(f"Duplicate Dataset IDs: {sorted(duplicates)}")

    catalogue_by_id = {row["Dataset ID"]: row for row in catalogue}
    licence_ids = {row.get("Dataset ID", "") for row in licences}
    missing_licences = missing_license_ids(catalogue, licences)
    if missing_licences:
        errors.append(f"Datasets missing license rows: {sorted(missing_licences)}")
    manifest_by_id = {row.get("Dataset ID", ""): row for row in manifest}
    manifest_keys = [(row.get("Dataset ID", ""), row.get("Local path", "")) for row in manifest]
    if len(manifest_keys) != len(set(manifest_keys)):
        errors.append("Acquisition manifest contains duplicate dataset/path records")
    for manifest_row in manifest:
        dataset_id = manifest_row.get("Dataset ID", "<missing ID>")
        if dataset_id not in catalogue_by_id:
            errors.append(f"Acquisition manifest references unknown dataset: {dataset_id}")
        if not manifest_row.get("Size bytes", "").isdigit():
            errors.append(f"{dataset_id}: manifest size is not a non-negative integer")
        checksum = manifest_row.get("SHA-256", "")
        if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
            errors.append(f"{dataset_id}: manifest SHA-256 is malformed")
        if not _valid_reference(root, manifest_row.get("Source URL", "")):
            errors.append(f"{dataset_id}: invalid manifest source URL")
    for row in catalogue:
        dataset_id = row.get("Dataset ID", "<missing ID>")
        for field in CATALOGUE_FIELDS:
            if not row.get(field, "").strip():
                errors.append(f"{dataset_id}: required catalogue field is empty: {field}")
        if row.get("Source type") not in SOURCE_TYPES:
            errors.append(f"{dataset_id}: invalid source type {row.get('Source type')}")
        if row.get("Category") not in CATEGORIES:
            errors.append(f"{dataset_id}: invalid category {row.get('Category')}")
        if row.get("Acquisition status") not in ACQUISITION_STATUSES:
            errors.append(f"{dataset_id}: invalid acquisition status")
        if row.get("Storage class") not in STORAGE_CLASSES:
            errors.append(f"{dataset_id}: invalid storage class")
        if not _valid_reference(root, row.get("Official source URL", "")):
            errors.append(f"{dataset_id}: invalid official source URL/path")
        try:
            module_number = int(row.get("Primary module number", "0"))
        except ValueError:
            errors.append(f"{dataset_id}: invalid primary module number")
        else:
            if MODULES.get(module_number) != row.get("Primary NutriLens module"):
                errors.append(f"{dataset_id}: primary module number/name mismatch")

        if row.get("Acquisition status") == "DOWNLOADED":
            if row.get("Checksum status") != "RECORDED":
                errors.append(f"{dataset_id}: DOWNLOADED row lacks RECORDED checksum status")
            acquisition = manifest_by_id.get(dataset_id)
            if acquisition is None:
                errors.append(f"{dataset_id}: DOWNLOADED row lacks acquisition manifest")
                continue
            if acquisition.get("Local path") != row.get("Local path"):
                errors.append(f"{dataset_id}: catalogue and manifest local paths differ")
            if not require_downloads:
                continue
            try:
                local_path = resolve_destination(root, row["Local path"])
            except ValueError as exc:
                errors.append(f"{dataset_id}: {exc}")
                continue
            if not local_path.is_file():
                errors.append(f"{dataset_id}: DOWNLOADED local file is missing")
                continue
            if str(local_path.stat().st_size) != acquisition.get("Size bytes"):
                errors.append(f"{dataset_id}: local byte size differs from manifest")
            if sha256_file(local_path) != acquisition.get("SHA-256"):
                errors.append(f"{dataset_id}: local SHA-256 differs from manifest")

    if duplicate_values(licences, "Dataset ID"):
        errors.append("License register contains duplicate Dataset IDs")
    unknown_licences = licence_ids - set(catalogue_by_id)
    if unknown_licences:
        errors.append(f"License rows reference unknown datasets: {sorted(unknown_licences)}")

    mapped_modules: set[int] = set()
    for row in mappings:
        dataset_id = row.get("Dataset ID", "")
        try:
            module_number = int(row.get("Module number", "0"))
        except ValueError:
            errors.append(f"Matrix row for {dataset_id}: invalid module number")
            continue
        mapped_modules.add(module_number)
        if MODULES.get(module_number) != row.get("Module name"):
            errors.append(f"Matrix row for {dataset_id}: module number/name mismatch")
        if dataset_id not in catalogue_by_id:
            errors.append(f"Matrix references unknown dataset: {dataset_id}")
        elif row.get("Acquisition status") != catalogue_by_id[dataset_id]["Acquisition status"]:
            errors.append(f"Matrix/catalogue status mismatch: {dataset_id}")
        if row.get("Required/optional") not in {"REQUIRED", "OPTIONAL"}:
            errors.append(f"Matrix row for {dataset_id}: invalid requirement classification")
    if mapped_modules != set(MODULES):
        errors.append(f"Module matrix coverage is {sorted(mapped_modules)}, expected 1-15")

    evidence_ids = [row.get("Evidence ID", "") for row in evidence]
    if not evidence_ids or any(not item for item in evidence_ids):
        errors.append("Evidence manifest has missing Evidence IDs")
    if len(evidence_ids) != len(set(evidence_ids)):
        errors.append("Evidence manifest contains duplicate Evidence IDs")
    for row in evidence:
        if not _valid_reference(root, row.get("URL", "")):
            errors.append(f"{row.get('Evidence ID')}: invalid evidence URL")

    for relative in TEMPLATE_PATHS:
        path = resolve_destination(root, relative)
        fields, rows = read_csv(path)
        if rows:
            errors.append(f"{relative}: R1 custom template must remain header-only")
        required = {"version", "review_status"}
        if not required.issubset(fields):
            errors.append(f"{relative}: missing version/review_status schema fields")
        if not ({"source_id", "source_reference", "url"} & set(fields)):
            errors.append(f"{relative}: missing source/reference field")

    for forbidden in (root / "data/interim", root / "data/processed"):
        if forbidden.exists():
            unexpected = [
                path
                for path in forbidden.rglob("*")
                if path.is_file()
                and path.name != "README.md"
                and not path.relative_to(forbidden).parts[0].startswith(("r2-v", "r3-real-v"))
            ]
            if unexpected:
                errors.append(
                    f"unversioned transformed output detected in {forbidden.relative_to(root)}"
                )
    return errors
