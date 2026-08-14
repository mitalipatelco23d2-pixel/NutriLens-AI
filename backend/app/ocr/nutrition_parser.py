from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from statistics import median
from typing import Iterable, Protocol


MODEL_FIELDS = (
    "energy_100g",
    "fat_100g",
    "saturated_fat_100g",
    "sugars_100g",
    "fiber_100g",
    "proteins_100g",
    "salt_100g",
    "sodium_100g",
)

LABELS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("saturated_fat_100g", re.compile(r"\b(?:saturated\s+fat|sat\.?\s*fat|saturates)\b", re.I)),
    ("trans_fat_100g", re.compile(r"\btrans\s+fat\b", re.I)),
    ("added_sugars_100g", re.compile(r"\badded\s+sugars?\b", re.I)),
    ("fat_100g", re.compile(r"\b(?:total\s+fat|fat\s+total|fat)\b", re.I)),
    ("sugars_100g", re.compile(r"\b(?:(?:of\s+which|total)\s+)?sugars?\b", re.I)),
    ("fiber_100g", re.compile(r"\b(?:dietary\s+)?fib(?:er|re)\b", re.I)),
    ("proteins_100g", re.compile(r"\bproteins?\b", re.I)),
    ("salt_100g", re.compile(r"\bsalt\b", re.I)),
    ("sodium_100g", re.compile(r"\bsodium\b", re.I)),
    ("carbohydrates_100g", re.compile(r"\b(?:total\s+)?carbohydrates?\b|\bcarbs?\b", re.I)),
    ("cholesterol_100g", re.compile(r"\bcholesterol\b", re.I)),
    ("calcium_100g", re.compile(r"\bcalcium\b", re.I)),
    ("energy_100g", re.compile(r"\be?nergy\b|\bcalories?\b", re.I)),
)

VALUE_PATTERN = re.compile(
    r"(?<![\w])(?P<qualifier><\s*)?(?P<number>[0-9Oo]+(?:[.,][0-9Oo]+)?)\s*(?P<unit>kcal|kj|mg|g)\b",
    re.I,
)
OCR_100G_PATTERN = re.compile(
    r"(?<!\w)(?:[1I][0Oo][0Oo]\s*[gq9_]|tobq|ionq)(?!\w)", re.I
)
OCR_100ML_PATTERN = re.compile(
    r"(?<!\w)[1I][0Oo][0Oo]\s*m[lIi1](?!\w)", re.I
)
UNIT_BEFORE_VALUE_PATTERN = re.compile(
    r"(?:\(\s*)?(?P<unit>kcal|kj|mg|g)(?:\s*\))?\s*[:=\-]?\s*"
    r"(?P<qualifier><\s*)?(?P<number>[0-9Oo]+(?:[.,][0-9Oo]+)?)\b",
    re.I,
)


@dataclass(frozen=True)
class ParsedNutrient:
    value: float
    unit: str
    source_value: float
    source_unit: str
    basis: str
    qualifier: str | None = None


@dataclass
class NutritionParseResult:
    nutrients: dict[str, ParsedNutrient] = field(default_factory=dict)
    basis: str = "unknown"
    warnings: list[str] = field(default_factory=list)

    @property
    def normalized_model_values(self) -> dict[str, float]:
        if self.basis != "per_100g":
            return {}
        return {
            key: nutrient.value
            for key, nutrient in self.nutrients.items()
            if key in MODEL_FIELDS
        }


class SpatialWord(Protocol):
    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int
    block: int
    paragraph: int
    line: int

    @property
    def center_x(self) -> float: ...

    @property
    def center_y(self) -> float: ...


def basis_candidate_lines(text: str) -> list[str]:
    """Return contextual header snippets that conservatively support per-100-g."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    candidates: list[str] = []
    for index, line in enumerate(lines):
        if not OCR_100G_PATTERN.search(line):
            continue
        # OCR engines frequently emit "Amount", "per", and "100g" as three
        # separate detections, so retain two preceding lines in the header window.
        window_lines = lines[max(0, index - 2) : min(len(lines), index + 2)]
        window = " ".join(window_lines)
        header_context = bool(
            re.search(
                r"\b(?:nutrition(?:al)?(?:\s+information|\s+facts)?|"
                r"amount\s+per|values?\s+per|typical\s+values?)\b",
                window,
                re.I,
            )
        )
        nutrient_context = sum(
            bool(pattern.search(window)) for _, pattern in LABELS
        ) >= 1
        per_context = bool(re.search(r"\bper\b", window, re.I))
        if header_context or (per_context and nutrient_context):
            snippet = " | ".join(window_lines)
            if snippet not in candidates:
                candidates.append(snippet)
    return candidates


def _detect_basis(text: str) -> str:
    if OCR_100ML_PATTERN.search(text):
        return "per_100ml"
    if re.search(r"\bper\s+(?:serving|serve|portion)\b|\bamount\s+per\s+serving\b", text, re.I):
        return "per_serving"
    if basis_candidate_lines(text):
        return "per_100g"
    return "unknown"


def _number(raw: str) -> tuple[float, bool]:
    corrected = re.sub(r"\s*([.,])\s*", r"\1", raw)
    corrected = corrected.replace("O", "0").replace("o", "0").replace(",", ".")
    return float(corrected), corrected != raw.replace(",", ".")


def _segments(line: str) -> list[tuple[str, str]]:
    matches: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    for field_name, pattern in LABELS:
        for match in pattern.finditer(line):
            if any(match.start() < end and match.end() > start for start, end in occupied):
                continue
            matches.append((match.start(), match.end(), field_name))
            occupied.append((match.start(), match.end()))
    matches.sort()
    return [
        (field_name, line[end : matches[index + 1][0] if index + 1 < len(matches) else None])
        for index, (_, end, field_name) in enumerate(matches)
    ]


def _parse_segment(field_name: str, segment: str, basis: str) -> tuple[ParsedNutrient | None, list[str]]:
    warnings: list[str] = []
    if field_name == "energy_100g":
        # Common glyph confusion in a unit-bearing energy row (for example
        # "313Lcai"). Restrict this correction to the already identified field.
        corrected_segment = re.sub(
            r"(?<=\d)\s*[lI]ca[iIl1]\b", " kcal", segment, flags=re.I
        )
        if corrected_segment != segment:
            warnings.append("Corrected an OCR-confused kcal unit for energy_100g.")
        segment = corrected_segment
    segment_without_basis = re.sub(
        r"\b(?:per\s*)?100\s*(?:g|ml)\b|\bper\s+(?:serving|serve|portion)\b",
        " ",
        segment,
        flags=re.I,
    )
    matches = sorted(
        [
            *VALUE_PATTERN.finditer(segment_without_basis),
            *UNIT_BEFORE_VALUE_PATTERN.finditer(segment_without_basis),
        ],
        key=lambda match: match.start(),
    )
    if not matches:
        return None, warnings

    if field_name == "energy_100g":
        energy_matches = [m for m in matches if m.group("unit").lower() in {"kj", "kcal"}]
        if not energy_matches:
            return None, warnings
        match = next((m for m in energy_matches if m.group("unit").lower() == "kj"), energy_matches[0])
    else:
        mass_matches = [m for m in matches if m.group("unit").lower() in {"g", "mg"}]
        if not mass_matches:
            return None, warnings
        match = mass_matches[0]

    source_value, corrected = _number(match.group("number"))
    source_unit = match.group("unit").lower()
    if corrected:
        warnings.append(f"Corrected an OCR letter O to zero for {field_name}.")
    qualifier = "less_than" if match.group("qualifier") else None
    if qualifier:
        warnings.append(f"The value for {field_name} is an upper-bound estimate.")

    value = source_value
    unit = source_unit
    if source_unit == "mg":
        value = source_value / 1000
        unit = "g"
    elif source_unit == "kcal":
        value = source_value * 4.184
        unit = "kJ"
    elif source_unit == "kj":
        unit = "kJ"

    return ParsedNutrient(
        value=round(value, 6),
        unit=unit,
        source_value=source_value,
        source_unit=source_unit,
        basis=basis,
        qualifier=qualifier,
    ), warnings


def _field_for_row(text: str) -> str | None:
    normalized = re.sub(r"[^a-z]", "", text.casefold())
    # Check the specific fat subtypes before the generic word "fat". OCR often
    # damages the first character while leaving the generic suffix intact.
    for field_name, alias in (
        ("saturated_fat_100g", "saturatedfat"),
        ("trans_fat_100g", "transfat"),
    ):
        window = normalized[: len(alias) + 4]
        if alias in normalized or SequenceMatcher(None, alias, window).ratio() >= 0.68:
            return field_name
    matches: list[tuple[int, int, str]] = []
    for field_name, pattern in LABELS:
        match = pattern.search(text)
        if match:
            matches.append((match.start(), -(match.end() - match.start()), field_name))
    if matches:
        return min(matches)[2]
    aliases = (
        ("added_sugars_100g", "addedsugar"),
        ("sugars_100g", "totalsugar"),
        ("fat_100g", "totalfat"),
        ("carbohydrates_100g", "totalcarbohydrate"),
        ("carbohydrates_100g", "carbohydrates"),
        ("fiber_100g", "dietaryfibre"),
        ("fiber_100g", "dietaryfiber"),
        ("cholesterol_100g", "cholesterol"),
        ("calcium_100g", "calcium"),
        ("sodium_100g", "sodium"),
        ("proteins_100g", "protein"),
        ("energy_100g", "energy"),
        ("energy_100g", "calories"),
    )
    alpha_tokens = re.findall(r"[a-z]+", text.casefold())
    for field_name, alias in aliases:
        window = normalized[: len(alias) + 4]
        token_similarity = max(
            (SequenceMatcher(None, alias, token).ratio() for token in alpha_tokens),
            default=0.0,
        )
        if (
            alias in normalized
            or SequenceMatcher(None, alias, window).ratio() >= 0.72
            or token_similarity >= 0.72
        ):
            return field_name
    if re.search(r"\b[wh]oteln\b", text, re.I):
        return "proteins_100g"
    return None


def _group_spatial_rows(words: Iterable[SpatialWord]) -> list[list[SpatialWord]]:
    usable = [word for word in words if word.text.strip() and word.height > 0]
    if not usable:
        return []
    slope = _estimate_table_row_slope(usable)
    return _cluster_spatial_rows(usable, slope=slope, tolerance_factor=0.55)


def _cluster_spatial_rows(
    words: Iterable[SpatialWord], *, slope: float, tolerance_factor: float
) -> list[list[SpatialWord]]:
    usable = [word for word in words if word.text.strip() and word.height > 0]
    if not usable:
        return []
    tolerance = max(7.0, median(word.height for word in usable) * tolerance_factor)
    rows: list[list[SpatialWord]] = []
    centers: list[float] = []
    for word in sorted(usable, key=lambda item: item.center_y - slope * item.center_x):
        adjusted_y = word.center_y - slope * word.center_x
        matches = [
            (abs(adjusted_y - center), index)
            for index, center in enumerate(centers)
            if abs(adjusted_y - center) <= tolerance
        ]
        if matches:
            _, index = min(matches)
            rows[index].append(word)
            centers[index] = median(
                item.center_y - slope * item.center_x for item in rows[index]
            )
        else:
            rows.append([word])
            centers.append(adjusted_y)
    ordered = sorted(zip(centers, rows), key=lambda item: item[0])
    return [sorted(row, key=lambda word: word.left) for _, row in ordered]


def _estimate_table_row_slope(words: Iterable[SpatialWord]) -> float:
    """Estimate tilt from trusted multi-token label phrases, not accidental rows."""
    usable = list(words)
    if len(usable) < 4:
        return 0.0
    phrase_aliases = {
        "nutritionalinformation",
        "nutritioninformation",
        "amountper",
        "valueper",
        "totalfat",
        "transfat",
        "saturatedfat",
        "totalcarbohydrate",
        "dietaryfiber",
        "dietaryfibre",
        "totalsugar",
        "addedsugar",
    }
    slopes: list[float] = []
    ordered = sorted(usable, key=lambda word: word.center_x)
    for index, first in enumerate(ordered):
        first_text = re.sub(r"[^a-z]", "", first.text.casefold())
        if not first_text:
            continue
        for second in ordered[index + 1 :]:
            delta_x = second.center_x - first.center_x
            local_height = max(first.height, second.height)
            if delta_x > local_height * 12:
                break
            if delta_x < local_height * 0.5:
                continue
            second_text = re.sub(r"[^a-z]", "", second.text.casefold())
            if first_text + second_text not in phrase_aliases:
                continue
            slope = (second.center_y - first.center_y) / delta_x
            # Larger values are usually an accidental diagonal through adjacent
            # rows, not page skew. Local association handles mild curvature.
            if abs(slope) <= 0.12:
                slopes.append(slope)
    return median(slopes) if slopes else 0.0


def _numeric_cells(row: list[SpatialWord]) -> list[tuple[float, str]]:
    cells: list[tuple[float, str]] = []
    index = 0
    numeric_piece = re.compile(r"^[0-9Oo]+(?:[.,][0-9Oo]+)?$|^[.,]$")
    complete_cell = re.compile(
        r"^(?P<qualifier><)?\s*(?P<number>[0-9Oo]+(?:[.,][0-9Oo]+)?)"
        r"\s*(?P<unit>kcal|kj|mg|g|q)?\s*(?P<percent>%)?$",
        re.I,
    )
    while index < len(row):
        word = row[index]
        token = word.text.strip()
        complete = complete_cell.fullmatch(token)
        if complete and (
            complete.group("qualifier")
            or complete.group("unit")
            or complete.group("percent")
        ):
            raw = (
                ("<" if complete.group("qualifier") else "")
                + complete.group("number")
                + ("%" if complete.group("percent") else "")
            )
            cells.append((word.center_x, raw))
            index += 1
            continue
        token = token.strip("%")
        if not numeric_piece.match(token):
            index += 1
            continue
        pieces = [token]
        right = word.left + word.width
        centers = [word.center_x]
        next_index = index + 1
        while next_index < len(row):
            following = row[next_index]
            following_token = following.text.strip().strip("%")
            gap = following.left - right
            if not numeric_piece.match(following_token) or gap > max(word.height, following.height) * 0.8:
                break
            pieces.append(following_token)
            centers.append(following.center_x)
            right = following.left + following.width
            next_index += 1
        raw = "".join(pieces)
        if re.search(r"\d", raw):
            cells.append((sum(centers) / len(centers), raw))
        index = max(next_index, index + 1)
    return cells


def _numeric_cell_value(raw: str) -> tuple[float, bool, str | None, bool]:
    qualifier = "less_than" if raw.lstrip().startswith("<") else None
    is_percent = raw.rstrip().endswith("%")
    cleaned = raw.strip().lstrip("<").rstrip("%").strip()
    value, corrected = _number(cleaned)
    return value, corrected, qualifier, is_percent


def infer_per_100_column(words: Iterable[SpatialWord], basis: str) -> float | None:
    """Locate the primary per-100 value column from header or repeated alignment."""
    if basis not in {"per_100g", "per_100ml"}:
        return None
    usable = [word for word in words if word.text.strip()]
    if not usable:
        return None

    # A unit-bearing token is much safer than a bare 100, which may be a serving
    # size elsewhere on the package. Tesseract commonly reads the final g as q/9.
    header_pattern = OCR_100G_PATTERN if basis == "per_100g" else OCR_100ML_PATTERN
    explicit = [word for word in usable if header_pattern.fullmatch(word.text.strip())]
    if explicit:
        return max(explicit, key=lambda word: word.confidence).center_x

    rows = _group_spatial_rows(usable)
    for row in rows:
        row_text = " ".join(word.text for word in row)
        if re.search(r"\b(?:value\s+)?per\b", row_text, re.I) and header_pattern.search(row_text):
            hundred = next(
                (word for word in row if header_pattern.fullmatch(word.text.strip())),
                None,
            )
            if hundred is None:
                expected_unit = r"[gq9_]" if basis == "per_100g" else r"m[lIi1]"
                hundred = next(
                    (
                        word
                        for index, word in enumerate(row[:-1])
                        if re.fullmatch(r"[1I][0Oo][0Oo]", word.text.strip())
                        and re.fullmatch(expected_unit, row[index + 1].text.strip(), re.I)
                    ),
                    None,
                )
            if hundred:
                return hundred.center_x

    # Tesseract may place "Per" on a neighbouring header row while retaining
    # the adjacent 100 + ml tokens. Basis has already been established from the
    # full same-engine OCR contract, so this remains table-context constrained.
    if basis == "per_100ml":
        for row in rows:
            for index, token in enumerate(row[:-1]):
                if re.fullmatch(r"[1I][0Oo][0Oo]", token.text.strip()) and re.fullmatch(
                    r"m[lIi1]", row[index + 1].text.strip(), re.I
                ):
                    return (token.center_x + row[index + 1].center_x) / 2

    # Some photographed tables lose the words "Per" or merge the header into
    # a damaged line while retaining two well-aligned numeric columns. Limit a
    # geometry-only fallback to the detected nutrition-table band, then choose
    # the leftmost repeated non-percent column. This is intentionally not used
    # on arbitrary page text.
    header_indexes = [
        index
        for index, row in enumerate(rows)
        if re.search(
            r"nutrition|facts|information|%\s*rda|recommended\s+dietary|100\s*m[lIi1]",
            " ".join(word.text for word in row),
            re.I,
        )
    ]
    table_band_rows: list[list[SpatialWord]] = []
    if header_indexes:
        start = min(header_indexes)
        stop = len(rows)
        for index in range(start + 1, len(rows)):
            row_text = " ".join(word.text for word in rows[index])
            if re.search(r"approximate\s+values|recommended\s+dietary\s+allowance", row_text, re.I):
                stop = index
                break
        table_band_rows = rows[start:stop]

    # Header OCR may fail while nutrient columns remain strongly aligned. Build
    # numeric x clusters from reconstructed rows and prefer the densest leftmost
    # column to avoid a farther-right RDA/percentage column.
    label_right_edges: list[float] = []
    numeric_cells: list[tuple[float, str]] = []
    for row in rows:
        row_text = " ".join(word.text for word in row)
        if _field_for_row(row_text):
            nonnumeric = [word for word in row if not re.search(r"\d", word.text)]
            if nonnumeric:
                label_right_edges.append(max(word.left + word.width for word in nonnumeric))
            numeric_cells.extend(_numeric_cells(row))
    if not numeric_cells and table_band_rows:
        numeric_cells = [
            cell
            for row in table_band_rows
            for cell in _numeric_cells(row)
        ]
    if not numeric_cells:
        return None
    label_boundary = median(label_right_edges) if label_right_edges else 0
    candidates = [
        x for x, raw in numeric_cells
        if x > label_boundary
        and not raw.endswith("%")
        and not re.fullmatch(r"1[Oo0][Oo0]", raw)
    ]
    if not candidates and table_band_rows:
        candidates = [
            x
            for row in table_band_rows
            for x, raw in _numeric_cells(row)
            if not raw.endswith("%") and not re.fullmatch(r"(?:100|250|450)", raw)
        ]
    if not candidates:
        return None
    tolerance = max(25.0, median(word.height for word in usable) * 1.2)
    clusters: list[list[float]] = []
    for x in sorted(candidates):
        if clusters and abs(x - median(clusters[-1])) <= tolerance:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    viable = [cluster for cluster in clusters if len(cluster) >= 3]
    if not viable and table_band_rows:
        band_candidates = [
            x
            for row in table_band_rows
            for x, raw in _numeric_cells(row)
            if not raw.endswith("%") and not re.fullmatch(r"(?:100|250|450)", raw)
        ]
        clusters = []
        for x in sorted(band_candidates):
            if clusters and abs(x - median(clusters[-1])) <= tolerance:
                clusters[-1].append(x)
            else:
                clusters.append([x])
        viable = [cluster for cluster in clusters if len(cluster) >= 3]
    if not viable:
        return None
    # Prefer the first repeated column. Farther-right columns are normally
    # per-serving and RDA, and consistency matters more than row-local proximity.
    chosen = min(viable, key=median)
    return median(chosen)


def _row_unit(row_text: str, field_name: str) -> str | None:
    units = re.findall(r"(?<![a-z])(kcal|kj|mg|g)(?![a-z])", row_text, re.I)
    if field_name == "energy_100g":
        direct = next((unit.lower() for unit in units if unit.lower() in {"kcal", "kj"}), None)
        if direct:
            return direct
        if re.search(r"\bk[ec]a[il1]?\b", row_text, re.I):
            return "kcal"
        return None
    direct = next((unit.lower() for unit in units if unit.lower() in {"mg", "g"}), None)
    if direct:
        return direct
    if field_name == "cholesterol_100g" and re.search(r"\(\s*i?g\s*\)", row_text, re.I):
        return "mg"
    if re.search(r"\(\s*[q9]\s*[\)1|]", row_text, re.I):
        return "g"
    if re.search(r"\d(?:[.,]\d+)?\s*q\b", row_text, re.I):
        return "g"
    return None


def _expected_row_y(
    row: list[SpatialWord], x: float, fallback_slope: float
) -> float:
    """Predict a local row baseline without assuming one global planar table."""
    anchors = [word for word in row if not re.search(r"\d", word.text)] or row
    slopes: list[float] = []
    for index, first in enumerate(anchors):
        for second in anchors[index + 1 :]:
            delta_x = second.center_x - first.center_x
            if abs(delta_x) < max(first.height, second.height):
                continue
            slope = (second.center_y - first.center_y) / delta_x
            if abs(slope) <= 0.35:
                slopes.append(slope)
    local_slope = median(slopes) if slopes else fallback_slope
    intercept = median(word.center_y - local_slope * word.center_x for word in anchors)
    return intercept + local_slope * x


def _locally_associated_cells(
    row_index: int,
    label_rows: list[tuple[list[SpatialWord], str]],
    words: list[SpatialWord],
    per_100_x: float,
    column_tolerance: float,
    slope: float,
) -> tuple[list[tuple[float, str]], list[SpatialWord]]:
    """Assign detached value boxes to the nearest local nutrient baseline."""
    current_row = label_rows[row_index][0]
    direct = _numeric_cells(current_row)
    accepted = [
        cell
        for cell in direct
        if not cell[1].endswith("%")
        and not re.fullmatch(r"100", cell[1])
        and abs(cell[0] - per_100_x) <= column_tolerance
    ]
    row_ids = {id(word) for row, _ in label_rows for word in row}
    associated_words: list[SpatialWord] = []
    associated_cells: list[tuple[float, str]] = list(accepted)
    for word in words:
        if id(word) in row_ids:
            continue
        cells = _numeric_cells([word])
        if not cells:
            continue
        for x, raw in cells:
            if (
                raw.endswith("%")
                or re.fullmatch(r"100", raw)
                # A second fragment just outside the selection window makes
                # the primary cell unsafe, while the farther serving column
                # remains excluded.
                or abs(x - per_100_x) > column_tolerance * 1.5
            ):
                continue
            distance = abs(word.center_y - _expected_row_y(current_row, x, slope))
            local_height = median(item.height for item in current_row)
            tolerance = max(10.0, (local_height + word.height) * 0.65)
            if distance <= tolerance:
                associated_cells.append((x, raw))
                associated_words.append(word)
    return associated_cells, associated_words


def parse_spatial_nutrition(
    words: Iterable[SpatialWord], basis: str
) -> tuple[dict[str, ParsedNutrient], list[str]]:
    """Associate label rows with one detected per-100 primary numeric column."""
    rows = _group_spatial_rows(words)
    word_list = [word for row in rows for word in row]
    per_100_x = infer_per_100_column(word_list, basis)
    if basis not in {"per_100g", "per_100ml"} or per_100_x is None:
        basis_name = "per-100-g" if basis == "per_100g" else "per-100-ml"
        return {}, [f"Could not identify the spatial {basis_name} table column."] if words else []

    nutrients: dict[str, ParsedNutrient] = {}
    warnings: list[str] = []
    word_heights = [word.height for word in word_list if word.height > 0]
    column_tolerance = max(35.0, median(word_heights) * 1.5) if word_heights else 35.0
    table_context = any(
        re.search(r"nutrition|facts|information|%\s*rda", word.text, re.I)
        for word in word_list
    )
    label_rows: list[tuple[list[SpatialWord], str]] = []
    for row in rows:
        row_text = " ".join(word.text for word in row)
        field_name = _field_for_row(row_text)
        if field_name is None and table_context and re.search(r"\bkcal\b", row_text, re.I):
            field_name = "energy_100g"
        if field_name:
            label_rows.append((row, field_name))
    slope = _estimate_table_row_slope(word_list)
    for row_index, (row, field_name) in enumerate(label_rows):
        row_text = " ".join(word.text for word in row)
        candidates, associated_words = _locally_associated_cells(
            row_index,
            label_rows,
            word_list,
            per_100_x,
            column_tolerance,
            slope,
        )
        if not candidates:
            continue
        if len(candidates) > 1:
            warnings.append(
                f"Ambiguous primary nutrition cell for {field_name}; value omitted."
            )
            continue
        unit_text = " ".join([row_text, *(word.text for word in associated_words)])
        unit = _row_unit(unit_text, field_name)
        if not unit:
            continue
        x, raw = min(candidates, key=lambda item: abs(item[0] - per_100_x))
        numeric_text = raw.strip().lstrip("<").rstrip("%").strip()
        if re.fullmatch(r"0[1-9][0-9]*", numeric_text):
            warnings.append(
                f"Omitted {field_name}: a leading-zero OCR value had no reliable decimal separator."
            )
            continue
        try:
            source_value, corrected, qualifier, _ = _numeric_cell_value(raw)
        except ValueError:
            continue
        value = source_value
        normalized_unit = unit
        if unit == "mg":
            value = source_value / 1000
            normalized_unit = "g"
        elif unit == "kcal":
            value = source_value * 4.184
            normalized_unit = "kJ"
        elif unit == "kj":
            normalized_unit = "kJ"
        nutrients[field_name] = ParsedNutrient(
            value=round(value, 6),
            unit=normalized_unit,
            source_value=source_value,
            source_unit=unit,
            basis=basis,
            qualifier=qualifier,
        )
        if corrected:
            warnings.append(f"Corrected OCR punctuation or letter O for {field_name}.")
        if qualifier:
            warnings.append(f"The value for {field_name} is an upper-bound estimate.")
    return nutrients, warnings


def _fragmented_spatial_fields(words: Iterable[SpatialWord], basis: str) -> set[str]:
    """Flag primary-column digit fragments that are unsafe to parse as values."""
    word_list = list(words)
    per_100_x = infer_per_100_column(word_list, basis)
    if per_100_x is None:
        return set()
    fragmented: set[str] = set()
    for row in _group_spatial_rows(word_list):
        row_text = " ".join(word.text for word in row)
        field_name = _field_for_row(row_text)
        if not field_name:
            continue
        for word in row:
            token = word.text.strip().strip("%")
            if abs(word.center_x - per_100_x) > max(45, word.height * 1.5):
                continue
            digit_count = sum(character.isdigit() for character in token)
            consensus_cell = word.confidence >= 100
            malformed = (
                not consensus_cell
                and digit_count
                and not re.fullmatch(
                    r"<?\s*[0-9Oo]+(?:[.,][0-9Oo]+)?\s*(?:kcal|kj|mg|g|q)?",
                    token,
                    re.I,
                )
            )
            implausibly_narrow = (
                not consensus_cell
                and digit_count >= 2
                and word.width / digit_count < word.height * 0.35
            )
            if malformed or implausibly_narrow:
                fragmented.add(field_name)
                break
    return fragmented


def _apply_plausibility(result: NutritionParseResult) -> None:
    invalid: dict[str, str] = {}
    gram_limits = {
        "fat_100g": 100,
        "saturated_fat_100g": 100,
        "trans_fat_100g": 100,
        "carbohydrates_100g": 100,
        "sugars_100g": 100,
        "added_sugars_100g": 100,
        "fiber_100g": 100,
        "proteins_100g": 100,
        "salt_100g": 100,
        "sodium_100g": 10,
        "calcium_100g": 10,
    }
    for field_name, maximum in gram_limits.items():
        nutrient = result.nutrients.get(field_name)
        if nutrient and not 0 <= nutrient.value <= maximum:
            invalid[field_name] = f"outside the plausible 0-{maximum} g per 100 g range"
    energy = result.nutrients.get("energy_100g")
    if energy and not 0 <= energy.value <= 5000:
        invalid["energy_100g"] = "outside the plausible energy range"

    relations = (
        ("saturated_fat_100g", "fat_100g", "saturated fat exceeds total fat"),
        ("trans_fat_100g", "fat_100g", "trans fat exceeds total fat"),
        ("sugars_100g", "carbohydrates_100g", "total sugar exceeds carbohydrate"),
        ("added_sugars_100g", "sugars_100g", "added sugar exceeds total sugar"),
    )
    for child, parent, reason in relations:
        if child in result.nutrients and parent in result.nutrients:
            if result.nutrients[child].value > result.nutrients[parent].value + 1e-6:
                invalid[child] = reason
    for field_name, reason in invalid.items():
        result.nutrients.pop(field_name, None)
        result.warnings.append(f"Rejected {field_name}: {reason}.")


def _reconstructed_nutrition_rows(text: str) -> list[tuple[str, str]]:
    """Join short split OCR detections only after a nutrient label is identified."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    reconstructed: list[tuple[str, str]] = []
    for index, line in enumerate(lines):
        field_name = _field_for_row(line)
        if not field_name:
            continue
        parts = [line]
        for following in lines[index + 1 : index + 6]:
            if _field_for_row(following):
                break
            if re.search(
                r"\b(?:ingredients?|recommended|allowance|net\s+weight|"
                r"production|imported|distributed)\b",
                following,
                re.I,
            ):
                break
            parts.append(following)
            if re.search(r"(?:kcal|kj|mg|g|q)\b", following, re.I):
                break
        reconstructed.append((field_name, " ".join(parts)))
    return reconstructed


def parse_nutrition_text(
    text: str,
    spatial_words: Iterable[SpatialWord] = (),
    basis_override: str | None = None,
) -> NutritionParseResult:
    normalized = text.replace("—", "-").replace("\u00a0", " ")
    basis = basis_override or _detect_basis(normalized)
    result = NutritionParseResult(basis=basis)
    if basis == "unknown":
        result.warnings.append("Could not determine whether values are per 100 g or per serving.")
    elif basis != "per_100g":
        result.warnings.append(f"Detected {basis.replace('_', ' ')} values; the current model requires per 100 g values.")

    spatial_word_list = list(spatial_words)
    strict_spatial_table = basis == "per_100ml" and bool(spatial_word_list)
    if not strict_spatial_table:
        for line in (item.strip() for item in normalized.splitlines() if item.strip()):
            for field_name, segment in _segments(line):
                nutrient, warnings = _parse_segment(field_name, segment, basis)
                if nutrient is not None and field_name not in result.nutrients:
                    result.nutrients[field_name] = nutrient
                    result.warnings.extend(warnings)

    if basis != "unknown" and not strict_spatial_table:
        for field_name, reconstructed in _reconstructed_nutrition_rows(normalized):
            if field_name in result.nutrients:
                continue
            nutrient, warnings = _parse_segment(field_name, reconstructed, basis)
            if nutrient is not None:
                result.nutrients[field_name] = nutrient
                result.warnings.extend(warnings)

    spatial_nutrients, spatial_warnings = parse_spatial_nutrition(spatial_word_list, basis)
    if spatial_nutrients:
        result.nutrients.update(spatial_nutrients)
        result.warnings.extend(spatial_warnings)
    for field_name in _fragmented_spatial_fields(spatial_word_list, basis):
        if field_name in result.nutrients:
            result.nutrients.pop(field_name)
            result.warnings.append(
                f"Omitted {field_name}: the primary OCR cell contained unresolved digit fragments."
            )

    if "salt_100g" in result.nutrients and "sodium_100g" in result.nutrients:
        salt = result.nutrients["salt_100g"].value
        sodium = result.nutrients["sodium_100g"].value
        if sodium > salt:
            result.warnings.append("Extracted sodium exceeds salt; verify OCR values and units.")
    _apply_plausibility(result)
    result.warnings = list(dict.fromkeys(result.warnings))
    return result


# Compatibility helper for earlier imports. New code uses NutritionParseResult.
def parse_nutrition_values(text: str) -> dict[str, float]:
    return parse_nutrition_text(text).normalized_model_values
