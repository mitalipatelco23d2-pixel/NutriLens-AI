"""Local OFF taxonomy loading for the R4 Ingredient Intelligence Engine."""

from __future__ import annotations

import gzip
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IngredientTaxonomyEntry:
    """Minimal governed ingredient taxonomy record used by R4."""

    taxonomy_id: str
    canonical_name: str
    english_names: tuple[str, ...]
    english_synonyms: tuple[str, ...]
    parent_ids: tuple[str, ...]
    source_dataset: str
    source_version: str


def load_ingredient_taxonomy(path: str | Path) -> list[IngredientTaxonomyEntry]:
    """Load valid ingredient records from an R2 JSONL taxonomy artifact."""

    source_path = Path(path)

    if not source_path.is_file():
        raise FileNotFoundError(f"Ingredient taxonomy not found: {source_path}")

    entries: list[IngredientTaxonomyEntry] = []

    with source_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()

            if not stripped:
                continue

            try:
                record: dict[str, Any] = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in ingredient taxonomy at line {line_number}"
                ) from exc

            if record.get("record_status") != "VALID":
                continue

            if record.get("taxonomy_type") != "ingredient":
                continue

            taxonomy_id = str(record.get("taxonomy_id", "")).strip()
            canonical_name = str(record.get("canonical_name", "")).strip()

            if not taxonomy_id or not canonical_name:
                continue

            english_names = _english_texts(record.get("localized_names", []))
            english_synonyms = _english_texts(record.get("synonyms", []))

            lineage = record.get("lineage") or {}

            entries.append(
                IngredientTaxonomyEntry(
                    taxonomy_id=taxonomy_id,
                    canonical_name=canonical_name,
                    english_names=english_names,
                    english_synonyms=english_synonyms,
                    parent_ids=tuple(
                        str(value) for value in record.get("parent_ids", []) if str(value).strip()
                    ),
                    source_dataset=str(lineage.get("source_dataset", "")),
                    source_version=str(lineage.get("source_version", "")),
                )
            )

    return entries


def _english_texts(values: object) -> tuple[str, ...]:
    """Extract unique English text values from OFF localized-name structures."""

    if not isinstance(values, list):
        return ()

    results: list[str] = []

    for item in values:
        if not isinstance(item, dict):
            continue

        if item.get("language") != "en":
            continue

        text = str(item.get("text", "")).strip()

        if text and text not in results:
            results.append(text)

    return tuple(results)


def normalize_lookup_text(value: str) -> str:
    """Normalize text for conservative exact taxonomy matching."""

    return " ".join(value.casefold().strip().split())


def build_ingredient_lookup(
    entries: list[IngredientTaxonomyEntry],
) -> dict[str, IngredientTaxonomyEntry]:
    """Build an exact-match lookup from canonical names and English aliases."""

    lookup: dict[str, IngredientTaxonomyEntry] = {}

    for entry in entries:
        candidates = (
            entry.canonical_name,
            *entry.english_names,
            *entry.english_synonyms,
        )

        for candidate in candidates:
            key = normalize_lookup_text(candidate)

            if key and key not in lookup:
                lookup[key] = entry

    return lookup


def match_ingredient_exact(
    value: str,
    lookup: dict[str, IngredientTaxonomyEntry],
) -> IngredientTaxonomyEntry | None:
    """Return an exact normalized OFF taxonomy match, if one exists."""

    key = normalize_lookup_text(value)

    if not key:
        return None

    return lookup.get(key)


@dataclass(frozen=True)
class AdditiveTaxonomyEntry:
    """Minimal governed additive taxonomy record used by R4."""

    taxonomy_id: str
    canonical_name: str
    external_code: str | None
    functional_category: str | None
    english_names: tuple[str, ...]
    english_synonyms: tuple[str, ...]
    parent_ids: tuple[str, ...]
    source_dataset: str
    source_version: str


def load_additive_taxonomy(path: str | Path) -> list[AdditiveTaxonomyEntry]:
    """Load valid additive records from an R2 JSONL taxonomy artifact."""

    source_path = Path(path)

    if not source_path.is_file():
        raise FileNotFoundError(f"Additive taxonomy not found: {source_path}")

    entries: list[AdditiveTaxonomyEntry] = []

    with source_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()

            if not stripped:
                continue

            try:
                record: dict[str, Any] = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in additive taxonomy at line {line_number}"
                ) from exc

            if record.get("record_status") != "VALID":
                continue

            if record.get("taxonomy_type") != "additive":
                continue

            taxonomy_id = str(record.get("taxonomy_id", "")).strip()
            canonical_name = str(record.get("canonical_name", "")).strip()

            if not taxonomy_id or not canonical_name:
                continue

            external_code_raw = record.get("external_code")
            functional_category_raw = record.get("functional_category")

            lineage = record.get("lineage") or {}

            entries.append(
                AdditiveTaxonomyEntry(
                    taxonomy_id=taxonomy_id,
                    canonical_name=canonical_name,
                    external_code=(
                        str(external_code_raw).strip() if external_code_raw is not None else None
                    ),
                    functional_category=(
                        str(functional_category_raw).strip()
                        if functional_category_raw is not None
                        else None
                    ),
                    english_names=_english_texts(record.get("localized_names", [])),
                    english_synonyms=_english_texts(record.get("synonyms", [])),
                    parent_ids=tuple(
                        str(value) for value in record.get("parent_ids", []) if str(value).strip()
                    ),
                    source_dataset=str(lineage.get("source_dataset", "")),
                    source_version=str(lineage.get("source_version", "")),
                )
            )

    return entries


def build_additive_lookup(
    entries: list[AdditiveTaxonomyEntry],
) -> dict[str, AdditiveTaxonomyEntry]:
    """Build exact-match lookup from additive codes and English aliases."""

    lookup: dict[str, AdditiveTaxonomyEntry] = {}

    for entry in entries:
        candidates: list[str] = [
            entry.canonical_name,
            *entry.english_names,
            *entry.english_synonyms,
        ]

        if entry.external_code:
            candidates.append(entry.external_code)

        for candidate in candidates:
            key = normalize_lookup_text(candidate)

            if key and key not in lookup:
                lookup[key] = entry

    return lookup


def match_additive_exact(
    value: str,
    lookup: dict[str, AdditiveTaxonomyEntry],
) -> AdditiveTaxonomyEntry | None:
    """Return an exact normalized additive taxonomy match."""

    key = normalize_lookup_text(value)

    if not key:
        return None

    return lookup.get(key)


@dataclass(frozen=True)
class AllergenTaxonomyEntry:
    """Minimal governed allergen taxonomy record used by R4."""

    taxonomy_id: str
    canonical_name: str
    english_names: tuple[str, ...]
    english_synonyms: tuple[str, ...]
    parent_ids: tuple[str, ...]
    source_dataset: str
    source_version: str


def load_allergen_taxonomy(path: str | Path) -> list[AllergenTaxonomyEntry]:
    """Load valid allergen records from an R2 JSONL taxonomy artifact."""

    source_path = Path(path)

    if not source_path.is_file():
        raise FileNotFoundError(f"Allergen taxonomy not found: {source_path}")

    entries: list[AllergenTaxonomyEntry] = []

    with source_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()

            if not stripped:
                continue

            try:
                record: dict[str, Any] = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON in allergen taxonomy at line {line_number}"
                ) from exc

            if record.get("record_status") != "VALID":
                continue

            if record.get("taxonomy_type") != "allergen":
                continue

            taxonomy_id = str(record.get("taxonomy_id", "")).strip()
            canonical_name = str(record.get("canonical_name", "")).strip()

            if not taxonomy_id or not canonical_name:
                continue

            # The OFF taxonomy contains a special "none" record.
            # It must not be treated as a real allergen.
            if canonical_name.casefold() == "none":
                continue

            lineage = record.get("lineage") or {}

            entries.append(
                AllergenTaxonomyEntry(
                    taxonomy_id=taxonomy_id,
                    canonical_name=canonical_name,
                    english_names=_english_texts(record.get("localized_names", [])),
                    english_synonyms=_english_texts(record.get("synonyms", [])),
                    parent_ids=tuple(
                        str(value) for value in record.get("parent_ids", []) if str(value).strip()
                    ),
                    source_dataset=str(lineage.get("source_dataset", "")),
                    source_version=str(lineage.get("source_version", "")),
                )
            )

    return entries


def build_allergen_lookup(
    entries: list[AllergenTaxonomyEntry],
) -> dict[str, AllergenTaxonomyEntry]:
    """Build exact-match lookup from allergen names and English aliases."""

    lookup: dict[str, AllergenTaxonomyEntry] = {}

    for entry in entries:
        candidates = (
            entry.canonical_name,
            *entry.english_names,
            *entry.english_synonyms,
        )

        for candidate in candidates:
            key = normalize_lookup_text(candidate)

            if key and key not in lookup:
                lookup[key] = entry

    return lookup


def match_allergen_exact(
    value: str,
    lookup: dict[str, AllergenTaxonomyEntry],
) -> AllergenTaxonomyEntry | None:
    """Return an exact normalized allergen taxonomy match."""

    key = normalize_lookup_text(value)

    if not key:
        return None

    return lookup.get(key)


@dataclass(frozen=True)
class NovaTaxonomyEntry:
    """Minimal governed NOVA taxonomy record used by R4."""

    taxonomy_id: str
    canonical_name: str
    group_number: int | None
    english_names: tuple[str, ...]
    english_synonyms: tuple[str, ...]
    source_dataset: str
    source_version: str


def load_nova_taxonomy(path: str | Path) -> list[NovaTaxonomyEntry]:
    """Load valid NOVA group records from an R2 JSONL taxonomy artifact."""

    source_path = Path(path)

    if not source_path.is_file():
        raise FileNotFoundError(f"NOVA taxonomy not found: {source_path}")

    entries: list[NovaTaxonomyEntry] = []

    with source_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()

            if not stripped:
                continue

            try:
                record: dict[str, Any] = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON in NOVA taxonomy at line {line_number}") from exc

            if record.get("record_status") != "VALID":
                continue

            if record.get("taxonomy_type") != "nova_group":
                continue

            taxonomy_id = str(record.get("taxonomy_id", "")).strip()
            canonical_name = str(record.get("canonical_name", "")).strip()

            if not taxonomy_id or not canonical_name:
                continue

            group_number = _extract_nova_group_number(canonical_name)

            lineage = record.get("lineage") or {}

            entries.append(
                NovaTaxonomyEntry(
                    taxonomy_id=taxonomy_id,
                    canonical_name=canonical_name,
                    group_number=group_number,
                    english_names=_english_texts(record.get("localized_names", [])),
                    english_synonyms=_english_texts(record.get("synonyms", [])),
                    source_dataset=str(lineage.get("source_dataset", "")),
                    source_version=str(lineage.get("source_version", "")),
                )
            )

    return entries


def _extract_nova_group_number(value: str) -> int | None:
    """Extract NOVA group number 1-4 from a canonical NOVA label."""

    match = re.match(r"^\s*([1-4])\s*-\s*", value)

    if match is None:
        return None

    return int(match.group(1))


def build_nova_lookup(
    entries: list[NovaTaxonomyEntry],
) -> dict[str, NovaTaxonomyEntry]:
    """Build exact-match lookup for governed NOVA labels and aliases."""

    lookup: dict[str, NovaTaxonomyEntry] = {}

    for entry in entries:
        candidates = (
            entry.canonical_name,
            *entry.english_names,
            *entry.english_synonyms,
        )

        for candidate in candidates:
            key = normalize_lookup_text(candidate)

            if key and key not in lookup:
                lookup[key] = entry

    return lookup


def get_nova_group(
    entries: list[NovaTaxonomyEntry],
    group_number: int,
) -> NovaTaxonomyEntry | None:
    """Return the governed NOVA record for group 1-4."""

    if group_number not in {1, 2, 3, 4}:
        return None

    for entry in entries:
        if entry.group_number == group_number:
            return entry

    return None


def is_sodium_bearing_text(value: str) -> bool:
    """Return True when text explicitly names a sodium-bearing compound."""

    normalized = normalize_lookup_text(value)

    sodium_pattern = re.compile(
        r"\b(?:sodium|monosodium|disodium|trisodium)\b",
        re.IGNORECASE,
    )

    return sodium_pattern.search(normalized) is not None


def build_sodium_additive_lookup(
    entries: list[AdditiveTaxonomyEntry],
) -> dict[str, AdditiveTaxonomyEntry]:
    """Build aliases only for additives explicitly identified as sodium-bearing."""

    lookup: dict[str, AdditiveTaxonomyEntry] = {}

    for entry in entries:
        candidates = (
            entry.canonical_name,
            *entry.english_names,
            *entry.english_synonyms,
        )

        sodium_candidates = [
            candidate for candidate in candidates if is_sodium_bearing_text(candidate)
        ]

        if not sodium_candidates:
            continue

        for candidate in candidates:
            key = normalize_lookup_text(candidate)

            if key and key not in lookup:
                lookup[key] = entry

    return lookup


def build_ingredient_id_map(
    entries: list[IngredientTaxonomyEntry],
) -> dict[str, IngredientTaxonomyEntry]:
    """Build taxonomy_id -> ingredient entry lookup."""

    return {entry.taxonomy_id: entry for entry in entries}


def ingredient_has_ancestor(
    entry: IngredientTaxonomyEntry,
    ancestor_id: str,
    id_map: dict[str, IngredientTaxonomyEntry],
) -> bool:
    """Return True when an ingredient belongs under a given taxonomy ancestor."""

    visited: set[str] = set()
    stack = list(entry.parent_ids)

    while stack:
        parent_id = stack.pop()

        if parent_id == ancestor_id:
            return True

        if parent_id in visited:
            continue

        visited.add(parent_id)

        parent = id_map.get(parent_id)

        if parent is not None:
            stack.extend(parent.parent_ids)

    return False


def load_runtime_bundle(
    path: str | Path,
) -> tuple[
    list[IngredientTaxonomyEntry],
    list[AdditiveTaxonomyEntry],
    list[AllergenTaxonomyEntry],
    list[NovaTaxonomyEntry],
]:
    """Load the compact, provenance-preserving public runtime taxonomy bundle."""

    with gzip.open(Path(path), "rt", encoding="utf-8") as handle:
        payload: dict[str, Any] = json.load(handle)
    if payload.get("bundle_version") != "r4-runtime-v0.1.0":
        raise ValueError("Unsupported R4 runtime bundle version.")
    sections = payload["sections"]
    ingredients = [
        IngredientTaxonomyEntry(
            taxonomy_id=item["taxonomy_id"],
            canonical_name=item["canonical_name"],
            english_names=tuple(item["english_names"]),
            english_synonyms=tuple(item["english_synonyms"]),
            parent_ids=tuple(item["parent_ids"]),
            source_dataset=item["source_dataset"],
            source_version=item["source_version"],
        )
        for item in sections["ingredients"]
    ]
    additives = [
        AdditiveTaxonomyEntry(
            taxonomy_id=item["taxonomy_id"],
            canonical_name=item["canonical_name"],
            external_code=item["external_code"],
            functional_category=item["functional_category"],
            english_names=tuple(item["english_names"]),
            english_synonyms=tuple(item["english_synonyms"]),
            parent_ids=tuple(item["parent_ids"]),
            source_dataset=item["source_dataset"],
            source_version=item["source_version"],
        )
        for item in sections["additives"]
    ]
    allergens = [
        AllergenTaxonomyEntry(
            taxonomy_id=item["taxonomy_id"],
            canonical_name=item["canonical_name"],
            english_names=tuple(item["english_names"]),
            english_synonyms=tuple(item["english_synonyms"]),
            parent_ids=tuple(item["parent_ids"]),
            source_dataset=item["source_dataset"],
            source_version=item["source_version"],
        )
        for item in sections["allergens"]
        if item["canonical_name"].casefold() != "none"
    ]
    nova = [
        NovaTaxonomyEntry(
            taxonomy_id=item["taxonomy_id"],
            canonical_name=item["canonical_name"],
            group_number=_extract_nova_group_number(item["canonical_name"]),
            english_names=tuple(item["english_names"]),
            english_synonyms=tuple(item["english_synonyms"]),
            source_dataset=item["source_dataset"],
            source_version=item["source_version"],
        )
        for item in sections["nova"]
    ]
    return ingredients, additives, allergens, nova
