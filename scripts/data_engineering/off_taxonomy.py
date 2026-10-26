"""Streaming parser for official Open Food Facts taxonomy source files."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from scripts.data_engineering.normalization import normalize_display_text, validate_unicode_text
from scripts.data_engineering.quarantine import Quarantine
from scripts.data_engineering.schemas import LocalizedText, TaxonomyRecord
from scripts.data_engineering.source_registry import SourceInfo

LANGUAGE_LINE = re.compile(r"^([a-z]{2,3}(?:_[A-Z]{2})?):\s*(.+)$")
PARENT_LINE = re.compile(r"^<\s*([a-z]{2,3}(?:_[A-Z]{2})?):\s*(.+)$")
EXTERNAL_CODE = re.compile(r"\b(?:E|INS)[\s-]?(\d{3,4}[a-zA-Z]?)\b", re.IGNORECASE)
ADDITIVE_CLASS_LINE = re.compile(r"^additives_classes:[a-z]{2,3}(?:_[A-Z]{2})?:\s*(.+)$")


def slugify(value: str) -> str:
    normalized = normalize_display_text(value).casefold()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    if slug:
        return slug
    return "unicode-" + value.encode("utf-8").hex()[:32]


def _blocks(path: Path) -> Iterable[tuple[int, list[str]]]:
    block: list[str] = []
    start_line = 1
    with path.open(encoding="utf-8-sig") as source:
        for line_number, raw in enumerate(source, start=1):
            line = raw.strip()
            if not line:
                if block:
                    yield start_line, block
                    block = []
                start_line = line_number + 1
                continue
            if line.startswith("#"):
                continue
            if not block:
                start_line = line_number
            block.append(line)
    if block:
        yield start_line, block


def parse_taxonomy(
    source: SourceInfo,
    taxonomy_type: str,
    *,
    limit: int | None = None,
    quarantine: Quarantine | None = None,
) -> Iterable[TaxonomyRecord]:
    emitted = 0
    seen: set[str] = set()
    for start_line, lines in _blocks(source.path):
        names: list[LocalizedText] = []
        synonyms: list[LocalizedText] = []
        parent_names: list[str] = []
        functional_categories: list[str] = []
        for line in lines:
            additive_class = ADDITIVE_CLASS_LINE.match(line)
            if additive_class:
                functional_categories.extend(
                    normalize_display_text(value.split(":", maxsplit=1)[-1])
                    for value in additive_class.group(1).split(",")
                    if value.strip()
                )
                continue
            parent = PARENT_LINE.match(line)
            if parent:
                parent_names.extend(
                    normalize_display_text(value)
                    for value in parent.group(2).split(",")
                    if value.strip()
                )
                continue
            label = LANGUAGE_LINE.match(line)
            if not label:
                continue
            language = label.group(1).replace("_", "-").lower()
            values = [normalize_display_text(value) for value in label.group(2).split(",")]
            values = [value for value in values if value]
            if not values or not all(validate_unicode_text(value) for value in values):
                if quarantine is not None:
                    quarantine.add(
                        source_record_id=f"line-{start_line}",
                        stage="OFF_TAXONOMY_PARSE",
                        rule="VALID_UTF8_TEXT",
                        reason="empty or corrupted localized label",
                        snapshot={"line": line[:500]},
                    )
                continue
            names.append(LocalizedText(language=language, text=values[0]))
            synonyms.extend(LocalizedText(language=language, text=value) for value in values[1:])
        if not names:
            continue
        english = next((item.text for item in names if item.language == "en"), names[0].text)
        taxonomy_id = f"off:{taxonomy_type}:{slugify(english)}"
        if taxonomy_id in seen:
            if quarantine is not None:
                quarantine.add(
                    source_record_id=f"line-{start_line}",
                    stage="OFF_TAXONOMY_PARSE",
                    rule="UNIQUE_TAXONOMY_ID",
                    reason=f"duplicate normalized taxonomy ID {taxonomy_id}",
                    snapshot={"canonical_name": english},
                )
            continue
        seen.add(taxonomy_id)
        code_match = EXTERNAL_CODE.search(english) if taxonomy_type == "additive" else None
        yield TaxonomyRecord(
            taxonomy_id=taxonomy_id,
            taxonomy_type=taxonomy_type,
            canonical_name=english,
            localized_names=names,
            synonyms=synonyms,
            parent_ids=[f"off:{taxonomy_type}:{slugify(parent)}" for parent in parent_names],
            external_code=f"E{code_match.group(1).upper()}" if code_match else None,
            functional_category="; ".join(functional_categories) or None,
            source_line=start_line,
            lineage=source.lineage(f"line-{start_line}"),
        )
        emitted += 1
        if limit is not None and emitted >= limit:
            return
