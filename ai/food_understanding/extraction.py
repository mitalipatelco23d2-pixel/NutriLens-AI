"""Conservative, layout-aware R3 text-to-structure extraction."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from difflib import SequenceMatcher
from statistics import median
from typing import Literal, cast

from ai.food_understanding.schemas import (
    Box,
    DateCandidate,
    DetectionMethod,
    IngredientExtraction,
    NutritionExtraction,
    NutritionRow,
    OCRLine,
    OCRNormalizationTrace,
    Region,
    TextCandidate,
)


@dataclass(frozen=True)
class _NutrientSpec:
    canonical: str
    aliases: tuple[str, ...]
    units: frozenset[str]


NUTRIENT_SPECS = (
    _NutrientSpec(
        "energy_kj",
        (
            "energy kj",
            "energie kj",
            "energy(kj)",
            "energie(kj)",
            "valeur energetique kj",
            "valeur énergétique kj",
        ),
        frozenset({"kj"}),
    ),
    _NutrientSpec(
        "energy",
        (
            "energy",
            "energy kcal",
            "energie kcal",
            "calories",
            "calorie",
            "calorles",
            "ccalones",
            "clories",
            "todes",
            "atodes",
            "calodes",
            "valeur energetique kcal",
            "valeur énergétique kcal",
        ),
        frozenset({"kcal", "kj"}),
    ),
    _NutrientSpec(
        "protein",
        ("protein", "proteins", "rotein", "protem", "irteln", "moteln", "proteines", "eiwitten"),
        frozenset({"g"}),
    ),
    _NutrientSpec(
        "carbohydrate",
        (
            "carbohydrate",
            "carbohydrates",
            "total carbohydrate",
            "total carbohydrates",
            "carbohydates",
            "nrohydrakcs",
            "abohydratcs",
            "ntphydratcs",
            "ntohydratcs",
            "total carb",
            "carbs",
            "glucides",
            "koolhydraten",
        ),
        frozenset({"g"}),
    ),
    _NutrientSpec(
        "added sugar",
        (
            "added sugar",
            "added sugars",
            "includes added sugar",
            "includes added sugars",
            "aded sugar",
            "uded sugar",
            "mded sugar",
        ),
        frozenset({"g"}),
    ),
    _NutrientSpec(
        "total sugar",
        (
            "total sugar",
            "total sugars",
            "totalsugar",
            "of which sugars",
            "sugars",
            "sugar",
        ),
        frozenset({"g"}),
    ),
    _NutrientSpec(
        "saturated fat",
        (
            "saturated fat",
            "saturatedfat",
            "saturatd fat",
            "auunled fat",
            "auated fat",
            "of which saturates",
            "saturates",
        ),
        frozenset({"g"}),
    ),
    _NutrientSpec(
        "trans fat",
        ("trans fat", "transfat", "iinans fat", "inns fat"),
        frozenset({"g"}),
    ),
    _NutrientSpec(
        "total fat",
        (
            "total fat",
            "totalfat",
            "tabfat",
            "abfat",
            "voblfal",
            "vobl fat",
            "otal fat",
            "matieres grasses",
            "vetten",
            "fat",
        ),
        frozenset({"g"}),
    ),
    _NutrientSpec(
        "cholesterol",
        ("cholesterol", "cholestrol", "colesterol"),
        frozenset({"mg"}),
    ),
    _NutrientSpec(
        "sodium",
        ("sodium", "sodiumn", "sdium", "sodlum", "miwm"),
        frozenset({"mg"}),
    ),
    _NutrientSpec(
        "calcium",
        ("calcium", "calctum", "clctum", "calclum", "illwn"),
        frozenset({"mg"}),
    ),
    _NutrientSpec(
        "fibre",
        ("fibre", "fiber", "dietary fibre", "dietary fiber", "fibres alimentaires", "vezels"),
        frozenset({"g"}),
    ),
    _NutrientSpec(
        "salt",
        ("salt", "sel", "zout", "salz", "sel zout", "salt selzout", "salt sel zout"),
        frozenset({"g", "mg"}),
    ),
)
NUTRIENT_TERMS = tuple(dict.fromkeys(alias for spec in NUTRIENT_SPECS for alias in spec.aliases))
_FRONT_CANDIDATE_NUTRIENT_TERMS = tuple(
    term
    for term in NUTRIENT_TERMS
    if term
    not in {
        "fat",
        "sugar",
        "sugars",
        "protein",
        "proteins",
        "fiber",
        "fibre",
        "carbs",
        "calcium",
        "salt",
    }
)
VALUE_PATTERN = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?|[oO](?=\s*(?:kcal|kj|mg|mcg|µg|ug|g|ml)\b))"
    r"\s*(kcal|kj|mg|mcg|µg|ug|g|ml|%)?",
    re.I,
)
GLYPH_VALUE_PATTERN = re.compile(
    r"(?<![\w.])([0-9SOJIBojib]+(?:[.,][0-9SOJIBojib]+)?)"
    r"\s*(kcal|kj|mg|mcg|µg|ug|g|ml|%)?",
    re.I,
)


def _normalize_ocr_glyph_candidate(
    token: str,
) -> tuple[str, list[OCRNormalizationTrace]] | None:
    """Normalize OCR glyph substitutions in numeric cells.

    Supports candidates like S7 -> 57, J8 -> 18, O -> 0, 1O -> 10.
    Returns normalized numeric string and trace list, or None if token cannot be normalized.
    Preserves raw observed token in trace.
    """
    cleaned = token.replace(",", ".")
    traces: list[OCRNormalizationTrace] = []

    parts = cleaned.split(".")
    if len(parts) <= 2 and all(p.isdigit() for p in parts if p):
        return cleaned, []

    glyph_map = {
        "S": ("5", "OCR_GLYPH_S_TO_5", 0.90),
        "s": ("5", "OCR_GLYPH_S_TO_5", 0.90),
        "J": ("1", "OCR_GLYPH_J_TO_1", 0.85),
        "j": ("1", "OCR_GLYPH_J_TO_1", 0.85),
        "O": ("0", "OCR_GLYPH_O_TO_0", 0.95),
        "o": ("0", "OCR_GLYPH_O_TO_0", 0.95),
        "I": ("1", "OCR_GLYPH_I_TO_1", 0.90),
        "i": ("1", "OCR_GLYPH_I_TO_1", 0.85),
        "l": ("1", "OCR_GLYPH_L_TO_1", 0.85),
        "B": ("8", "OCR_GLYPH_B_TO_8", 0.85),
        "b": ("6", "OCR_GLYPH_b_TO_6", 0.80),
    }

    has_digit = any(c.isdigit() for c in cleaned)
    is_known_glyph_only = len(cleaned) == 1 and cleaned in glyph_map

    if not (has_digit or is_known_glyph_only):
        return None

    normalized_chars: list[str] = []
    for c in cleaned:
        if c.isdigit() or c == ".":
            normalized_chars.append(c)
        elif c in glyph_map:
            rep, rule_type, conf = glyph_map[c]
            normalized_chars.append(rep)
            traces.append(
                OCRNormalizationTrace(
                    observed_token=c,
                    normalized_value=rep,
                    normalization_type=rule_type,
                    confidence=conf,
                )
            )
        else:
            return None

    normalized_str = "".join(normalized_chars)
    parts_norm = normalized_str.split(".")
    if len(parts_norm) > 2 or not all(p.isdigit() for p in parts_norm if p):
        return None

    return normalized_str, traces


SERVING_PATTERN = re.compile(
    r"(?:s(?:erv|r)(?:ing|ng)|(?:or|n)ing)\s*size\s*[-:]?\s*(\d+(?:[.,]\d+)?)\s*(mml|m[l1it]|g)",
    re.I,
)
MONTH_PATTERN = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
DATE_PATTERN = re.compile(
    rf"\b(\d{{1,2}}[./-]\d{{1,2}}(?:[./-]\d{{2,4}})?|"
    rf"\d{{1,2}}\s+{MONTH_PATTERN}\s+\d{{2,4}}|{MONTH_PATTERN}\s+\d{{2,4}})\b",
    re.I,
)
DATE_LABELS = {
    "mfg": "MFG",
    "mfd": "MFG",
    "manufactured": "MFG",
    "pkd": "PACKED_ON",
    "packed on": "PACKED_ON",
    "best before": "BEST_BEFORE",
    "use by": "USE_BY",
    "expiry": "EXPIRY",
    "expires": "EXPIRY",
    "exp": "EXPIRY",
}
_METADATA_TAIL = re.compile(
    r"\b(?:for\s+batch|batch\s+no|use\s+by|best\s+before|mfg|mfd|mrp|"
    r"net\s+quantity|nutrition(?:al)?\s+(?:facts|information)|serving\s+size)\b.*$",
    re.I,
)
_INGREDIENT_START = re.compile(
    r"\b(?:ingredients?|ngre[do]ients?|composition|made\s+(?:from|with))\b\s*[:\-]?",
    re.I,
)
_ALLERGEN_START = re.compile(
    r"\b(?:(?:may|might|could)\s+(?:also\s+)?contains?|"
    r"(?:does\s+not|do\s+not|not|doesn['’]t|don['’]t)\s+contain|"
    r"free[\s-]+(?:from|of)|traces?\s+of|no\s+allergens?|"
    r"(?:milk|dairy|soy|soya|nuts?|peanuts?|wheat|gluten|eggs?|fish|shellfish|allergen)[\s-]+free|"
    r"contains?|all?ergens?(?:\s+information)?)\b\s*[:\-]?",
    re.I,
)
_ALLERGEN_CONTROL_TOKENS = frozenset(
    {
        "allergen",
        "allergens",
        "allergy",
        "also",
        "contain",
        "contains",
        "could",
        "declaration",
        "do",
        "does",
        "free",
        "from",
        "information",
        "label",
        "may",
        "might",
        "no",
        "not",
        "of",
        "statement",
        "trace",
        "traces",
    }
)
_BRAND_LEGAL_CONTEXT = re.compile(r"\b(?:brand|logo|registered\s+trademark|trademark)\b", re.I)
_EXPLICIT_BRAND = re.compile(r"\bbrand(?:\s+name)?\s*[:\-]\s*(.{2,80})$", re.I)
_DOCUMENT_SECTION_ALIASES = (
    "nutrition facts",
    "nutrition information",
    "nutritional information",
    "nutrient information",
    "serving information",
    "ingredient information",
    "allergen information",
    "net quantity",
    "typical values",
    "average values",
    "valeurs moyennes",
    "gemiddelde waarden",
)
_MARKETING_SLOGAN_ALIASES = (
    "live better",
    "eat better",
    "feel better",
    "good for you",
    "made with love",
    "people love making food",
    "making food people love",
    "serving suggestion",
)
_SECTION_STOP = re.compile(
    r"\b(?:net\s+quantity|nutrition(?:al)?\s+(?:facts|information)|serving\s+size|"
    r"for\s+batch|batch\s+no|use\s+by|best\s+before|mfg|mfd|mrp|fssai)\b",
    re.I,
)
_COMPOSITION_LINE = re.compile(
    r"(?:\bsnf\b|\bfat\b.*\d+(?:[.,]\d+)?\s*%|^\s*(?:max|min)\.?\s*$)", re.I
)
_COMPOSITION_FRAGMENT = re.compile(r"^[a-z]{0,2}\d+(?:[.,]\d+)?\s*%$", re.I)


def _allergen_payload_tokens(statement: str) -> list[str]:
    """Return evidence tokens after bounded allergen headings/qualifiers are removed."""
    return [
        token
        for token in re.findall(r"[a-z0-9]+", statement.casefold())
        if token not in _ALLERGEN_CONTROL_TOKENS
    ]


def _clean_allergen_statements(statements: list[str]) -> list[str]:
    """Drop heading-only OCR fragments without inventing an allergen target."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for statement in statements:
        candidate = statement.strip(" ,;:-")
        if not candidate or not _allergen_payload_tokens(candidate):
            continue
        identity = " ".join(re.findall(r"[a-z0-9]+", candidate.casefold()))
        if identity in seen:
            continue
        seen.add(identity)
        cleaned.append(candidate)
    return cleaned


def _is_per_100_ml_basis(header_text: str) -> bool:
    """Safe check for PER_100_ML basis in nutrition header.

    Rejects standalone '1001 ml' or arbitrary quantities (e.g. '1500 ml').
    Only resolves to PER_100_ML if:
    1. Explicit canonical pattern: 'per 100 ml' / '/ 100 ml'.
    2. Explicit OCR misread: 'per 1001 ml' / '/ 1001 ml'.
    3. Clear nutrition context (e.g. 'nutrition', 'facts', 'information', 'approx', 'serving')
       together with '100 ml', '1001 ml', or single OCR artifact separator like '100 D ml'.
    Standalone '1001 ml' without context is NOT accepted.
    """
    clean_header = re.sub(
        r"(?:s(?:erv|r)(?:ing|ng)|(?:or|n)ing)\s*size\s*[-:]?\s*\d+(?:[.,]\d+)?\s*(?:mml|m[l1it]|g)\b",
        " ",
        header_text.casefold(),
    )

    if re.search(r"(?:per|/)\s*100\s*m[l1i]\b", clean_header):
        return True

    if re.search(r"(?:per|/)\s*100\s*1?\s*m[l1i]\b", clean_header):
        return True

    has_nutrition_context = any(
        marker in clean_header
        for marker in (
            "nutrition",
            "nutrient",
            "facts",
            "information",
            "typical values",
            "approx",
            "per",
            "serve",
            "serving",
            "100g",
            "100 g",
        )
    )
    return bool(
        has_nutrition_context
        and (
            re.search(r"\b100\s*(?:[a-z0-9]\s+)?m[l1i]\b", clean_header)
            or re.search(r"\b1001\s*m[l1i]\b", clean_header)
        )
    )


def _is_per_100_g_basis(header_text: str) -> bool:
    clean_header = re.sub(
        r"(?:s(?:erv|r)(?:ing|ng)|(?:or|n)ing)\s*size\s*[-:]?\s*\d+(?:[.,]\d+)?\s*(?:mml|m[l1it]|g)\b",
        " ",
        header_text.casefold(),
    )
    if re.search(r"(?:per|/)\s*[1i]00\s*g\b", clean_header):
        return True
    has_nutrition_context = any(
        marker in clean_header
        for marker in (
            "nutrition",
            "nutrient",
            "facts",
            "information",
            "typical values",
            "valeurs moyennes",
            "gemiddelde waarden",
            "approx",
            "per",
            "serve",
            "serving",
            "100ml",
            "100 ml",
        )
    )
    return bool(has_nutrition_context and re.search(r"\b[1i]00\s*g\b", clean_header))


BasisType = Literal[
    "PER_100_G",
    "PER_100_ML",
    "PER_SERVING",
    "PERCENT_RDA",
    "PERCENT_DV",
    "UNKNOWN",
]


def _detect_table_columns(header_text: str, rows: list[NutritionRow]) -> list[str]:
    clean_header = re.sub(
        r"(?:s(?:erv|r)(?:ing|ng)|(?:or|n)ing)\s*size\s*[-:]?\s*\d+(?:[.,]\d+)?\s*(?:mml|m[l1it]|g)\b",
        " ",
        header_text.casefold(),
    )
    clean_header = re.sub(
        r"\b(?:servings?|erings?)\s+per\s+(?:pack|package|container|bottle|box|pouch|bag)\b",
        " ",
        clean_header,
    )
    clean_header_no_rda = re.sub(
        r"(?:%|196)?\s*(?:r\s*i?d[aā]|ada)\s*per\s*(?:serv(?:ing|e|a)?|scrv[a0o])\b",
        " ",
        clean_header,
    )
    ordered_markers: list[tuple[int, str]] = []
    match_100g = re.search(r"(?:(?:per|/)\s*)?\b[1i]00\s*g\b", clean_header_no_rda)
    if match_100g and _is_per_100_g_basis(header_text):
        ordered_markers.append((match_100g.start(), "per 100 g"))
    match_100ml = re.search(
        r"(?:(?:per|/)\s*)?(?:\b100\s*(?:[a-z0-9]\s+)?m[l1i]\b|\b1001\s*m[l1i]\b)",
        clean_header_no_rda,
    )
    if match_100ml and _is_per_100_ml_basis(header_text):
        ordered_markers.append((match_100ml.start(), "per 100 ml"))
    match_serving = re.search(
        r"(?:(?:per|/)\s*)?\b(serv(?:ing|e|a)?|scrv[a0o]|cookie|biscuit|piece|portion|bowl|cup|sachet)\b",
        clean_header_no_rda,
    )
    if match_serving:
        serving_token = match_serving.group(1).lower()
        if "cookie" in serving_token:
            ordered_markers.append((match_serving.start(), "per cookie"))
        elif "biscuit" in serving_token:
            ordered_markers.append((match_serving.start(), "per biscuit"))
        elif "piece" in serving_token:
            ordered_markers.append((match_serving.start(), "per piece"))
        else:
            ordered_markers.append((match_serving.start(), "per serving"))
    match_with_milk = re.search(
        r"\b(?:with|w/)\s*(?:[\d/]+\s*cup\s*)?(?:skim\s*)?milk\b",
        clean_header_no_rda,
    )
    if match_with_milk:
        ordered_markers.append((match_with_milk.start(), "with milk"))
    match_container = re.search(
        r"\b(?:per|/)\s*(?:container|pack|package|bottle|box|pouch|bag)\b",
        clean_header_no_rda,
    )
    if match_container:
        ordered_markers.append((match_container.start(), "per container"))

    ordered_markers.sort(key=lambda item: item[0])
    columns: list[str] = [col for _pos, col in ordered_markers]

    has_explicit_pct_header = bool(
        re.search(
            r"(?:%|196)?\s*(?:r\s*i?d[aā]|ada)\s*per\b|adaper\b|(?:%|196)\s*(?:r\s*i?d[aā]|ada|dv)\b|%\s*ri\b|reference\s*intake|daily\s*values?",
            header_text,
            re.I,
        )
    )
    pct_rows_count = sum(1 for row in rows if "%" in row.units)
    has_majority_pct_values = pct_rows_count >= max(2, len(rows) // 2) and "%" in header_text

    if has_explicit_pct_header or has_majority_pct_values:
        if re.search(r"(?:%|196)\s*dv\b|daily\s*values?", header_text, re.I):
            columns.append("% DV")
        else:
            columns.append("% RDA per serving")
    return columns


def _populate_parsed_values(
    rows: list[NutritionRow],
    *,
    basis: str,
    columns: list[str],
    serving_value: str | None,
    serving_unit: str | None,
) -> list[NutritionRow]:
    from .schemas import NutritionValue

    column_bases: list[BasisType] = []
    column_source_texts: list[str] = []
    for c in columns:
        lowered = c.lower()
        column_source_texts.append(c)
        if "%" in lowered or "rda" in lowered or "dv" in lowered:
            if "dv" in lowered:
                column_bases.append("PERCENT_DV")
            else:
                column_bases.append("PERCENT_RDA")
        elif "100 g" in lowered:
            column_bases.append("PER_100_G")
        elif "100 ml" in lowered or "100ml" in lowered:
            column_bases.append("PER_100_ML")
        elif any(
            term in lowered
            for term in (
                "serving",
                "serve",
                "cookie",
                "biscuit",
                "piece",
                "portion",
                "cup",
                "bowl",
                "milk",
                "container",
                "pack",
            )
        ):
            column_bases.append("PER_SERVING")
        else:
            column_bases.append("UNKNOWN")

    non_ref_bases: list[tuple[BasisType, str]] = [
        (b, column_source_texts[idx])
        for idx, b in enumerate(column_bases)
        if b not in ("PERCENT_RDA", "PERCENT_DV")
    ]
    ref_basis: BasisType = next(
        (b for b in column_bases if b in ("PERCENT_RDA", "PERCENT_DV")),
        "PERCENT_RDA",
    )
    ref_source_text: str = next(
        (
            column_source_texts[idx]
            for idx, b in enumerate(column_bases)
            if b in ("PERCENT_RDA", "PERCENT_DV")
        ),
        "% RDA per serving",
    )

    resolved_serving_str = f"{serving_value} {serving_unit}".strip() if serving_value else None

    # Infer column horizontal centers from rows having full column boxes
    inferred_col_centers: list[float] | None = None
    if len(columns) >= 2:
        col_x_samples: list[list[float]] = [[] for _ in range(len(columns))]
        for r in rows:
            if len(r.values) == len(columns) and len(r.source_boxes) >= len(columns):
                s_boxes = sorted(r.source_boxes, key=lambda b: b.x)
                val_boxes = s_boxes[-len(columns) :]
                for idx, b in enumerate(val_boxes):
                    col_x_samples[idx].append(b.x + b.width / 2)
        if all(col_x_samples):
            inferred_col_centers = [float(median(samples)) for samples in col_x_samples]

    updated_rows: list[NutritionRow] = []
    for row in rows:
        parsed_vals: list[NutritionValue] = []
        row_units = list(row.units)
        non_ref_idx = 0
        for i, val in enumerate(row.values):
            unit = row_units[i] if i < len(row_units) else ""
            c_basis: BasisType
            src_text: str | None = None

            # Geometric column association when 1 value is present in a multi-column table
            if (
                len(row.values) == 1
                and inferred_col_centers is not None
                and row.source_boxes
                and len(columns) >= 2
            ):
                x_val = row.source_boxes[-1].x + row.source_boxes[-1].width / 2
                matched_idx = min(
                    range(len(columns)),
                    key=lambda idx: abs(inferred_col_centers[idx] - x_val),
                )
                c_basis = column_bases[matched_idx]
                src_text = column_source_texts[matched_idx]
                if c_basis in ("PERCENT_RDA", "PERCENT_DV"):
                    unit = "%"
            elif i < len(column_bases) and column_bases[i] in ("PERCENT_RDA", "PERCENT_DV"):
                c_basis = column_bases[i]
                src_text = column_source_texts[i]
                unit = "%"
                if i < len(row_units):
                    row_units[i] = "%"
                else:
                    row_units.append("%")
            elif unit == "%":
                c_basis = ref_basis
                src_text = ref_source_text
            elif i < len(column_bases) and column_bases[i] not in ("PERCENT_RDA", "PERCENT_DV"):
                c_basis = column_bases[i]
                src_text = column_source_texts[i]
                non_ref_idx += 1
            elif non_ref_idx < len(non_ref_bases):
                c_basis, src_text = non_ref_bases[non_ref_idx]
                non_ref_idx += 1
            elif len(row.values) == 1 and basis in (
                "PER_100_G",
                "PER_100_ML",
                "PER_SERVING",
            ):
                c_basis = cast(BasisType, basis)
                src_text = basis.replace("_", " ").lower()
                non_ref_idx += 1
            else:
                c_basis = "UNKNOWN"
                src_text = None
                non_ref_idx += 1

            is_ref = c_basis in ("PERCENT_RDA", "PERCENT_DV") or unit == "%"
            parsed_vals.append(
                NutritionValue(
                    value=val,
                    unit=unit,
                    basis=c_basis,
                    resolved_serving=(resolved_serving_str if c_basis == "PER_SERVING" else None),
                    source_basis_text=src_text,
                    is_reference_intake=is_ref,
                )
            )
        updated_rows.append(
            row.model_copy(
                update={
                    "parsed_values": parsed_vals,
                    "values": [pv.value for pv in parsed_vals],
                    "units": [pv.unit for pv in parsed_vals],
                }
            )
        )
    return updated_rows


def extract_nutrition(lines: list[OCRLine], region: Region | None) -> NutritionExtraction:
    raw_selected = _lines_in_region(lines, region)
    split_lines: list[OCRLine] = []
    for line in raw_selected:
        if ("|" in line.text or "¦" in line.text or "│" in line.text) and line.bounding_box:
            delim = "|" if "|" in line.text else ("¦" if "¦" in line.text else "│")
            parts = line.text.split(delim)
            total_len = len(line.text)
            box = line.bounding_box
            curr_char = 0
            for p in parts:
                p_len = len(p)
                p_box = Box(
                    x=box.x + box.width * (curr_char / max(1, total_len)),
                    y=box.y,
                    width=box.width * (p_len / max(1, total_len)),
                    height=box.height,
                )
                split_lines.append(
                    OCRLine(
                        text=p.strip(),
                        confidence=line.confidence,
                        bounding_box=p_box,
                    )
                )
                curr_char += p_len + 1
        else:
            split_lines.append(line)
    selected = _ordered_lines(split_lines)
    text = "\n".join(line.text for line in selected)
    rows: list[NutritionRow] = []
    for row_number, row_lines in enumerate(_cluster_nutrition_rows(selected), start=1):
        ordered = sorted(
            row_lines,
            key=lambda item: item.bounding_box.x if item.bounding_box is not None else 0,
        )
        ordered = _prune_overlapping_value_lines(ordered)
        parse_lines = ordered
        raw_row_text = " ".join(
            item.text.strip() for item in parse_lines if item.text.strip()
        ).strip()
        row_text = _clean_ocr_value_delimiters(raw_row_text)
        first_value = VALUE_PATTERN.search(row_text)
        if first_value is None:
            continue
        raw_label = row_text[: first_value.start()].strip(" :-|.")
        value_matches = list(VALUE_PATTERN.finditer(row_text[first_value.start() :]))
        match = _match_nutrient(raw_label)
        if match is None:
            match = _match_nutrient_from_units(value_matches)
        if match is None:
            continue
        spec, match_confidence = match
        # Extract raw tokens using exact character-level alignment to maintain source provenance
        sm_aligner = SequenceMatcher(None, raw_row_text, row_text)
        raw_values: list[str] = []
        values: list[str] = []
        row_traces: list[OCRNormalizationTrace] = []
        for _idx, item in enumerate(value_matches):
            tok = item.group(1)
            raw_match_str = item.group(0).strip()
            c_start = first_value.start() + item.start(0)
            c_end = first_value.start() + item.end(0)

            # Map clean token match coordinates back to raw_row_text
            r_start = None
            r_end = None
            for tag, i1, i2, j1, j2 in sm_aligner.get_opcodes():
                if j1 <= c_start < j2:
                    r_start = i1 + (c_start - j1) if tag == "equal" else i1
                if j1 < c_end <= j2:
                    r_end = i1 + (c_end - j1) if tag == "equal" else i2

            if r_start is not None and r_end is not None and r_start < r_end:
                raw_val_str = raw_row_text[r_start:r_end].strip()
            else:
                raw_val_str = raw_match_str

            raw_values.append(raw_val_str)

            norm_res = _normalize_ocr_glyph_candidate(tok)
            # Check if numeric token part underwent glyph substitution (e.g. S7->57, J8->18, O->0)
            tok_raw = re.sub(r"[^a-zA-Z0-9]", "", raw_val_str)
            raw_num_part = re.sub(r"[a-zA-Z]+$", "", tok_raw)
            if raw_num_part != tok and any(c.isalpha() for c in raw_num_part):
                # Raw OCR token underwent actual glyph substitution
                numeric_glyph = raw_num_part
                rule = "OCR_GLYPH_NORMALIZATION"
                if re.search(r"[sS]", numeric_glyph) and "5" in tok:
                    rule = "OCR_GLYPH_S_TO_5"
                elif re.search(r"[jJ]", numeric_glyph) and "1" in tok:
                    rule = "OCR_GLYPH_J_TO_1"
                elif re.search(r"[oO]", numeric_glyph) and "0" in tok:
                    rule = "OCR_GLYPH_O_TO_0"
                row_traces.append(
                    OCRNormalizationTrace(
                        observed_token=numeric_glyph,
                        normalized_value=tok,
                        normalization_type=rule,
                        confidence=0.85,
                    )
                )
                values.append(tok.replace(",", "."))
            elif norm_res is not None and norm_res[1]:
                norm_val, traces = norm_res
                values.append(norm_val)
                row_traces.extend(traces)
            elif tok.casefold() == "o":
                values.append("0")
                row_traces.append(
                    OCRNormalizationTrace(
                        observed_token=raw_val_str,
                        normalized_value="0",
                        normalization_type="OCR_GLYPH_O_TO_0",
                        confidence=0.95,
                    )
                )
            else:
                values.append(tok.replace(",", "."))
        units = [_normalize_unit(item.group(2)) for item in value_matches]
        for i, raw_v in enumerate(raw_values):
            if not units[i] and re.search(r"[*xXk%]$", raw_v):
                units[i] = "%"
        if spec.canonical == "energy":
            lowered_raw_label = raw_label.casefold()
            row_energy_unit = (
                "kj" if ("kj" in lowered_raw_label or any(u == "kj" for u in units)) else "kcal"
            )
            units = [
                u
                if (
                    u
                    or (
                        i < len(raw_values)
                        and ("%" in raw_values[i] or re.search(r"[*xXk%]$", raw_values[i]))
                    )
                )
                else row_energy_unit
                for i, u in enumerate(units)
            ]
        elif spec.canonical == "energy_kj":
            units = [
                u if (u or (i < len(raw_values) and "%" in raw_values[i])) else "kj"
                for i, u in enumerate(units)
            ]
        else:
            explicit_spec_units = [u for u in units if u and u in spec.units]
            if explicit_spec_units:
                primary_unit = explicit_spec_units[0]
                units = [
                    (
                        primary_unit
                        if (
                            not u
                            and i < len(raw_values)
                            and not re.search(r"[*xXk%]$", raw_values[i])
                        )
                        else u
                    )
                    for i, u in enumerate(units)
                ]
        explicit_units = {unit for unit in units if unit and unit != "%"}
        if explicit_units and not explicit_units.intersection(spec.units):
            continue
        line_confidences = [item.confidence for item in parse_lines if item.confidence is not None]
        ocr_confidence = sum(line_confidences) / len(line_confidences) if line_confidences else None
        confidence = (
            min(match_confidence, ocr_confidence)
            if ocr_confidence is not None
            else match_confidence
        )
        rows.append(
            NutritionRow(
                label=spec.canonical,
                raw_label=raw_label,
                canonical_label=spec.canonical,
                match_confidence=match_confidence,
                parsed_values=[],
                values=values,
                raw_values=raw_values,
                units=units,
                normalization_traces=row_traces,
                source_rows=[row_number],
                source_boxes=[
                    item.bounding_box for item in parse_lines if item.bounding_box is not None
                ],
                confidence=confidence,
            )
        )

    rows = _deduplicate_nutrition_rows(rows)

    lowered_text = _normalize_label(text)
    header_text = _nutrition_header_text(selected)
    if _is_per_100_g_basis(header_text):
        basis = "PER_100_G"
    elif _is_per_100_ml_basis(header_text):
        basis = "PER_100_ML"
    elif re.search(
        r"per\s*(?:serv(?:ing|e)|cookie|biscuit|piece|portion|bowl|cup|pack|sachet)\b|(?:s(?:erv|r)(?:ing|ng)|(?:or|n)ing)\s*size",
        lowered_text,
    ):
        basis = "PER_SERVING"
    else:
        basis = "UNKNOWN"
    columns = _detect_table_columns(header_text, rows)
    serving_match = SERVING_PATTERN.search(text)
    serving_value, serving_unit = _serving_size_from_layout(selected)
    normalized_serving_value = (
        serving_match.group(1).replace(",", ".") if serving_match else serving_value
    )
    normalized_serving_unit = (
        "ml"
        if serving_match and serving_match.group(2).lower() in {"mml", "m1", "mi", "mt"}
        else serving_match.group(2).lower()
        if serving_match
        else serving_unit
    )
    rows = _normalize_serving_columns(
        rows,
        basis=basis,
        columns=columns,
        serving_value=normalized_serving_value,
        serving_unit=normalized_serving_unit,
    )
    rows = _populate_parsed_values(
        rows,
        basis=basis,
        columns=columns,
        serving_value=normalized_serving_value,
        serving_unit=normalized_serving_unit,
    )
    confidences = [row.confidence for row in rows if row.confidence is not None]
    overall_confidence: float | None = None
    if confidences:
        coverage = min(1.0, 0.55 + 0.05 * len(rows))
        overall_confidence = (sum(confidences) / len(confidences)) * coverage
    return NutritionExtraction(
        region=region,
        raw_table_text=text if region is not None else "",
        table_rows=rows,
        table_columns=columns,
        basis=basis,  # type: ignore[arg-type]
        serving_size_value=normalized_serving_value,
        serving_size_unit=normalized_serving_unit,
        confidence=overall_confidence,
    )


_INGREDIENT_MODIFIERS_TAIL = re.compile(
    r"\b(?:and|or|with|containing|of|from|min\.?|max\.?|fat|solids?|pasteurized|homogenized|"
    r"fortified|dehydrated|concentrated|hydrogenated|hydrolyzed|refined|bleached|enriched|"
    r"iodized|skimmed|whole|skim|low|reduced|pure|natural|organic|raw|fresh|filtered|"
    r"partially|added|crushed|ground|flaked|toasted|roasted|dried|sweetened|unsweetened|"
    r"fermented|cultured|modified|isolated)\b$",
    re.I,
)

_INGREDIENT_MODIFIERS_HEAD = re.compile(
    r"^(?:and\b|or\b|with\b|of\b|from\b|min\.?|max\.?|%\b|percent\b|\d+(?:[.,]\d+)?\s*%|"
    r"powder\b|extract\b|oil\b|syrup\b|flour\b|paste\b|starch\b|gum\b|isolate\b|"
    r"concentrate\b|protein\b|solids?\b|fiber\b|"
    r"seeds?\b|leaves\b|pieces\b|flakes\b|meal\b)",
    re.I,
)


def _join_ingredient_lines(lines: list[str]) -> str:
    """Join OCR ingredient lines, preserving continuity without merging distinct items."""
    cleaned_lines = [line.strip() for line in lines if line and line.strip()]
    cleaned_lines = [line for line in cleaned_lines if not re.fullmatch(r"^[,;.\s]+$", line)]
    if not cleaned_lines:
        return ""

    joined_chunks: list[str] = []
    for line in cleaned_lines:
        if not joined_chunks:
            if re.match(r"^ingredients?\s*:$", line, re.I):
                continue
            joined_chunks.append(line)
            continue

        prev = joined_chunks[-1]
        bullet_match = re.match(r"^[\u2022\u25cf\*\-]\s*", line)

        if prev.endswith((",", ";", ":")):
            joined_chunks.append(line)
        elif bullet_match:
            joined_chunks[-1] = prev.rstrip(",") + ","
            joined_chunks.append(line[bullet_match.end() :].strip())
        else:
            unclosed_paren = prev.count("(") > prev.count(")")
            ends_with_modifier = bool(_INGREDIENT_MODIFIERS_TAIL.search(prev))
            starts_with_modifier = bool(
                _INGREDIENT_MODIFIERS_HEAD.search(line) or line.startswith(("%", "(", ")"))
            )

            if unclosed_paren or ends_with_modifier or starts_with_modifier:
                joined_chunks[-1] = f"{prev} {line}"
            else:
                joined_chunks[-1] = prev.rstrip(",") + ","
                joined_chunks.append(line)

    result = " ".join(joined_chunks).strip(" ;")
    result = re.sub(r",\s*,+", ",", result)
    result = re.sub(r"\s+", " ", result).strip(" ;,")
    return result


def extract_ingredients(lines: list[OCRLine], region: Region | None) -> IngredientExtraction:
    selected = _ordered_lines(_lines_in_region(lines, region))
    ingredients: list[str] = []
    allergen_statements: list[str] = []
    source_rows: list[int] = []
    ingredient_confidences: list[float] = []
    allergen_confidences: list[float] = []
    collecting = False

    for row_number, line in enumerate(selected, start=1):
        text = line.text.strip()
        if not text:
            continue
        allergen_match = _ALLERGEN_START.search(text)
        ingredient_match = _INGREDIENT_START.search(text)
        if ingredient_match is not None:
            collecting = True
            text = text[ingredient_match.end() :].strip(" :-")
            allergen_match = _ALLERGEN_START.search(text)
        if allergen_match is not None:
            before = text[: allergen_match.start()].strip(" ,;:-")
            statement = text[allergen_match.start() :].strip()
            if collecting and before:
                ingredients.append(before)
                source_rows.append(row_number)
                if line.confidence is not None:
                    ingredient_confidences.append(line.confidence)
            if statement:
                # Preserve the whole clause, including negation/precaution. R4 must
                # not receive an affirmative-looking token after stripping 'may'.
                allergen_statements.append(statement)
                if line.confidence is not None:
                    allergen_confidences.append(line.confidence)
            collecting = False
            continue
        if collecting and _SECTION_STOP.search(text):
            break
        if collecting and (
            VALUE_PATTERN.fullmatch(text)
            or _COMPOSITION_LINE.search(text)
            or _COMPOSITION_FRAGMENT.fullmatch(text)
        ):
            # Perspective-warped labels can place a composition statement a
            # few pixels before the actual first ingredient even though it is
            # printed after it. Skip that statement, but retain the bounded
            # ingredient section until at least one ingredient is collected.
            collecting = not ingredients
            continue
        if collecting and text:
            ingredients.append(text)
            source_rows.append(row_number)
            if line.confidence is not None:
                ingredient_confidences.append(line.confidence)
            if len(ingredients) >= 8 or sum(map(len, ingredients)) >= 1_000:
                break

    for line in selected:
        match = _ALLERGEN_START.search(line.text)
        if match is None:
            continue
        statement = line.text[match.start() :].strip()
        if statement and statement not in allergen_statements:
            allergen_statements.append(statement)
            if line.confidence is not None:
                allergen_confidences.append(line.confidence)

    raw = _join_ingredient_lines(ingredients)
    allergen_text = "; ".join(_clean_allergen_statements(allergen_statements))
    return IngredientExtraction(
        region=region,
        raw_text=raw,
        allergen_text=allergen_text,
        allergen_confidence=(
            sum(allergen_confidences) / len(allergen_confidences) if allergen_confidences else None
        ),
        source_rows=source_rows,
        confidence=(
            sum(ingredient_confidences) / len(ingredient_confidences)
            if ingredient_confidences
            else None
        ),
    )


def merge_ingredient_allergen_evidence(
    primary: IngredientExtraction, fallback: IngredientExtraction
) -> IngredientExtraction:
    """Keep the chosen ingredient crop while recovering explicit package allergen evidence."""
    primary_has_payload = bool(_allergen_payload_tokens(primary.allergen_text))
    fallback_has_payload = bool(_allergen_payload_tokens(fallback.allergen_text))
    if primary_has_payload or not fallback_has_payload:
        if primary.allergen_text and not primary_has_payload:
            return primary.model_copy(update={"allergen_text": "", "allergen_confidence": None})
        return primary
    return primary.model_copy(
        update={
            "allergen_text": fallback.allergen_text,
            "allergen_confidence": fallback.allergen_confidence,
        }
    )


def merge_nutrition_evidence(
    primary: NutritionExtraction, fallback: NutritionExtraction
) -> NutritionExtraction:
    """Merge complementary crop and full-label rows without combining raw OCR text."""
    merged_basis = primary.basis
    if merged_basis == "UNKNOWN" or (
        merged_basis == "PER_SERVING" and fallback.basis in {"PER_100_G", "PER_100_ML"}
    ):
        merged_basis = fallback.basis

    merged_serving_value = primary.serving_size_value or fallback.serving_size_value
    merged_serving_unit = primary.serving_size_unit or fallback.serving_size_unit

    raw_columns = list(dict.fromkeys([*primary.table_columns, *fallback.table_columns]))
    serving_synonyms = ("per serving", "per cookie", "per biscuit", "per piece", "per portion")
    first_col = raw_columns[0].lower() if raw_columns else ""
    if any(first_col == s for s in serving_synonyms):
        canonical_order = (
            *serving_synonyms,
            "per 100 g",
            "per 100 ml",
            "% RDA per serving",
            "% DV",
        )
    else:
        canonical_order = (
            "per 100 g",
            "per 100 ml",
            *serving_synonyms,
            "% RDA per serving",
            "% DV",
        )
    columns = [col for col in canonical_order if col in raw_columns] + [
        col for col in raw_columns if col not in canonical_order
    ]

    norm_primary_rows = _normalize_serving_columns(
        list(primary.table_rows),
        basis=merged_basis,
        columns=columns,
        serving_value=merged_serving_value,
        serving_unit=merged_serving_unit,
    )
    norm_fallback_rows = _normalize_serving_columns(
        list(fallback.table_rows),
        basis=merged_basis,
        columns=columns,
        serving_value=merged_serving_value,
        serving_unit=merged_serving_unit,
    )

    selected: dict[str, NutritionRow] = {}
    order: list[str] = []
    for row in [*norm_primary_rows, *norm_fallback_rows]:
        key = row.canonical_label or row.label
        if key not in selected:
            order.append(key)
            selected[key] = row
            continue
        if _nutrition_row_evidence_score(row) > _nutrition_row_evidence_score(selected[key]):
            selected[key] = row

    rows = [selected[key] for key in order]
    rows = _normalize_serving_columns(
        rows,
        basis=merged_basis,
        columns=columns,
        serving_value=merged_serving_value,
        serving_unit=merged_serving_unit,
    )
    has_pct_col = any("%" in col or "rda" in col.lower() or "dv" in col.lower() for col in columns)
    source_has_pct = any(
        "%" in c.lower() or "rda" in c.lower() or "dv" in c.lower()
        for c in primary.table_columns + fallback.table_columns
    )
    if not has_pct_col and source_has_pct:
        columns.append("% RDA per serving")
    rows = _populate_parsed_values(
        rows,
        basis=merged_basis,
        columns=columns,
        serving_value=merged_serving_value,
        serving_unit=merged_serving_unit,
    )
    confidences = [row.confidence for row in rows if row.confidence is not None]
    coverage = min(1.0, 0.55 + 0.05 * len(rows))
    confidence = (
        (sum(confidences) / len(confidences)) * coverage if confidences else primary.confidence
    )
    return primary.model_copy(
        update={
            "table_rows": rows,
            "table_columns": columns,
            "basis": merged_basis,
            "serving_size_value": merged_serving_value,
            "serving_size_unit": merged_serving_unit,
            "confidence": confidence,
        }
    )


def _nutrition_row_evidence_score(row: NutritionRow) -> float:
    non_rda_values = sum(unit != "%" for unit in row.units)
    if non_rda_values > 2:
        return -1.0
    for v in row.values:
        try:
            fv = float(v)
            if fv > 200.0 and row.canonical_label in {
                "fibre",
                "total sugar",
                "protein",
                "total fat",
                "saturated fat",
                "salt",
            }:
                return -10.0
        except ValueError:
            pass
    explicit_units = sum(bool(unit and unit != "%") for unit in row.units)
    return (row.confidence or 0.0) + min(non_rda_values, 2) * 0.12 + min(explicit_units, 2) * 0.04


_NON_PRODUCT_BOILERPLATE_TERMS = (
    "storage",
    "store in",
    "airtight",
    "container",
    "once opened",
    "cool",
    "dry place",
    "best before",
    "front of pack",
    "typical values",
    "average values",
    "valeurs moyennes",
    "gemiddelde waarden",
    "of which",
    "saturates",
    "verzadigde",
    "vetzuren",
    "matieres grasses",
    "glucides",
    "koolhydraten",
    "eiwitten",
    "vezels",
    "zout",
    "per cookie",
    "per serve",
    "per serving",
    "servings per",
    "approximate values",
    "proximate values",
    "dietary allowance",
    "calorie needs",
    "all taxes",
    "see stamp",
    "brewed by",
    "specially brewed",
    "manufactured by",
    "marketed by",
    "packed by",
    "distributed by",
    "average",
    "valies",
    "values",
    "serving suggestion",
    "best served",
    "keep refrigerated",
    "shake well",
    "sold by weight",
    "partially produced",
    "genetic engineering",
    "contents may settle",
    "all rights reserved",
    "people love",
    "making food",
)

_NON_PRODUCT_TABLE_TOKENS = frozenset(
    {
        "average",
        "valies",
        "values",
        "typical",
        "approximate",
        "proximate",
        "mean",
        "amount",
        "daily",
        "total",
        "basis",
        "facts",
        "information",
        "table",
        "chart",
        "panel",
        "cookie",
        "cookies",
        "biscuit",
        "biscuits",
        "portion",
        "piece",
        "pack",
        "package",
        "serve",
        "serving",
        "per",
        "nutritio",
        "nutrition",
        "nutritional",
        "nutrient",
        "energy",
        "calories",
        "calorie",
    }
)

_SLOGAN_PROSE_PATTERNS = (
    re.compile(
        r"\b(?:people|we|you|everyone|our\s+family)\s+(?:love|loves|make|makes|making|believe|believes|care|cares|enjoy|enjoys|crave|craves|bring|share|sharing)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:making|loving|sharing|caring|enjoying)\s+(?:food|meals|moments|memories|life|quality)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:serving\s*suggestion|best\s*served|keep\s*refrigerated|shake\s*well|sold\s*by\s*weight)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:partially\s*produced|genetic\s*engineering|contents\s*may\s*settle|all\s*rights\s*reserved)\b",
        re.I,
    ),
)


def _is_noisy_or_non_product_candidate(value: str) -> bool:
    """Reject raw OCR table headers, storage instructions, slogans, or garbled tokens."""
    stripped = value.strip()
    if not stripped:
        return True
    if any(c in stripped for c in (";", "(", ")", "[", "]", "{", "}", "_", "*", "•", "·")):
        return True
    if "/" in stripped or re.search(r"\S&\S", stripped):
        return True
    lowered = stripped.casefold()
    if any(term in lowered for term in _NON_PRODUCT_BOILERPLATE_TERMS):
        return True
    if any(pat.search(lowered) for pat in _SLOGAN_PROSE_PATTERNS):
        return True
    if "," in stripped and any(
        ing in lowered
        for ing in (
            "sugar",
            "syrup",
            "oil",
            "flour",
            "wheat",
            "oat",
            "oats",
            "salt",
            "milk",
            "water",
            "seed",
            "seeds",
            "cranberries",
            "cherries",
        )
    ):
        return True
    if re.search(r"\b(?:brewed|packed|marketed|manufactured)by\b", lowered):
        return True
    tokens = re.findall(r"[A-Za-z]+", stripped)
    if not tokens:
        return True
    if all(tok.casefold() in _NON_PRODUCT_TABLE_TOKENS for tok in tokens):
        return True
    if len(tokens) <= 3 and any(
        tok.casefold() in {"average", "valies", "values", "approximate", "proximate"}
        for tok in tokens
    ):
        return True
    # Generalized single-token filtering: reject solitary verbs, imperatives, adjectives,
    # or truncated fragments that do not constitute a standalone product name
    if len(tokens) == 1:
        tok_low = tokens[0].casefold()
        if tok_low in {
            "live",
            "better",
            "best",
            "good",
            "fresh",
            "drink",
            "eat",
            "enjoy",
            "love",
            "taste",
            "feel",
            "try",
            "keep",
            "store",
            "shake",
            "open",
            "serve",
            "use",
            "see",
            "visit",
            "follow",
            "scan",
            "recycle",
            "dispose",
            "crush",
            "batch",
            "average",
            "typical",
            "values",
            "facts",
            "information",
            "original",
            "classic",
            "premium",
            "quality",
            "natural",
            "healthy",
        }:
            return True
        if len(tok_low) <= 4 and tok_low not in {
            "milk",
            "silk",
            "bulk",
            "oats",
            "corn",
            "rice",
            "chai",
            "tea",
            "soya",
            "tofu",
            "peps",
            "cola",
        }:
            return True

    for token in tokens:
        t_low = token.casefold()
        if t_low in {"per", "serve", "serving", "rda", "snf"}:
            return True
        if len(token) >= 3 and re.fullmatch(r"[A-Z]{2,}[a-z]+|[a-z]+[A-Z][A-Za-z]*", token):
            return True
        if len(token) >= 12 and (token.isupper() or token.islower()):
            return True
        if re.search(r"(?:tlk|tkl|wt|ttex|ttet|v)\b", t_low) and t_low not in {
            "milk",
            "silk",
            "bulk",
            "rev",
            "bev",
        }:
            return True
    return False


def extract_front_candidates(
    lines: list[OCRLine], view_id: str
) -> tuple[list[TextCandidate], list[TextCandidate]]:
    usable: list[tuple[OCRLine, str]] = []
    quantity_pattern = re.compile(
        r"^(?:\d+(?:[.,]\d+)?\s*(?:g|ml|kg|l|oz|kcal|kj|mg|mcg|ct|pk|pack|pcs)?|"
        r"(?:net\s*wt|net\s*weight|net\s*quantity|batch\s*no|mfg|exp|use\s*by|mrp).*)$",
        re.I,
    )
    for line in lines:
        if line.bounding_box is None:
            continue
        if line.confidence is not None and line.confidence < 0.58:
            continue
        cleaned = _METADATA_TAIL.sub("", line.text).strip(" ·|,:;-")
        lowered = cleaned.casefold()
        if not cleaned or len(cleaned) < 3:
            continue
        if line.text.rstrip().endswith(",") and len(cleaned.split()) == 1:
            continue
        if _is_governed_non_product_phrase(cleaned) or _is_noisy_or_non_product_candidate(cleaned):
            continue
        if any(
            term in lowered
            for term in (
                *_FRONT_CANDIDATE_NUTRIENT_TERMS,
                "ingredient",
                "contains",
                "allergen",
                "quantity",
                "brand",
                "logo",
                "trademark",
            )
        ):
            continue
        if _match_nutrient(cleaned) is not None:
            continue
        if VALUE_PATTERN.fullmatch(cleaned):
            continue
        if "%" in cleaned or quantity_pattern.match(cleaned):
            continue
        readable_characters = sum(c.isalpha() or c.isspace() or c.isdigit() for c in cleaned)
        if readable_characters / len(cleaned) < 0.8:
            continue
        usable.append((line, cleaned))
    grouped = _front_phrases(usable)
    filtered_grouped = [
        item
        for item in grouped
        if not _is_governed_non_product_phrase(item[0])
        and not _is_noisy_or_non_product_candidate(item[0])
    ]
    ranked = sorted(filtered_grouped, key=lambda item: item[2], reverse=True)[:8]
    candidates = [
        TextCandidate(
            value=cleaned,
            confidence=min(0.9, confidence * 0.9),
            method=DetectionMethod.OCR_LAYOUT,
            source_view_id=view_id,
        )
        for cleaned, confidence, _score in ranked
    ]
    supported_brand_candidates: list[TextCandidate] = []
    for line in lines:
        explicit_brand = _EXPLICIT_BRAND.search(line.text)
        if explicit_brand is not None:
            value = explicit_brand.group(1).strip(" ,;:-")
            if value and not _is_governed_non_product_phrase(value):
                supported_brand_candidates.append(
                    TextCandidate(
                        value=value,
                        confidence=min(0.9, (line.confidence or 0.4) * 0.9),
                        method=DetectionMethod.OCR_LAYOUT,
                        source_view_id=view_id,
                    )
                )
        if not _BRAND_LEGAL_CONTEXT.search(line.text):
            continue
        value = _brand_from_legal_context(line.text)
        if not value or _is_governed_non_product_phrase(value):
            continue
        supported_brand_candidates.append(
            TextCandidate(
                value=value,
                confidence=min(0.9, (line.confidence or 0.4) * 0.9),
                method=DetectionMethod.OCR_LAYOUT,
                source_view_id=view_id,
            )
        )
    brand_candidates: list[TextCandidate] = []
    seen_brands: set[str] = set()
    # Product-rank position is not brand evidence. Only explicit package
    # wording or legal/trademark context may populate the brand list.
    for candidate in supported_brand_candidates:
        key = _normalize_label(candidate.value)
        if not key or key in seen_brands:
            continue
        seen_brands.add(key)
        brand_candidates.append(candidate)
    return brand_candidates[:3], candidates[:4]


def _is_governed_non_product_phrase(value: str) -> bool:
    """Reject a bounded vocabulary of headings/slogans, including mild OCR noise."""
    compact = re.sub(r"[^a-z0-9]", "", _normalize_label(value))
    if not compact:
        return True
    for phrase in (*_DOCUMENT_SECTION_ALIASES, *_MARKETING_SLOGAN_ALIASES):
        governed = re.sub(r"[^a-z0-9]", "", phrase)
        if governed in compact:
            return True
        prefix = compact[: min(len(compact), len(governed) + 4)]
        if len(prefix) >= 8 and SequenceMatcher(None, prefix, governed).ratio() >= 0.8:
            return True
    return False


def _brand_from_legal_context(value: str) -> str:
    """Recover only a bounded name adjacent to explicit brand/legal wording."""
    prefix = re.sub(
        r"\b(?:(?:regi)?stered\s+trademark|registered\s+trademark|logo|trademark)\b.*$",
        "",
        value,
        flags=re.I,
    ).strip(" ,;:-")
    if not prefix or len(prefix) < 3 or prefix.islower():
        return ""
    parts = [part.strip(" ,;:-") for part in prefix.split(",") if part.strip(" ,;:-")]
    normalized_prefix = _normalize_label(parts[0]) if parts else ""
    primary_name = re.split(r"\s+-\s+", parts[0], maxsplit=1)[0] if parts else ""
    normalized_primary = _normalize_label(primary_name)
    for part in reversed(parts[1:]):
        normalized = _normalize_label(part)
        if (
            1 <= len(normalized.split()) <= 5
            and SequenceMatcher(None, normalized, normalized_primary).ratio() >= 0.86
        ):
            return primary_name[:80]
        if 1 <= len(normalized.split()) <= 5 and normalized in normalized_prefix:
            return part[:80]
    return prefix[:80]


def extract_dates(lines: list[OCRLine], view_id: str) -> list[DateCandidate]:
    candidates: list[DateCandidate] = []
    ordered = _ordered_lines(lines)
    for index, line in enumerate(ordered):
        lowered = line.text.casefold()
        date_type = next((value for label, value in DATE_LABELS.items() if label in lowered), None)
        if date_type is None and index > 0:
            previous = ordered[index - 1].text.casefold()
            date_type = next(
                (value for label, value in DATE_LABELS.items() if label in previous), None
            )
        if date_type is None:
            continue
        for match in DATE_PATTERN.finditer(line.text):
            raw = match.group(1)
            parsed, ambiguous = _parse_date(raw)
            base = line.confidence if line.confidence is not None else 0.4
            candidates.append(
                DateCandidate(
                    date_type=date_type,  # type: ignore[arg-type]
                    raw_text=raw,
                    parsed_date=parsed,
                    confidence=min(1.0, base + 0.1),
                    ambiguous=ambiguous,
                    source_view_id=view_id,
                )
            )
    return candidates


def _match_nutrient_from_units(
    value_matches: list[re.Match[str]],
) -> tuple[_NutrientSpec, float] | None:
    """Resolve only units that uniquely identify a governed nutrient."""
    units = {_normalize_unit(match.group(2)) for match in value_matches if match.group(2)}
    if units.intersection({"kcal", "kj"}):
        energy = next(spec for spec in NUTRIENT_SPECS if spec.canonical == "energy")
        return energy, 0.86
    return None


def _deduplicate_nutrition_rows(rows: list[NutritionRow]) -> list[NutritionRow]:
    selected: dict[str, NutritionRow] = {}
    order: list[str] = []
    for row in rows:
        key = row.canonical_label or row.label
        score = (row.confidence or 0.0) + 0.025 * len(row.values)
        score += 0.02 * sum(bool(unit) for unit in row.units)
        if key == "energy" and "kcal" in row.units:
            score += 0.05
        existing = selected.get(key)
        existing_score = -1.0
        if existing is not None:
            existing_score = (existing.confidence or 0.0) + 0.025 * len(existing.values)
            existing_score += 0.02 * sum(bool(unit) for unit in existing.units)
            if key == "energy" and "kcal" in existing.units:
                existing_score += 0.05
        if existing is None:
            order.append(key)
        if score > existing_score:
            selected[key] = row
    return [selected[key] for key in order]


def _normalize_serving_columns(
    rows: list[NutritionRow],
    *,
    basis: str,
    columns: list[str] | None = None,
    serving_value: str | None,
    serving_unit: str | None,
) -> list[NutritionRow]:
    if basis not in {"PER_100_G", "PER_100_ML"} or serving_value is None:
        return rows
    expected_basis_unit = "g" if basis == "PER_100_G" else "ml"
    if serving_unit != expected_basis_unit:
        return rows

    normalized_rows: list[NutritionRow] = []
    specs = {spec.canonical: spec for spec in NUTRIENT_SPECS}
    for row in rows:
        spec = specs.get(row.canonical_label or row.label)
        values = list(row.values)
        units = list(row.units)
        if spec is not None and len(spec.units) == 1:
            expected_unit = next(iter(spec.units))
            for index in range(len(values)):
                if index >= len(units):
                    units.append("")
                if units[index]:
                    continue
                if index >= 2:
                    units[index] = "%"
                    continue
                if expected_unit in {"g", "mg", "kcal", "kj"}:
                    units[index] = expected_unit

        normalized_rows.append(row.model_copy(update={"values": values, "units": units}))
    return normalized_rows


def _nutrition_header_text(lines: list[OCRLine]) -> str:
    boxed = [line for line in lines if line.bounding_box is not None]
    if not boxed:
        return _normalize_label(" ".join(line.text for line in lines[:8]))
    top = min(line.bounding_box.y for line in boxed if line.bounding_box is not None)
    bottom = max(
        line.bounding_box.y + line.bounding_box.height
        for line in boxed
        if line.bounding_box is not None
    )
    cutoff = top + (bottom - top) * 0.42
    table_anchor_ys = [
        line.bounding_box.y
        for line in boxed
        if line.bounding_box is not None
        and (
            any(
                marker in line.text.casefold()
                for marker in (
                    "nutrition",
                    "nutrient",
                    "information",
                    "typical values",
                    "valeurs moyennes",
                    "gemiddelde waarden",
                )
            )
            or _match_nutrient(line.text) is not None
        )
    ]
    table_top = min(table_anchor_ys, default=None)
    table_cutoff = (
        table_top + max(180.0, (bottom - table_top) * 0.42) if table_top is not None else cutoff
    )
    header = [
        line.text
        for line in boxed
        if line.bounding_box is not None
        and (
            line.bounding_box.y + line.bounding_box.height / 2 <= cutoff
            or (
                table_top is not None
                and table_top - 80.0
                <= line.bounding_box.y + line.bounding_box.height / 2
                <= table_cutoff
            )
        )
    ]
    raw_header = " ".join(header)
    cleaned_header = re.sub(r"[|/\\;]", " ", raw_header)
    return _normalize_label(cleaned_header)


def _serving_size_from_layout(lines: list[OCRLine]) -> tuple[str | None, str | None]:
    size_lines = [
        line
        for line in lines
        if any(
            marker in _normalize_label(line.text)
            for marker in ("size", "cookie", "biscuit", "piece", "portion")
        )
    ]
    for size_line in size_lines:
        if size_line.bounding_box is None:
            continue
        size_center = size_line.bounding_box.y + size_line.bounding_box.height / 2
        nearby: list[tuple[float, re.Match[str]]] = []
        for line in lines:
            if line.bounding_box is None:
                continue
            match = re.search(
                r"(?:\b|\()(\d+(?:[.,]\d+)?)\s*(mml|m[l1it]|g)(?:\b|\))",
                line.text,
                re.I,
            )
            if match is None:
                continue
            if match.group(1) in {"100", "1001"} and "size" not in _normalize_label(size_line.text):
                continue
            center = line.bounding_box.y + line.bounding_box.height / 2
            distance = abs(center - size_center)
            tolerance = max(size_line.bounding_box.height, line.bounding_box.height) * 1.8
            if distance <= tolerance:
                nearby.append((distance, match))
        if nearby:
            match = min(nearby, key=lambda item: item[0])[1]
            unit = match.group(2).casefold()
            return (
                match.group(1).replace(",", "."),
                "ml" if unit in {"mml", "m1", "mi", "mt"} else unit,
            )
    return None, None


def _front_phrases(
    usable: list[tuple[OCRLine, str]],
) -> list[tuple[str, float, tuple[float, float, int]]]:
    """Join large, overlapping front-label words without joining document sections."""
    clusters: list[list[tuple[OCRLine, str]]] = []
    for item in sorted(
        usable,
        key=lambda value: (
            value[0].bounding_box.y if value[0].bounding_box is not None else 0,
            value[0].bounding_box.x if value[0].bounding_box is not None else 0,
        ),
    ):
        line, _ = item
        box = line.bounding_box
        if box is None:
            continue
        center = box.y + box.height / 2
        target: list[tuple[OCRLine, str]] | None = None
        for cluster in clusters:
            cluster_boxes = [
                candidate for value in cluster if (candidate := value[0].bounding_box) is not None
            ]
            if not cluster_boxes:
                continue
            cluster_center = sum(value.y + value.height / 2 for value in cluster_boxes) / len(
                cluster_boxes
            )
            largest_height = max([box.height, *(value.height for value in cluster_boxes)])
            if abs(center - cluster_center) <= max(12.0, largest_height * 0.7):
                target = cluster
                break
        if target is None:
            clusters.append([item])
        else:
            target.append(item)

    phrases: list[tuple[str, float, tuple[float, float, int]]] = []
    seen: set[str] = set()
    for cluster in clusters:
        ordered = sorted(
            cluster,
            key=lambda value: value[0].bounding_box.x if value[0].bounding_box is not None else 0,
        )
        text = " ".join(value[1] for value in ordered).strip()
        normalized = _normalize_label(text)
        if not normalized or normalized in seen or len(normalized) > 80:
            continue
        seen.add(normalized)
        confidences = [value[0].confidence or 0.35 for value in ordered]
        boxes = [candidate for value in ordered if (candidate := value[0].bounding_box) is not None]
        if not boxes:
            continue
        height = max(value.y + value.height for value in boxes) - min(value.y for value in boxes)
        top = min(value.y for value in boxes)
        word_count = len(normalized.split())
        phrases.append(
            (
                text,
                sum(confidences) / len(confidences),
                (height + min(word_count, 5) * 5.0, -top, word_count),
            )
        )
    return phrases


def _match_nutrient(raw_label: str) -> tuple[_NutrientSpec, float] | None:
    candidates = [raw_label]
    if "/" in raw_label:
        candidates.extend(seg.strip() for seg in raw_label.split("/") if seg.strip())
    best: tuple[_NutrientSpec, float] | None = None
    best_alias_len = 0
    for candidate in candidates:
        normalized = _normalize_label(candidate)
        if not normalized or len(normalized) > 80:
            continue
        for spec in NUTRIENT_SPECS:
            for alias in spec.aliases:
                normalized_alias = _normalize_label(alias)
                if normalized == normalized_alias:
                    score = 1.0
                elif (
                    len(normalized_alias) >= 6
                    and (
                        " " in normalized_alias
                        or normalized_alias not in {"sugar", "sugars", "fat"}
                        or "of which" in normalized
                    )
                    and re.search(rf"(?:^|\s){re.escape(normalized_alias)}(?:$|\s)", normalized)
                ):
                    score = 0.94 + min(0.04, len(normalized_alias) * 0.002)
                else:
                    score = SequenceMatcher(None, normalized, normalized_alias).ratio()
                if score >= 0.78 and (
                    best is None
                    or score > best[1]
                    or (abs(score - best[1]) <= 1e-6 and len(normalized_alias) > best_alias_len)
                ):
                    best = (spec, score)
                    best_alias_len = len(normalized_alias)
    return best


def _normalize_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = re.sub(r"[^a-z0-9%]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_unit(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.casefold().replace("µ", "u")
    return "mcg" if normalized == "ug" else normalized


def _cluster_rows(lines: list[OCRLine]) -> list[list[OCRLine]]:
    if not lines:
        return []
    boxed = [line for line in lines if line.bounding_box is not None]
    unboxed = [[line] for line in lines if line.bounding_box is None]
    if not boxed:
        return unboxed
    heights = [line.bounding_box.height for line in boxed if line.bounding_box is not None]
    tolerance = max(6.0, median(heights) * 0.6) if heights else 10.0
    clusters: list[list[OCRLine]] = []
    centers: list[float] = []
    for line in sorted(
        boxed,
        key=lambda item: (
            item.bounding_box.y if item.bounding_box is not None else 0,
            item.bounding_box.x if item.bounding_box is not None else 0,
        ),
    ):
        box = _required_box(line)
        center = box.y + box.height / 2
        target = next(
            (index for index, value in enumerate(centers) if abs(center - value) <= tolerance),
            None,
        )
        if target is None:
            clusters.append([line])
            centers.append(center)
        else:
            clusters[target].append(line)
            centers[target] = sum(
                _required_box(item).y + _required_box(item).height / 2 for item in clusters[target]
            ) / len(clusters[target])
    return clusters + unboxed


def _required_box(line: OCRLine) -> Box:
    box = line.bounding_box
    if box is None:
        raise ValueError("Expected a positioned OCR line.")
    return box


def _prune_overlapping_value_lines(lines: list[OCRLine]) -> list[OCRLine]:
    """Keep the geometrically most plausible value when adjacent rows overlap.

    OCR occasionally loses a nutrient label while retaining that row's wide
    value box. The orphan then joins the preceding nutrient. Competing numeric
    boxes in the same horizontal lane are resolved using the same perspective
    preference as row clustering: values slightly above a label are preferred
    over values from the following printed row.
    """
    label_match = next(
        (
            (line, matched[0])
            for line in lines
            if (matched := _match_nutrient(line.text)) is not None
        ),
        None,
    )
    if label_match is None or label_match[0].bounding_box is None:
        return lines
    label, spec = label_match
    assert label.bounding_box is not None
    label_lower = label.text.casefold()
    numeric = [
        line
        for line in lines
        if line is not label
        and line.bounding_box is not None
        and VALUE_PATTERN.search(line.text) is not None
    ]
    groups: list[list[OCRLine]] = []
    for line in numeric:
        box = line.bounding_box
        if box is None:
            continue
        target = None
        for group in groups:
            other = group[0].bounding_box
            if other is None:
                continue
            overlap = max(
                0.0,
                min(box.x + box.width, other.x + other.width) - max(box.x, other.x),
            )
            if overlap / max(1.0, min(box.width, other.width)) >= 0.65:
                target = group
                break
        if target is None:
            groups.append([line])
        else:
            target.append(line)

    selected_ids: set[int] = set()
    anchor_center_y = (
        label.bounding_box.y + label.bounding_box.height / 2
        if label.bounding_box is not None
        else 0.0
    )
    for group in groups:

        def score(item: OCRLine) -> float:
            assert item.bounding_box is not None
            item_center_y = item.bounding_box.y + item.bounding_box.height / 2
            offset = anchor_center_y - item_center_y
            penalty = 0.0
            cleaned = _clean_ocr_value_delimiters(item.text)
            item_units = {
                _normalize_unit(m.group(2)) for m in VALUE_PATTERN.finditer(cleaned) if m.group(2)
            }
            non_pct_units = {u for u in item_units if u and u != "%"}
            if non_pct_units and not non_pct_units.intersection(spec.units):
                penalty += 200.0
            if (
                spec.canonical == "energy_kj"
                and "kcal" in non_pct_units
                and "kj" not in non_pct_units
            ):
                penalty += 200.0
            if spec.canonical == "energy" and (
                ("kcal" in label_lower and "kj" in non_pct_units and "kcal" not in non_pct_units)
                or ("kj" in label_lower and "kcal" in non_pct_units and "kj" not in non_pct_units)
            ):
                penalty += 120.0
            return abs(offset) + penalty

        selected_ids.add(id(min(group, key=score)))
    numeric_ids = {id(line) for line in numeric}
    return [line for line in lines if id(line) not in numeric_ids or id(line) in selected_ids]


def _clean_ocr_value_delimiters(text: str) -> str:
    cleaned = re.sub(r"(?:^|(?<=[^\w])|(?<=[a-zA-Z%]))[|/\\lI](?=\d)", " ", text)
    cleaned = re.sub(r"(?i)(kcal|kj|mg|mcg|µg|ug|ml|g|%)(?=[|/\\lI\d])", r"\1 ", cleaned)
    cleaned = re.sub(r"(?:^|(?<=[^\w])|(?<=[a-zA-Z%]))[|/\\lI](?=\d)", " ", cleaned)
    cleaned = re.sub(r"\b[sS](?=\d)", "5", cleaned)
    cleaned = re.sub(r"(?<=\d)[sS](?=[a-zA-Z%]|$)", "5", cleaned)
    cleaned = re.sub(r"\b[Jj](?=\d)", "1", cleaned)
    cleaned = re.sub(r"(?<=[a-zA-Z])(?=\d)", " ", cleaned)
    cleaned = re.sub(r"(?<=[a-zA-Z])(?:[oO0])(?=mg\b|g\b|ml\b)", " 0", cleaned)
    if re.search(r"\bM[z\d]", cleaned):
        cleaned = re.sub(r"\bM([z\d])", r"11\1", cleaned).replace("z", "2")
    return cleaned


def _is_reference_intake_footer(text: str) -> bool:
    return bool(
        re.search(
            r"\b(?:reference\s*intake|recommended\s*dietary\s*allowance\s*\(rda\)|daily\s*values?|adult\s*intake|average\s*adult|calorie\s*needs|basis\s*of\s*a\s*2000)\b",
            text,
            re.I,
        )
    )


def _cluster_nutrition_rows(lines: list[OCRLine]) -> list[list[OCRLine]]:
    """Use nutrient labels as row anchors with table tilt projection across width."""
    boxed = [line for line in lines if line.bounding_box is not None]
    if boxed:
        heights = [line.bounding_box.height for line in boxed if line.bounding_box is not None]
        med_h = float(median(heights))
        max_box_h = max(110.0, 1.7 * med_h)
    else:
        med_h, max_box_h = 30.0, 110.0

    # Filter out reference intake footer lines so dietary guideline footnotes
    # (e.g. 8400 kJ / 2000 kcal) do not become nutrient anchors or hijack rows.
    # Also filter out severely oversized multi-row merged OCR boxes.
    filtered: list[OCRLine] = []
    footer_seen = False
    for line in boxed:
        if _is_reference_intake_footer(line.text):
            footer_seen = True
        if not footer_seen:
            if line.bounding_box is not None and line.bounding_box.height > max_box_h:
                continue
            filtered.append(line)

    anchors: list[tuple[OCRLine, str]] = []
    unit_fallbacks: list[tuple[OCRLine, str]] = []
    for line in filtered:
        match = _match_nutrient(line.text)
        if match is None:
            cleaned = _clean_ocr_value_delimiters(line.text)
            first_val = VALUE_PATTERN.search(cleaned)
            if first_val is not None and first_val.start() > 0:
                match = _match_nutrient(line.text[: first_val.start()].strip(" :-|."))
        if match is None:
            cleaned = _clean_ocr_value_delimiters(line.text)
            value_matches = list(VALUE_PATTERN.finditer(cleaned))
            match = _match_nutrient_from_units(value_matches)
            if match is not None:
                unit_fallbacks.append((line, match[0].canonical))
            continue
        if match is None:
            continue
        canonical = match[0].canonical
        top = line.bounding_box.y  # type: ignore[union-attr]
        duplicate = next(
            (
                existing
                for existing in anchors
                if existing[1] == canonical and abs(existing[0].bounding_box.y - top) <= 28  # type: ignore[union-attr]
            ),
            None,
        )
        if duplicate is None:
            anchors.append((line, canonical))
        elif (line.confidence or 0.0) > (duplicate[0].confidence or 0.0):
            anchors[anchors.index(duplicate)] = (line, canonical)

    anchored_nutrients = {canonical for _line, canonical in anchors}
    for line, canonical in unit_fallbacks:
        if canonical not in anchored_nutrients:
            anchors.append((line, canonical))
            anchored_nutrients.add(canonical)

    if not anchors:
        return _cluster_rows(lines)

    anchors.sort(
        key=lambda item: (
            item[0].bounding_box.y + item[0].bounding_box.height / 2
            if item[0].bounding_box is not None
            else 0.0
        )
    )

    clusters: list[list[OCRLine]] = [[anchor] for anchor, _canonical in anchors]
    anchor_ids = {id(anchor) for anchor, _canonical in anchors}
    first_anchor_top = min(
        anchor.bounding_box.y for anchor, _canonical in anchors if anchor.bounding_box is not None
    )
    specs_by_canonical = {spec.canonical: spec for spec in NUTRIENT_SPECS}

    # Candidate numeric lines
    num_candidates: list[OCRLine] = []
    for line in filtered:
        if id(line) in anchor_ids:
            continue
        box = line.bounding_box
        if box is None:
            continue
        # Skip header lines located above table nutrient data
        if box.y < first_anchor_top - 40.0:
            continue
        # Skip pure parenthesized serving size header declarations like "(23g)"
        if re.match(r"^\(\s*\d+(?:\.\d+)?\s*(?:g|ml)\s*\)$", line.text.strip(), re.I):
            continue
        # Skip table title / serving size header lines
        if re.search(
            r"\b(?:nutrition\s*(?:facts|information)?|nutrient\s*information|servings?\s*size|sring\s*size|serving\s*suggestion)\b",
            line.text,
            re.I,
        ):
            continue
        cleaned = _clean_ocr_value_delimiters(line.text)
        if VALUE_PATTERN.search(cleaned) is not None:
            num_candidates.append(line)

    # Estimate horizontal table tilt slope across table width (dy / dx) from candidate rows
    slopes: list[float] = []
    for al, can in anchors:
        spec = specs_by_canonical.get(can)
        ay = al.bounding_box.y + al.bounding_box.height / 2  # type: ignore[union-attr]
        ax = al.bounding_box.x  # type: ignore[union-attr]
        for nl in num_candidates:
            cleaned = _clean_ocr_value_delimiters(nl.text)
            n_units = {
                _normalize_unit(m.group(2)) for m in VALUE_PATTERN.finditer(cleaned) if m.group(2)
            }
            ny = nl.bounding_box.y + nl.bounding_box.height / 2  # type: ignore[union-attr]
            nx = nl.bounding_box.x  # type: ignore[union-attr]
            dx = nx - ax
            dy = ny - ay
            unit_compatible = (n_units and spec and n_units.intersection(spec.units)) or (
                can in ("energy", "energy_kj") and not n_units
            )
            if dx > 120 and abs(dy / dx) < 0.25 and unit_compatible and abs(dy) <= 35.0:
                slopes.append(dy / dx)

    median_slope = float(median(slopes)) if slopes else 0.0

    for line in num_candidates:
        box = line.bounding_box
        if box is None:
            continue
        cleaned = _clean_ocr_value_delimiters(line.text)
        line_units = {
            _normalize_unit(m.group(2)) for m in VALUE_PATTERN.finditer(cleaned) if m.group(2)
        }
        non_pct_units = {u for u in line_units if u and u != "%"}
        ny = box.y + box.height / 2
        nx = box.x

        scores: list[float] = []
        for _idx, (anchor, canonical) in enumerate(anchors):
            anchor_box = anchor.bounding_box
            if anchor_box is None:
                scores.append(float("inf"))
                continue
            ay = anchor_box.y + anchor_box.height / 2
            ax = anchor_box.x
            proj_y = ny - median_slope * (nx - ax)
            diff = abs(proj_y - ay)
            spec = specs_by_canonical.get(canonical)
            unit_penalty = 0.0
            if non_pct_units and spec is not None and not non_pct_units.intersection(spec.units):
                unit_penalty = 120.0
            scores.append(diff + unit_penalty)

        target = min(range(len(scores)), key=scores.__getitem__)
        anchor_box = anchors[target][0].bounding_box
        ay = anchor_box.y + anchor_box.height / 2 if anchor_box else 0.0
        ax = anchor_box.x if anchor_box else 0.0
        proj_y = ny - median_slope * (nx - ax)

        # Enforce strict row bands between consecutive anchors
        prev_box = anchors[target - 1][0].bounding_box if target > 0 else None
        next_box = anchors[target + 1][0].bounding_box if target < len(anchors) - 1 else None
        prev_ay = (
            prev_box.y + prev_box.height / 2
            if prev_box is not None
            else ay - 1.2 * (anchor_box.height if anchor_box else 20.0)
        )
        next_ay = (
            next_box.y + next_box.height / 2
            if next_box is not None
            else ay + 1.2 * (anchor_box.height if anchor_box else 20.0)
        )
        top_bound = (prev_ay + ay) / 2
        bot_bound = (ay + next_ay) / 2

        # Check if line contains leading non-numeric text matching a different nutrient
        first_v = VALUE_PATTERN.search(cleaned)
        prefix = (
            cleaned[: first_v.start()].strip(" :-|.") if first_v and first_v.start() > 0 else ""
        )
        target_spec = specs_by_canonical.get(anchors[target][1])
        if (
            prefix
            and len(prefix) >= 3
            and target_spec
            and not any(alias in prefix.lower() for alias in target_spec.aliases)
        ):
            continue

        tolerance = max(40.0, (anchor_box.height if anchor_box else 0.0) * 0.85)
        if top_bound <= proj_y <= bot_bound and scores[target] <= tolerance:
            clusters[target].append(line)

    return sorted(
        clusters,
        key=lambda cluster: min(
            line.bounding_box.y for line in cluster if line.bounding_box is not None
        ),
    )


def _parse_date(raw: str) -> tuple[str | None, bool]:
    numeric = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2,4}))?", raw)
    if numeric:
        first, second, year = numeric.groups()
        ambiguous = int(first) <= 12 and int(second) <= 12
        if year is None or ambiguous:
            return None, ambiguous
        if len(year) == 2:
            year = f"20{year}"
        try:
            return datetime(int(year), int(second), int(first)).date().isoformat(), False
        except ValueError:
            return None, False
    for pattern in ("%d %b %Y", "%d %B %Y", "%b %Y", "%B %Y"):
        try:
            parsed = datetime.strptime(raw.title(), pattern)
            return parsed.date().isoformat() if "%d" in pattern else parsed.strftime("%Y-%m"), False
        except ValueError:
            continue
    return None, False


def _ordered_lines(lines: list[OCRLine]) -> list[OCRLine]:
    return sorted(
        lines,
        key=lambda line: (
            line.bounding_box.y if line.bounding_box is not None else float("inf"),
            line.bounding_box.x if line.bounding_box is not None else float("inf"),
        ),
    )


def _lines_in_region(lines: list[OCRLine], region: Region | None) -> list[OCRLine]:
    if region is None:
        return []
    box = region.bounding_box
    selected: list[OCRLine] = []
    for line in lines:
        if line.bounding_box is None:
            continue
        center_x = line.bounding_box.x + line.bounding_box.width / 2
        center_y = line.bounding_box.y + line.bounding_box.height / 2
        if box.x <= center_x <= box.x + box.width and box.y <= center_y <= box.y + box.height:
            selected.append(line)
    return selected
