"""USDA Foundation Foods ZIP parser and canonical nutrition/serving transformation."""

from __future__ import annotations

import csv
import io
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scripts.data_engineering.io_utils import write_jsonl
from scripts.data_engineering.normalization import (
    derive_salt_from_sodium,
    normalize_display_text,
    normalize_reported_value,
)
from scripts.data_engineering.quality import nutrition_outlier_flags, transparent_quality_score
from scripts.data_engineering.quarantine import Quarantine
from scripts.data_engineering.schemas import (
    MissingReason,
    NutrientValue,
    NutritionRecord,
    ServingRecord,
)
from scripts.data_engineering.source_registry import SourceInfo

NUTRIENT_MAP: dict[tuple[str, str], tuple[str, str]] = {
    ("Energy", "KCAL"): ("energy_kcal", "kcal"),
    ("Energy", "kJ"): ("energy_kj", "kJ"),
    ("Protein", "G"): ("protein_g", "g"),
    ("Carbohydrate, by difference", "G"): ("carbohydrates_g", "g"),
    ("Total Sugars", "G"): ("sugars_g", "g"),
    ("Sugars, Total", "G"): ("sugars_g", "g"),
    ("Total lipid (fat)", "G"): ("total_fat_g", "g"),
    ("Fatty acids, total saturated", "G"): ("saturated_fat_g", "g"),
    ("Fiber, total dietary", "G"): ("fiber_g", "g"),
    ("Sodium, Na", "MG"): ("sodium_mg", "mg"),
    ("Cholesterol", "MG"): ("cholesterol_mg", "mg"),
    ("Calcium, Ca", "MG"): ("calcium_mg", "mg"),
    ("Iron, Fe", "MG"): ("iron_mg", "mg"),
    ("Potassium, K", "MG"): ("potassium_mg", "mg"),
}
CANONICAL_FIELDS = (
    "energy_kj",
    "energy_kcal",
    "protein_g",
    "carbohydrates_g",
    "sugars_g",
    "total_fat_g",
    "saturated_fat_g",
    "fiber_g",
    "sodium_mg",
    "salt_g",
    "cholesterol_mg",
    "calcium_mg",
    "iron_mg",
    "potassium_mg",
)


class USDAZip:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.archive = zipfile.ZipFile(path)
        self.members = {Path(name).name: name for name in self.archive.namelist()}

    def rows(self, filename: str) -> Iterable[dict[str, str]]:
        member = self.members[filename]
        with (
            self.archive.open(member) as binary,
            io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as text,
        ):
            yield from csv.DictReader(text)

    def close(self) -> None:
        self.archive.close()


def _float(value: str) -> float | None:
    if value.strip() == "":
        return None
    return float(value)


def process_usda(
    source: SourceInfo,
    interim_dir: Path,
    output_dir: Path,
    quarantine_dir: Path,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    archive = USDAZip(source.path)
    quarantine = Quarantine(source.dataset_id)
    try:
        foundation_ids = [row["fdc_id"] for row in archive.rows("foundation_food.csv")]
        if limit is not None:
            foundation_ids = foundation_ids[:limit]
        selected = set(foundation_ids)
        categories = {row["id"]: row["description"] for row in archive.rows("food_category.csv")}
        measures = {row["id"]: row["name"] for row in archive.rows("measure_unit.csv")}
        foods: dict[str, dict[str, Any]] = {}
        for row in archive.rows("food.csv"):
            if row["fdc_id"] not in selected:
                continue
            foods[row["fdc_id"]] = {
                "food_id": f"usda:{row['fdc_id']}",
                "source_food_id": row["fdc_id"],
                "description_original": row["description"],
                "description": normalize_display_text(row["description"]),
                "food_category_id": row["food_category_id"] or None,
                "food_category": categories.get(row["food_category_id"]),
                "data_type": row["data_type"],
                "publication_date": row["publication_date"] or None,
                "lineage": source.lineage(row["fdc_id"]).model_dump(mode="json"),
            }

        nutrient_metadata = {
            row["id"]: {"name": row["name"], "unit": row["unit_name"]}
            for row in archive.rows("nutrient.csv")
        }
        canonical: dict[str, dict[str, NutrientValue]] = {food_id: {} for food_id in selected}
        long_rows: list[dict[str, Any]] = []
        for row in archive.rows("food_nutrient.csv"):
            food_id = row["fdc_id"]
            if food_id not in selected:
                continue
            metadata = nutrient_metadata.get(row["nutrient_id"])
            if metadata is None:
                quarantine.add(
                    source_record_id=row["id"],
                    stage="USDA_NUTRIENT_JOIN",
                    rule="KNOWN_NUTRIENT_ID",
                    reason=f"unknown nutrient ID {row['nutrient_id']}",
                    snapshot=row,
                )
                continue
            try:
                amount = _float(row["amount"])
                if amount is None or amount < 0:
                    raise ValueError("amount is missing or negative")
            except ValueError as exc:
                quarantine.add(
                    source_record_id=row["id"],
                    stage="USDA_NUTRIENT_PARSE",
                    rule="NON_NEGATIVE_NUMERIC_VALUE",
                    reason=str(exc),
                    snapshot=row,
                )
                continue
            long_rows.append(
                {
                    "source_food_id": food_id,
                    "source_food_nutrient_id": row["id"],
                    "source_nutrient_id": row["nutrient_id"],
                    "nutrient_name": metadata["name"],
                    "reported_value": amount,
                    "reported_unit": metadata["unit"],
                    "data_points": _float(row["data_points"]),
                    "derivation_id": row["derivation_id"] or None,
                    "lineage": source.lineage(row["id"]).model_dump(mode="json"),
                }
            )
            mapped = NUTRIENT_MAP.get((metadata["name"], metadata["unit"]))
            if mapped and mapped[0] not in canonical[food_id]:
                canonical[food_id][mapped[0]] = normalize_reported_value(
                    amount,
                    metadata["unit"],
                    mapped[1],
                    source_nutrient_id=row["nutrient_id"],
                )

        nutrition_records: list[NutritionRecord] = []
        for food_id in foundation_ids:
            values = canonical[food_id]
            for field in CANONICAL_FIELDS:
                values.setdefault(field, NutrientValue(missing_reason=MissingReason.NOT_REPORTED))
            sodium = values["sodium_mg"]
            if sodium.normalized_value is not None:
                values["salt_g"] = derive_salt_from_sodium(sodium)
            present = sum(
                value.normalized_value is not None
                for field, value in values.items()
                if field != "salt_g"
            )
            completeness = present / (len(CANONICAL_FIELDS) - 1)
            score = transparent_quality_score(
                schema_compliance=1,
                provenance=1,
                licensing=1,
                completeness=completeness,
                uniqueness=1,
                unit_validity=1,
            )
            draft: dict[str, Any] = {
                "food_id": f"usda:{food_id}",
                "food_name": foods.get(food_id, {}).get("description", f"USDA {food_id}"),
                **values,
                "data_quality_score": score,
                "lineage": source.lineage(food_id),
            }
            draft["outlier_flags"] = nutrition_outlier_flags(
                {key: value.model_dump(mode="json") for key, value in values.items()}
            )
            nutrition_records.append(NutritionRecord.model_validate(draft))

        servings: list[ServingRecord] = []
        for row in archive.rows("food_portion.csv"):
            if row["fdc_id"] not in selected:
                continue
            try:
                amount = _float(row["amount"])
                gram_weight = _float(row["gram_weight"])
                servings.append(
                    ServingRecord(
                        serving_id=f"usda-portion:{row['id']}",
                        food_id=f"usda:{row['fdc_id']}",
                        description=row["portion_description"] or row["modifier"] or None,
                        amount=amount,
                        measure_unit=measures.get(row["measure_unit_id"]),
                        gram_weight=gram_weight,
                        geographic_context="United States",
                        method="USDA_REPORTED_PORTION",
                        lineage=source.lineage(row["id"]),
                    )
                )
            except ValueError as exc:
                quarantine.add(
                    source_record_id=row["id"],
                    stage="USDA_PORTION_PARSE",
                    rule="POSITIVE_PORTION_VALUE",
                    reason=str(exc),
                    snapshot=row,
                )

        interim_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        counts: dict[str, Any] = {
            "foods": write_jsonl(interim_dir / "usda_foundation_foods.jsonl", foods.values()),
            "nutrients_long": write_jsonl(interim_dir / "usda_nutrients_long.jsonl", long_rows),
            "nutrition": write_jsonl(output_dir / "usda_nutrition.jsonl", nutrition_records),
            "servings": write_jsonl(output_dir / "usda_servings.jsonl", servings),
            "quarantined": quarantine.write(quarantine_dir / "usda_foundation.jsonl"),
        }
        counts["input_foundation_foods"] = len(foundation_ids)
        counts["outlier_records"] = sum(bool(record.outlier_flags) for record in nutrition_records)
        counts["canonical_nutrient_coverage"] = {
            field: sum(
                getattr(record, field) is not None
                and getattr(record, field).normalized_value is not None
                for record in nutrition_records
            )
            for field in CANONICAL_FIELDS
        }
        return counts
    finally:
        archive.close()
