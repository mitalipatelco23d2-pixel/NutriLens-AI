from __future__ import annotations

import re
import unicodedata
from typing import Protocol


STOP_LABEL = re.compile(
    r"\b(?:nutrition(?:al)?\s+(?:facts|information)|allergen(?:s| information)?|"
    r"may contain|best before|use by|expiry|production date|batch|lot(?:\s+no)?|"
    r"net (?:weight|wt)|storage instructions?|store in|directions?|preparation|"
    r"prepared by|produced (?:for|by)|manufactur(?:ed|er)|packed by|marketed by|"
    r"imported by|importer|distributed by|country of origin)\b",
    re.I,
)
INGREDIENT_START = re.compile(r"\b[i1l]ngredients?\s*[:;\-]?\s*", re.I)


class IngredientExtractor(Protocol):
    """Interface Member 1 can implement without changing pipeline code."""

    def extract(self, text: str) -> list[str]: ...


def extract_explicit_allergens(text: str) -> list[str]:
    """Extract only directly labelled allergen/contains statements."""
    normalized = unicodedata.normalize("NFKC", text).replace("\u00a0", " ")
    allergens: list[str] = []
    for line in normalized.splitlines():
        match = re.search(
            r"\b(?:allergens?\s*[:;\-]?\s*(?:contains?\s+)?|contains?\s+)"
            r"(?P<items>[A-Za-z][A-Za-z ,/&-]{1,80})",
            line,
            re.I,
        )
        if not match:
            continue
        items = re.split(r"\s*(?:,|/|&|\band\b)\s*", match.group("items"), flags=re.I)
        for item in items:
            value = normalize_ingredient_name(item)
            if value and value.casefold() not in {existing.casefold() for existing in allergens}:
                allergens.append(value.title())
    return allergens


def normalize_ingredient_name(name: str) -> str:
    name = unicodedata.normalize("NFKC", name).strip().strip(". ;:-")
    name = re.sub(r"\s+", " ", name)
    return name


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


def extract_ingredients_from_text(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", text).replace("—", "-").replace("\u00a0", " ")
    start = INGREDIENT_START.search(normalized)
    if not start:
        return []

    remainder = normalized[start.end() :]
    source_lines = remainder.splitlines() or [remainder]
    selected_lines: list[str] = []
    bracket_depth = 0
    for line in source_lines:
        line = line.strip()
        if not line:
            if selected_lines:
                break
            continue
        if selected_lines and INGREDIENT_START.search(line):
            break
        transition = STOP_LABEL.search(line)
        stop_after_line = transition is not None
        if transition:
            line = line[: transition.start()].strip()
            if not line:
                break
        if selected_lines:
            previous = selected_lines[-1].rstrip()
            starts_like_continuation = bool(
                line[:1].islower()
                or previous.endswith((",", ";", ":"))
                or bracket_depth > 0
            )
            if previous.endswith(".") or not starts_like_continuation:
                break
        selected_lines.append(line)
        bracket_depth += line.count("(") + line.count("[")
        bracket_depth -= line.count(")") + line.count("]")
        bracket_depth = max(0, bracket_depth)
        if stop_after_line:
            break
    block = " ".join(selected_lines)
    singular_label = start.group(0).casefold().startswith("ingredient:") or bool(
        re.match(r"ingredient\s*[-:]", start.group(0), re.I)
    )
    if singular_label:
        block = block.splitlines()[0]
        block = re.split(r"[.;]|\s{3,}", block, maxsplit=1)[0]
        block = re.split(
            r"\s+\b(?:is|are|was|were|contains|manufactured|packed|marketed)\b\s+",
            block,
            maxsplit=1,
            flags=re.I,
        )[0]
    stop = STOP_LABEL.search(block)
    if stop:
        block = block[: stop.start()]
    block = re.sub(r"\s*\n\s*", " ", block).strip()
    if not block:
        return []

    ingredients: list[str] = []
    for raw_item in _split_top_level(block):
        ingredient = normalize_ingredient_name(raw_item)
        if ingredient and ingredient.casefold() not in {item.casefold() for item in ingredients}:
            ingredients.append(ingredient)
    return ingredients


def normalize_ingredient_list(ingredients: list[str]) -> list[str]:
    normalized: list[str] = []
    for ingredient in ingredients:
        value = normalize_ingredient_name(ingredient)
        if value and value.casefold() not in {item.casefold() for item in normalized}:
            normalized.append(value)
    return normalized


class FallbackIngredientExtractor:
    """Basic parser used until Member 1 supplies the final NLP implementation."""

    def extract(self, text: str) -> list[str]:
        return extract_ingredients_from_text(text)
