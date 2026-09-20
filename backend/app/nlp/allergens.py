from __future__ import annotations

import re
from dataclasses import dataclass

from .normalizer import normalize_ocr_text, unique_casefold


@dataclass(frozen=True)
class AllergenDeclaration:
    name: str
    declaration: str
    evidence: str


ALLERGEN_ALIASES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Tree Nuts", re.compile(r"\b(?:tree\s+nuts?|nuts?)\b", re.I)),
    ("Peanut", re.compile(r"\bpeanuts?\b", re.I)),
    ("Shellfish", re.compile(r"\b(?:shellfish|crustaceans?)\b", re.I)),
    ("Milk", re.compile(r"\bmilk\b", re.I)),
    ("Soy", re.compile(r"\bsoya?\b", re.I)),
    ("Wheat", re.compile(r"\bwheat\b", re.I)),
    ("Gluten", re.compile(r"\bgluten\b", re.I)),
    ("Egg", re.compile(r"\beggs?\b", re.I)),
    ("Fish", re.compile(r"\bfish\b", re.I)),
    ("Sesame", re.compile(r"\bsesame\b", re.I)),
)
DECLARATIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("may_contain", re.compile(r"\bmay\s+contain\s*:?[ \t]*(?P<items>[^\n.;]{1,160})", re.I)),
    ("facility", re.compile(r"\b(?:processed|made)\s+in\s+(?:a\s+)?facility[^\n.;]*?\b(?:handles?|processes?)\s+(?P<items>[^\n.;]{1,160})", re.I)),
    ("contains", re.compile(r"(?<!may )\bcontains?\s*:?[ \t]*(?P<items>[^\n.;]{1,160})", re.I)),
    ("contains", re.compile(r"\ballergen(?:s| information)?\s*[:\-][ \t]*(?P<items>[^\n.;]{1,160})", re.I)),
)


def _negated_declaration(text: str, match: re.Match[str]) -> bool:
    prefix = text[max(0, match.start() - 24) : match.start()]
    items = match.group("items").lstrip()
    return bool(
        re.search(r"(?:\bmay|\bnot|does\s+not|doesn['’]?t|without)\s*$", prefix, re.I)
        or re.match(r"(?:(?:contains?|does\s+not\s+contain)\s+)?no\b", items, re.I)
        or re.match(r"does\s+not\s+contain\b|without\b", items, re.I)
    )


def extract_allergen_declarations(text: str) -> list[AllergenDeclaration]:
    normalized = normalize_ocr_text(text)
    declarations: list[tuple[int, AllergenDeclaration]] = []
    seen: set[tuple[str, str]] = set()
    for declaration, pattern in DECLARATIONS:
        for match in pattern.finditer(normalized):
            if declaration == "contains" and _negated_declaration(normalized, match):
                continue
            evidence = " ".join(match.group(0).split())
            items = match.group("items")
            for name, allergen_pattern in ALLERGEN_ALIASES:
                allergen_match = allergen_pattern.search(items)
                if not allergen_match:
                    continue
                key = (name.casefold(), declaration)
                if key not in seen:
                    declarations.append(
                        (match.start() + allergen_match.start(), AllergenDeclaration(name, declaration, evidence))
                    )
                    seen.add(key)
    return [item for _, item in sorted(declarations, key=lambda pair: pair[0])]


def extract_explicit_allergens(text: str) -> list[str]:
    return unique_casefold(item.name for item in extract_allergen_declarations(text))
