from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

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
INGREDIENT_HEADING_ONLY = re.compile(
    r"^\s*(?:ingre[\s-]*dients?|composition|made\s+with)\s*[:;\-]?\s*$",
    re.I,
)
MAX_INGREDIENT_SECTION_LINES = 30
INGREDIENT_QUALITY_STATES = {"trusted", "partial", "untrusted", "absent"}
IngredientQualityState = Literal["trusted", "partial", "untrusted", "absent"]
CONTAMINATION_PATTERN = re.compile(
    r"\b(?:nutrition(?:al)?\s+(?:facts|information)|serving\s+size|"
    r"recommended\s+dietary\s+allowance|%\s*rda|net\s+(?:weight|wt|quantity)|"
    r"allergen(?:s| information)?|contains\s*[:\-]|best\s+before|use\s+by|"
    r"batch(?:\s+no)?|lot(?:\s+no)?|mrp|lic(?:ence)?\s*no|storage\s+instructions?|"
    r"prepared\s+by|produced\s+(?:for|by)|manufactur(?:ed|er)|packed\s+by|"
    r"marketed\s+by|imported\s+by|distributed\s+by|customer\s+care|"
    r"for\s+feedback|www\.|https?://)\b",
    re.I,
)
PROSE_PATTERN = re.compile(
    r"\b(?:is|are|was|were)\b[^.;]{0,80}\b(?:throughout|process|quality|"
    r"ensure[sd]?|achieve[sd]?|produced|manufactured)\b",
    re.I,
)
PRODUCT_SPECIFICATION_PATTERN = re.compile(
    r"(?:\b(?:snf|milk\s*fat)\b|\b\d+(?:[.,]\d+)?\s*%\s*(?:max(?:imum)?|min(?:imum)?)\b)",
    re.I,
)


@dataclass(frozen=True)
class IngredientExtraction:
    ingredients: list[str] = field(default_factory=list)
    section_detected: bool = False
    heading: str | None = None
    truncated: bool = False
    boundary_detected: bool = False
    quality_status: IngredientQualityState = "absent"
    quality_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def ingredient_quality_from_result(
    nlp_result: dict[str, Any],
) -> tuple[IngredientQualityState, list[str]]:
    """Read the M1 quality contract, defaulting missing evidence to safe abstention."""
    quality = nlp_result.get("ingredient_quality")
    if isinstance(quality, dict):
        status = quality.get("status")
        reasons = quality.get("reasons")
        if status in INGREDIENT_QUALITY_STATES:
            clean_reasons = (
                [str(item) for item in reasons if str(item).strip()]
                if isinstance(reasons, list)
                else []
            )
            return status, clean_reasons
    ingredients = nlp_result.get("ingredients")
    if not isinstance(ingredients, (list, tuple)) or not any(
        isinstance(item, str) and item.strip() for item in ingredients
    ):
        return "absent", ["No usable ingredient list was extracted."]
    return "untrusted", ["M1 did not provide ingredient-quality evidence."]


def trusted_ingredients(nlp_result: dict[str, Any]) -> list[str]:
    status, _ = ingredient_quality_from_result(nlp_result)
    ingredients = nlp_result.get("ingredients")
    if status != "trusted" or not isinstance(ingredients, (list, tuple)):
        return []
    return [item.strip() for item in ingredients if isinstance(item, str) and item.strip()]


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


def _outside_nested_text(value: str) -> str:
    output: list[str] = []
    depth = 0
    for character in value:
        if character in "([":
            depth += 1
            output.append(" ")
        elif character in ")]":
            depth = max(0, depth - 1)
            output.append(" ")
        else:
            output.append(character if depth == 0 else " ")
    return "".join(output)


def _plausible_item(item: str) -> bool:
    compact = " ".join(item.split())
    if not 1 <= len(compact) <= 180:
        return False
    if re.fullmatch(r"(?:e|ins)\s*[- ]?\s*\d{3,4}[a-z]?", compact, re.I):
        return True
    letters = sum(character.isalpha() for character in compact)
    digits = sum(character.isdigit() for character in compact)
    words = re.findall(r"[^\W\d_]{2,}", compact, re.UNICODE)
    return bool(words) and letters >= max(2, digits) and len(words) <= 24


def _quality_assessment(
    ingredients: list[str],
    block: str,
    *,
    truncated: bool,
    boundary_detected: bool,
    ocr_confidence: float | None,
    candidate_ingredients: Iterable[Iterable[str]],
) -> tuple[IngredientQualityState, list[str]]:
    if not ingredients:
        return "untrusted", ["The ingredient heading did not yield usable list items."]

    reasons: list[str] = []
    outside_nested = _outside_nested_text(block)
    contaminated = bool(
        CONTAMINATION_PATTERN.search(outside_nested)
        or PROSE_PATTERN.search(outside_nested)
        or PRODUCT_SPECIFICATION_PATTERN.search(outside_nested)
    )
    implausible_count = sum(not _plausible_item(item) for item in ingredients)
    excessive_noise = implausible_count >= 2 or (
        implausible_count > 0 and implausible_count / len(ingredients) >= 0.25
    )
    if contaminated:
        reasons.append("The extracted section contains unrelated packaging or prose text.")
    if excessive_noise:
        reasons.append("Too many extracted items do not resemble ingredient-list entries.")
    if contaminated or excessive_noise:
        return "untrusted", reasons

    partial_reasons: list[str] = []
    if truncated:
        partial_reasons.append("The ingredient section may be incomplete or truncated.")
    if not boundary_detected:
        partial_reasons.append("A reliable end boundary for the ingredient section was not found.")
    if isinstance(ocr_confidence, (int, float)) and 0 <= ocr_confidence < 0.5:
        partial_reasons.append("Ingredient text had low OCR confidence.")

    signatures = [
        tuple(normalize_label_value(item).casefold() for item in candidate if item.strip())
        for candidate in candidate_ingredients
        if candidate
    ]
    target = tuple(item.casefold() for item in ingredients)
    if len(set(signatures)) > 1:
        dominant, count = Counter(signatures).most_common(1)[0]
        if count < 2 or dominant != target:
            partial_reasons.append("Independent OCR passes disagreed on the ingredient list.")

    if partial_reasons:
        return "partial", list(dict.fromkeys(partial_reasons))
    return "trusted", ["An explicit, bounded, structurally plausible ingredient list was extracted."]


def extract_ingredient_section(
    text: str,
    *,
    ocr_confidence: float | None = None,
    candidate_ingredients: Iterable[Iterable[str]] = (),
) -> IngredientExtraction:
    normalized = normalize_ocr_text(text).replace("—", "-")
    start = INGREDIENT_START.search(normalized)
    if not start:
        return IngredientExtraction(
            quality_status="absent",
            quality_reasons=["No ingredient-section heading was detected."],
        )

    remainder = normalized[start.end() :]
    lines = remainder.splitlines()
    selected: list[str] = []
    depth = 0
    truncated = False
    boundary_detected = False
    stopped = False
    singular = start.group("label").casefold() == "ingredient"

    for line in lines[:MAX_INGREDIENT_SECTION_LINES]:
        line = line.strip()
        if not line:
            if selected:
                boundary_detected = True
                stopped = True
                break
            continue
        repeated_heading = INGREDIENT_START.search(line)
        if selected and repeated_heading and (
            repeated_heading.start() > 0 or INGREDIENT_HEADING_ONLY.fullmatch(line)
        ):
            boundary_detected = True
            stopped = True
            break
        transition = _stop_match(line)
        if transition:
            boundary_detected = True
            line = line[: transition.start()].strip()
        if not line:
            stopped = True
            break
        if selected and selected[-1].rstrip().endswith(".") and depth == 0:
            boundary_detected = True
            stopped = True
            break
        selected.append(line)
        depth += line.count("(") + line.count("[")
        depth -= line.count(")") + line.count("]")
        depth = max(0, depth)
        if transition or singular:
            boundary_detected = True
            stopped = True
            break
    if selected and not stopped and len(lines) <= MAX_INGREDIENT_SECTION_LINES:
        boundary_detected = True
    block = _ingredient_block(selected).strip()
    if (
        (len(lines) > MAX_INGREDIENT_SECTION_LINES and not stopped)
        or block.endswith((",", ";", "-"))
        or depth
    ):
        truncated = True
    ingredients = unique_casefold(
        normalize_label_value(item) for item in _split_top_level(block)
    )
    warnings: list[str] = []
    if not ingredients:
        warnings.append("An ingredient section was detected, but no usable ingredients were extracted.")
    if truncated:
        warnings.append("The ingredient section may be truncated or incomplete.")
    quality_status, quality_reasons = _quality_assessment(
        ingredients,
        block,
        truncated=truncated,
        boundary_detected=boundary_detected,
        ocr_confidence=ocr_confidence,
        candidate_ingredients=candidate_ingredients,
    )
    if quality_status in {"partial", "untrusted"}:
        warnings.extend(quality_reasons)
    return IngredientExtraction(
        ingredients=ingredients,
        section_detected=True,
        heading=start.group("label"),
        truncated=truncated,
        boundary_detected=boundary_detected,
        quality_status=quality_status,
        quality_reasons=quality_reasons,
        warnings=warnings,
    )


def extract_ingredients_from_text(text: str) -> list[str]:
    return extract_ingredient_section(text).ingredients


def normalize_ingredient_name(name: str) -> str:
    return normalize_label_value(name)


def normalize_ingredient_list(ingredients: list[str]) -> list[str]:
    return unique_casefold(normalize_label_value(item) for item in ingredients)
