from __future__ import annotations

import re
from dataclasses import dataclass, field

from .normalizer import normalize_label_value, normalize_ocr_text, unique_casefold


INGREDIENT_START = re.compile(
    r"\b(?P<label>ingre[\s-]*dients?|composition|made\s+with)\b[ \t]*[:;\-]?[ \t]*",
    re.I,
)
SECTION_STOP = re.compile(
    r"\b(?:nutrition(?:al)?\s+(?:facts|information)|allergen(?:s| information)?|"
    r"best before|use by|expiry|production date|batch|"
    r"lot(?:\s+no)?|net (?:weight|wt)|storage instructions?|store in|directions?|"
    r"preparation|prepared by|produced (?:for|by)|manufactur(?:ed|er)|packed by|"
    r"marketed by|imported by|importer|distributed by|country of origin)\b",
    re.I,
)
ALLERGEN_STOP = re.compile(
    r"\b(?:allergen(?:s| information)?|contains|may\s+contain)[ \t]*[:\-]",
    re.I,
)


@dataclass(frozen=True)
class IngredientExtraction:
    ingredients: list[str] = field(default_factory=list)
    section_detected: bool = False
    heading: str | None = None
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)


def _split_top_level(block: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    depth = 0
    for character in block:
        if character in "([":
            depth += 1
        elif character in ")]" and depth:
            depth -= 1
        if character in ",;" and depth == 0:
            value = "".join(current).strip()
            if value:
                items.append(value)
            current = []
        else:
            current.append(character)
    value = "".join(current).strip()
    if value:
        items.append(value)
    return items


def _stop_match(line: str) -> re.Match[str] | None:
    """Find a following label without treating nested ``contains`` as a section."""
    candidates = [
        match
        for pattern in (SECTION_STOP, ALLERGEN_STOP)
        for match in pattern.finditer(line)
        if line[: match.start()].count("(") == line[: match.start()].count(")")
        and line[: match.start()].count("[") == line[: match.start()].count("]")
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda match: match.start())


def _ingredient_block(lines: list[str]) -> str:
    """Preserve wrapped text, but recognize clear one-ingredient-per-line OCR lists."""
    bullet = re.compile(r"\s*[-*\u2022]\s+")
    if len(lines) >= 2 and all(bullet.match(line) for line in lines):
        return "; ".join(bullet.sub("", line, count=1) for line in lines)
    if len(lines) >= 3 and all(
        not re.search(r"[,;]$", line)
        for line in lines
    ):
        return "; ".join(lines)
    return " ".join(lines)


def extract_ingredient_section(text: str) -> IngredientExtraction:
    normalized = normalize_ocr_text(text).replace("—", "-")
    start = INGREDIENT_START.search(normalized)
    if not start:
        return IngredientExtraction()

    remainder = normalized[start.end() :]
    lines = remainder.splitlines()
    selected: list[str] = []
    depth = 0
    truncated = False
    singular = start.group("label").casefold() == "ingredient"

    for line in lines[:12]:
        line = line.strip()
        if not line:
            if selected:
                break
            continue
        if selected and INGREDIENT_START.search(line):
            break
        transition = _stop_match(line)
        if transition:
            line = line[: transition.start()].strip()
        if not line:
            break
        if selected and selected[-1].rstrip().endswith(".") and depth == 0:
            break
        selected.append(line)
        depth += line.count("(") + line.count("[")
        depth -= line.count(")") + line.count("]")
        depth = max(0, depth)
        if transition or singular:
            break
    block = _ingredient_block(selected).strip()
    if len(lines) > 12 or block.endswith((",", ";", "-")) or depth:
        truncated = True
    ingredients = unique_casefold(
        normalize_label_value(item) for item in _split_top_level(block)
    )
    warnings: list[str] = []
    if not ingredients:
        warnings.append("An ingredient section was detected, but no usable ingredients were extracted.")
    if truncated:
        warnings.append("The ingredient section may be truncated or incomplete.")
    return IngredientExtraction(
        ingredients=ingredients,
        section_detected=True,
        heading=start.group("label"),
        truncated=truncated,
        warnings=warnings,
    )


def extract_ingredients_from_text(text: str) -> list[str]:
    return extract_ingredient_section(text).ingredients


def normalize_ingredient_name(name: str) -> str:
    return normalize_label_value(name)


def normalize_ingredient_list(ingredients: list[str]) -> list[str]:
    return unique_casefold(normalize_label_value(item) for item in ingredients)
