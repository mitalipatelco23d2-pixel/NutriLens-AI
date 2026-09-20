from __future__ import annotations

import re

from .normalizer import normalize_ocr_text, unique_casefold


E_NUMBER = re.compile(r"(?<![A-Za-z0-9])E\s*[- ]?\s*(?P<number>\d{3,4}[A-Za-z]?)(?!\w)", re.I)
INS_NUMBER = re.compile(r"\bINS\s*[- ]?\s*(?P<number>\d{3,4}[A-Za-z]?)(?!\w)", re.I)
NAMED_CATEGORIES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Flavour enhancer", re.compile(r"\bflavou?r enhancers?\b", re.I)),
    ("Preservative", re.compile(r"\bpreservatives?\b", re.I)),
    ("Emulsifier", re.compile(r"\bemulsifiers?\b", re.I)),
    ("Stabilizer", re.compile(r"\bstabili[sz]ers?\b", re.I)),
    ("Antioxidant", re.compile(r"\bantioxidants?\b", re.I)),
    ("Artificial colour", re.compile(r"\bartificial colou?rs?\b", re.I)),
    ("Acidity regulator", re.compile(r"\bacidity regulators?\b", re.I)),
)
NEGATED_CATEGORY_SPAN = re.compile(
    r"\b(?:no|without|free\s+from|contains?\s+no)\b[^\n.;]{0,100}", re.I
)
ADDITIVE_CONTEXT = re.compile(
    r"\b(?:ingredients?|additives?|colou?rs?|preservatives?|emulsifiers?|"
    r"stabili[sz]ers?|antioxidants?|acidity\s+regulators?|flavou?r\s+enhancers?)\b",
    re.I,
)
INGREDIENT_CONTEXT_START = re.compile(r"\bingre[\s-]*dients?\b", re.I)
INGREDIENT_CONTEXT_STOP = re.compile(
    r"\b(?:nutrition(?:al)?\s+(?:facts|information)|allergens?|best before|"
    r"production date|batch|net (?:weight|wt)|storage|prepared by|produced by|"
    r"manufactured by|packed by|imported by|distributed by)\b",
    re.I,
)


def _has_additive_context(text: str, position: int) -> bool:
    line_start = text.rfind("\n", 0, position) + 1
    line_end = text.find("\n", position)
    if line_end < 0:
        line_end = len(text)
    if ADDITIVE_CONTEXT.search(text[line_start:line_end]):
        return True

    prefix = text[:position]
    starts = list(INGREDIENT_CONTEXT_START.finditer(prefix))
    if not starts:
        return False
    ingredient_start = starts[-1].start()
    stops = list(INGREDIENT_CONTEXT_STOP.finditer(prefix, ingredient_start))
    return not stops or stops[-1].start() < ingredient_start


def extract_additives(text: str) -> list[str]:
    normalized = normalize_ocr_text(text)
    matches: list[tuple[int, str]] = []
    negated_spans = [match.span() for match in NEGATED_CATEGORY_SPAN.finditer(normalized)]
    for match in E_NUMBER.finditer(normalized):
        if _has_additive_context(normalized, match.start()):
            matches.append((match.start(), f"E{match.group('number').upper()}"))
    for match in INS_NUMBER.finditer(normalized):
        if _has_additive_context(normalized, match.start()):
            matches.append((match.start(), f"INS {match.group('number').upper()}"))
    for name, pattern in NAMED_CATEGORIES:
        matches.extend(
            (match.start(), name)
            for match in pattern.finditer(normalized)
            if not any(start <= match.start() < end for start, end in negated_spans)
        )
    return unique_casefold(value for _, value in sorted(matches))
