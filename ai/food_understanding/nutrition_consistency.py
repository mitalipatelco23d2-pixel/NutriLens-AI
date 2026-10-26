"""Detect contradictory declared amounts without correcting OCR or rating food."""

from __future__ import annotations

import re
from decimal import Decimal

from ai.food_understanding.schemas import NutritionExtraction


def _interval(raw: str) -> tuple[Decimal, Decimal] | None:
    text = raw.strip().replace(",", ".")
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", text):
        return None
    amount = Decimal(text)
    # Allow half the last displayed digit on either side, including integer rounding.
    precision = len(text.split(".", 1)[1]) if "." in text else 0
    step = Decimal(1).scaleb(-precision) / 2
    return max(Decimal(0), amount - step), amount + step


def inconsistent_serving_rows(nutrition: NutritionExtraction) -> set[int]:
    """Compare explicit per-100 and serving columns only when dimensions agree.

    Disjoint rounding intervals mean the label evidence contradicts itself.
    Missing/ambiguous columns, inequality values and unlike units are not inferred.
    """
    columns = [column.strip().casefold() for column in nutrition.table_columns]
    bases = [
        (i, unit) for i, c in enumerate(columns) for unit in ("g", "ml") if c == f"per 100 {unit}"
    ]
    servings = [i for i, c in enumerate(columns) if c == "per serving"]
    if len(bases) != 1 or len(servings) != 1:
        return set()
    base, unit = bases[0]
    serving = servings[0]
    if (nutrition.serving_size_unit or "").casefold() != unit:
        return set()
    size = nutrition.serving_size_value or ""
    if not re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", size.strip()):
        return set()
    multiplier = Decimal(size.replace(",", ".")) / 100
    if multiplier <= 0:
        return set()
    conflicts: set[int] = set()
    for index, row in enumerate(nutrition.table_rows):
        if max(base, serving) >= min(len(row.values), len(row.units)):
            continue
        # Extra declared percentages can follow the amount columns. No other
        # unlabelled column is safe to align by position.
        if len(row.values) > len(columns) and any(
            value != "%" for value in row.units[len(columns) :]
        ):
            continue
        if row.units[base] != row.units[serving] or row.units[base] not in {
            "g",
            "mg",
            "mcg",
            "kcal",
            "kJ",
            "kj",
        }:
            continue
        basis_range, serving_range = _interval(row.values[base]), _interval(row.values[serving])
        if basis_range is None or serving_range is None:
            continue
        low, high = (value * multiplier for value in basis_range)
        if high < serving_range[0] or low > serving_range[1]:
            conflicts.add(index)
    return conflicts
