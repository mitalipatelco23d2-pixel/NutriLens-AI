"""FAO/INFOODS Density Database v2.0 canonical transformation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from scripts.data_engineering.io_utils import write_jsonl
from scripts.data_engineering.normalization import normalize_display_text
from scripts.data_engineering.quarantine import Quarantine
from scripts.data_engineering.schemas import DensityRecord
from scripts.data_engineering.source_registry import SourceInfo
from scripts.data_engineering.xlsx_reader import iter_xlsx_rows


def _number(value: Any) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def process_density(
    source: SourceInfo,
    output_dir: Path,
    quarantine_dir: Path,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    quarantine = Quarantine(source.dataset_id)
    records: list[DensityRecord] = []
    input_records = 0
    for row_number, values in iter_xlsx_rows(source.path, "Density DB"):
        if row_number == 1:
            continue
        if not values or values[0] in {None, ""}:
            continue
        input_records += 1
        food_name = normalize_display_text(str(values[0]))
        density_original = values[1] if len(values) > 1 else None
        specific_gravity = values[2] if len(values) > 2 else None
        bibliography_id = str(values[3]).strip() if len(values) > 3 and values[3] else None
        density = _number(density_original)
        if density is not None and density <= 0:
            quarantine.add(
                source_record_id=f"row-{row_number}",
                stage="DENSITY_NORMALIZATION",
                rule="POSITIVE_DENSITY",
                reason=f"density must be positive, got {density}",
                snapshot={"food_name": food_name, "density": density_original},
            )
            density = None
        if density is not None:
            status: Literal["MEASUREMENT", "PARTIAL_REFERENCE", "CATEGORY_HEADER"] = "MEASUREMENT"
            notes = None
        elif specific_gravity not in {None, ""}:
            status = "PARTIAL_REFERENCE"
            notes = "Source has specific gravity but no directly reported g/mL density"
        else:
            status = "CATEGORY_HEADER"
            notes = "Source category/header row retained; not a density measurement"
        records.append(
            DensityRecord(
                food_id=f"fao-density:row-{row_number}",
                food_name=food_name,
                density=density,
                density_unit="g/mL" if density is not None else None,
                specific_gravity_original=specific_gravity,
                temperature_or_condition=None,
                bibliography_id=bibliography_id,
                source_row=row_number,
                record_status=status,
                quality_notes=notes,
                lineage=source.lineage(f"row-{row_number}"),
            )
        )
        if limit is not None and len(records) >= limit:
            break
    output_dir.mkdir(parents=True, exist_ok=True)
    output_count = write_jsonl(output_dir / "fao_infoods_density.jsonl", records)
    quarantined = quarantine.write(quarantine_dir / "fao_density.jsonl")
    return {
        "input_records": input_records,
        "output_records": output_count,
        "quarantined": quarantined,
        "measurements": sum(record.record_status == "MEASUREMENT" for record in records),
        "partial_references": sum(
            record.record_status == "PARTIAL_REFERENCE" for record in records
        ),
        "category_headers": sum(record.record_status == "CATEGORY_HEADER" for record in records),
        "missing_density_rate": round(
            sum(record.density is None for record in records) / len(records), 6
        )
        if records
        else 0.0,
    }
