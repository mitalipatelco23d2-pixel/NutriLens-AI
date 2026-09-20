"""Deterministic lookup over the unverified teammate-provided M5 CSV."""

from __future__ import annotations

import csv
import hashlib
import re
import threading
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any


REQUIRED_COLUMNS = (
    "ingredient",
    "aliases",
    "category",
    "concern_level",
    "concern_type",
    "reason",
    "possible_effect",
    "usage",
    "avoid_for",
    "source",
    "product_count",
    "long_term_risk",
)


class KnowledgeBaseUnavailableError(Exception):
    """The optional M5 dataset is missing, malformed, or not the reviewed file."""

    def __init__(self, message: str, *, actual_sha256: str | None = None) -> None:
        super().__init__(message)
        self.actual_sha256 = actual_sha256


def _normalized_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _e_number_key(value: str) -> str | None:
    compact = re.sub(r"[^a-z0-9]", "", value.casefold())
    match = re.fullmatch(r"(?:ins|e)?(\d{3,4}[a-z]?(?:i{1,3}|iv)?)", compact)
    if match is None:
        return None
    return f"e{match.group(1)}"


def _aliases(row: dict[str, str]) -> list[str]:
    values = [row["ingredient"]]
    values.extend(
        item.strip()
        for item in re.split(r"[,;|]", row.get("aliases", ""))
        if item.strip()
    )
    return values


class KnowledgeBaseService:
    """Lazy CSV lookup using only exact normalized keys and explicit aliases."""

    matching_policy = "normalized_exact_alias_and_e_number_only"

    def __init__(
        self,
        path: Path,
        *,
        expected_sha256: str | None,
    ) -> None:
        self.path = Path(path)
        self.expected_sha256 = expected_sha256.lower() if expected_sha256 else None
        self._lock = threading.Lock()
        self._loaded: tuple[
            list[dict[str, str]],
            dict[str, list[dict[str, str]]],
            dict[str, list[dict[str, str]]],
            str,
        ] | None = None

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _add_index(
        index: dict[str, list[dict[str, str]]],
        key: str | None,
        row: dict[str, str],
    ) -> None:
        if key and row not in index[key]:
            index[key].append(row)

    def _load(
        self,
    ) -> tuple[
        list[dict[str, str]],
        dict[str, list[dict[str, str]]],
        dict[str, list[dict[str, str]]],
        str,
    ]:
        if self._loaded is not None:
            return self._loaded
        with self._lock:
            if self._loaded is not None:
                return self._loaded
            if not self.path.is_file():
                raise KnowledgeBaseUnavailableError(
                    "The optional M5 knowledge-base CSV is unavailable."
                )

            actual_sha256 = self._digest(self.path)
            if self.expected_sha256 and actual_sha256 != self.expected_sha256:
                raise KnowledgeBaseUnavailableError(
                    "The M5 knowledge-base CSV failed its SHA-256 identity check.",
                    actual_sha256=actual_sha256,
                )

            try:
                with self.path.open("r", encoding="utf-8-sig", newline="") as source:
                    reader = csv.DictReader(source, strict=True)
                    fieldnames = reader.fieldnames or []
                    if len(fieldnames) != len(set(fieldnames)) or set(fieldnames) != set(
                        REQUIRED_COLUMNS
                    ):
                        raise KnowledgeBaseUnavailableError(
                            "The M5 knowledge-base CSV schema is invalid.",
                            actual_sha256=actual_sha256,
                        )
                    rows: list[dict[str, str]] = []
                    for line_number, raw_row in enumerate(reader, start=2):
                        if None in raw_row or any(value is None for value in raw_row.values()):
                            raise KnowledgeBaseUnavailableError(
                                f"The M5 knowledge-base CSV has a malformed row at line {line_number}.",
                                actual_sha256=actual_sha256,
                            )
                        row = {key: value.strip() for key, value in raw_row.items()}
                        if not row["ingredient"]:
                            raise KnowledgeBaseUnavailableError(
                                f"The M5 knowledge-base CSV has no ingredient at line {line_number}.",
                                actual_sha256=actual_sha256,
                            )
                        rows.append(row)
            except (OSError, UnicodeError, csv.Error) as exc:
                raise KnowledgeBaseUnavailableError(
                    "The M5 knowledge-base CSV could not be parsed.",
                    actual_sha256=actual_sha256,
                ) from exc

            if not rows:
                raise KnowledgeBaseUnavailableError(
                    "The M5 knowledge-base CSV contains no rows.",
                    actual_sha256=actual_sha256,
                )

            primary: dict[str, list[dict[str, str]]] = defaultdict(list)
            aliases: dict[str, list[dict[str, str]]] = defaultdict(list)
            for row in rows:
                ingredient = row["ingredient"]
                self._add_index(primary, _normalized_text(ingredient), row)
                self._add_index(primary, _e_number_key(ingredient), row)
                for alias in _aliases(row)[1:]:
                    self._add_index(aliases, _normalized_text(alias), row)
                    self._add_index(aliases, _e_number_key(alias), row)

            self._loaded = (rows, dict(primary), dict(aliases), actual_sha256)
            return self._loaded

    def _metadata(
        self,
        *,
        actual_sha256: str | None,
        row_count: int | None,
    ) -> dict[str, Any]:
        return {
            "dataset_file": self.path.name,
            "sha256": actual_sha256,
            "expected_sha256": self.expected_sha256,
            "hash_matches_reviewed_file": bool(
                actual_sha256
                and self.expected_sha256
                and actual_sha256 == self.expected_sha256
            ),
            "row_count": row_count,
            "matching_policy": self.matching_policy,
            "trust": "unverified_teammate_provided_dataset",
            "citation_status": "source_labels_not_independently_verified",
        }

    @staticmethod
    def _select(
        index: dict[str, list[dict[str, str]]], key: str | None
    ) -> tuple[dict[str, str] | None, bool]:
        candidates = index.get(key or "", [])
        return (candidates[0], False) if len(candidates) == 1 else (None, len(candidates) > 1)

    @staticmethod
    def _match_detail(
        input_ingredient: str,
        row: dict[str, str],
        matched_by: str,
    ) -> dict[str, Any]:
        return {
            "input_ingredient": input_ingredient,
            "matched_ingredient": row["ingredient"],
            "matched_by": matched_by,
            "aliases": row["aliases"],
            "category": row["category"],
            "concern_level": row["concern_level"],
            "concern_type": row["concern_type"],
            "dataset_reason": row["reason"],
            "usage": row["usage"],
            "dataset_source_label": row["source"],
            "citation_verified": False,
        }

    def lookup(self, ingredients: Any) -> dict[str, Any]:
        if not isinstance(ingredients, (list, tuple)) or any(
            not isinstance(item, str) for item in ingredients
        ):
            return {
                "status": "unavailable",
                "matched": [],
                "unmatched": [],
                "summary": {"total": 0, "matched": 0, "unmatched": 0},
                "dataset": self._metadata(actual_sha256=None, row_count=None),
                "warnings": ["M5 knowledge lookup requires an ingredient string list."],
            }

        cleaned = [item.strip() for item in ingredients if item.strip()]
        try:
            rows, primary, aliases, actual_sha256 = self._load()
        except KnowledgeBaseUnavailableError as exc:
            return {
                "status": "unavailable",
                "matched": [],
                "unmatched": [
                    {
                        "input_ingredient": item,
                        "normalized": _normalized_text(item),
                        "reason": "dataset_unavailable",
                    }
                    for item in cleaned
                ],
                "summary": {
                    "total": len(cleaned),
                    "matched": 0,
                    "unmatched": len(cleaned),
                },
                "dataset": self._metadata(
                    actual_sha256=exc.actual_sha256, row_count=None
                ),
                "warnings": [str(exc)],
            }

        matched: list[dict[str, Any]] = []
        unmatched: list[dict[str, Any]] = []
        for ingredient in cleaned:
            normalized = _normalized_text(ingredient)
            e_number = _e_number_key(ingredient)
            row, ambiguous = self._select(primary, normalized)
            matched_by = "exact"
            if row is None and e_number:
                row, e_ambiguous = self._select(primary, e_number)
                ambiguous = ambiguous or e_ambiguous
                matched_by = "e_number"
            if row is None:
                row, alias_ambiguous = self._select(aliases, normalized)
                ambiguous = ambiguous or alias_ambiguous
                matched_by = "alias"
            if row is None and e_number:
                row, e_alias_ambiguous = self._select(aliases, e_number)
                ambiguous = ambiguous or e_alias_ambiguous
                matched_by = "e_number"

            if row is None:
                unmatched.append(
                    {
                        "input_ingredient": ingredient,
                        "normalized": normalized,
                        "reason": "ambiguous_alias" if ambiguous else "not_found",
                    }
                )
            else:
                matched.append(self._match_detail(ingredient, row, matched_by))

        return {
            "status": "available",
            "matched": matched,
            "unmatched": unmatched,
            "summary": {
                "total": len(cleaned),
                "matched": len(matched),
                "unmatched": len(unmatched),
            },
            "dataset": self._metadata(
                actual_sha256=actual_sha256, row_count=len(rows)
            ),
            "warnings": [],
        }
