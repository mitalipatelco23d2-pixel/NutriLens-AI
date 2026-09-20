from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


def normalize_ocr_text(text: str) -> str:
    """Normalize layout noise without changing recognized letters or numbers."""
    normalized = unicodedata.normalize("NFKC", text).replace("\u00a0", " ")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in normalized.split("\n"))


def normalize_label_value(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().strip(". ;:-")
    return re.sub(r"\s+", " ", value)


def unique_casefold(values: Iterable[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if value and key not in seen:
            unique.append(value)
            seen.add(key)
    return unique
