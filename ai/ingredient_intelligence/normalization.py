"""Ingredient text normalization for the R4 Ingredient Intelligence Engine."""

from __future__ import annotations

import re
import unicodedata

PREFIX_PATTERN = re.compile(
    r"^\s*(ingredients?|ingredient list)\s*[:\-]\s*",
    re.IGNORECASE,
)

WHITESPACE_PATTERN = re.compile(r"\s+")
SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([,;:)\]])")
SPACE_AFTER_OPEN = re.compile(r"([(\[])\s+")
MULTI_SEPARATOR = re.compile(r"[,;]\s*[,;]+")


def normalize_ingredient_text(raw_text: str) -> str:
    """Normalize OCR ingredient text without changing ingredient meaning."""

    text = unicodedata.normalize("NFKC", raw_text or "")
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    text = PREFIX_PATTERN.sub("", text)
    text = WHITESPACE_PATTERN.sub(" ", text)
    text = SPACE_BEFORE_PUNCTUATION.sub(r"\1", text)
    text = SPACE_AFTER_OPEN.sub(r"\1", text)
    text = MULTI_SEPARATOR.sub(",", text)

    return text.strip(" ,;")
