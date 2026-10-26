"""Transparent R2 quality metrics, duplicate classification, and outlier flags."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from scripts.data_engineering.schemas import DuplicateClass

QUALITY_WEIGHTS = {
    "schema_compliance": 25,
    "provenance": 20,
    "licensing": 15,
    "completeness": 20,
    "uniqueness": 10,
    "unit_validity": 10,
}


@dataclass(frozen=True)
class DuplicateFinding:
    record_id: str
    duplicate_of: str | None
    classification: DuplicateClass


def classify_duplicates(
    records: Iterable[Mapping[str, Any]], *, id_field: str, exact_key_fields: tuple[str, ...]
) -> list[DuplicateFinding]:
    seen_ids: set[str] = set()
    seen_keys: dict[str, str] = {}
    findings: list[DuplicateFinding] = []
    for record in records:
        record_id = str(record.get(id_field, ""))
        exact_key = json.dumps([record.get(field) for field in exact_key_fields], sort_keys=True)
        if record_id in seen_ids:
            findings.append(DuplicateFinding(record_id, record_id, DuplicateClass.EXACT_DUPLICATE))
        elif exact_key in seen_keys:
            findings.append(
                DuplicateFinding(record_id, seen_keys[exact_key], DuplicateClass.LIKELY_DUPLICATE)
            )
        else:
            findings.append(DuplicateFinding(record_id, None, DuplicateClass.NOT_DUPLICATE))
        seen_ids.add(record_id)
        seen_keys.setdefault(exact_key, record_id)
    return findings


def nutrition_outlier_flags(record: Mapping[str, Any]) -> list[str]:
    flags: list[str] = []
    thresholds = {
        "energy_kcal": (900.0, 1000.0),
        "sodium_mg": (5000.0, 100000.0),
        "protein_g": (100.0, 150.0),
        "carbohydrates_g": (100.0, 150.0),
        "total_fat_g": (100.0, 150.0),
    }
    for field, (suspect, invalid) in thresholds.items():
        value_record = record.get(field)
        if not isinstance(value_record, Mapping):
            continue
        value = value_record.get("normalized_value")
        if not isinstance(value, int | float):
            continue
        if value > invalid:
            flags.append(f"INVALID:{field}>{invalid:g}")
        elif value > suspect:
            flags.append(f"SUSPECT_OUTLIER:{field}>{suspect:g}")
    return flags


def transparent_quality_score(
    *,
    schema_compliance: float,
    provenance: float,
    licensing: float,
    completeness: float,
    uniqueness: float,
    unit_validity: float,
) -> float:
    components = {
        "schema_compliance": schema_compliance,
        "provenance": provenance,
        "licensing": licensing,
        "completeness": completeness,
        "uniqueness": uniqueness,
        "unit_validity": unit_validity,
    }
    if any(value < 0 or value > 1 for value in components.values()):
        raise ValueError("quality components must be between 0 and 1")
    return round(sum(components[name] * weight for name, weight in QUALITY_WEIGHTS.items()), 2)


def missingness(records: list[Mapping[str, Any]], fields: Iterable[str]) -> dict[str, float]:
    if not records:
        return {field: 0.0 for field in fields}
    return {
        field: round(
            sum(record.get(field) is None or record.get(field) == "" for record in records)
            / len(records),
            6,
        )
        for field in fields
    }


def distribution(records: Iterable[Mapping[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(str(record.get(field, "UNKNOWN")) for record in records)
    return dict(sorted(counts.items()))
