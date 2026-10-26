"""Minimal dependency-free XLSX row reader for deterministic pipeline ingestion."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath
from typing import Any

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CELL_REF = re.compile(r"([A-Z]+)(\d+)")
MAX_ZIP_ENTRIES = 512
MAX_EXPANDED_BYTES = 100 * 1024 * 1024
MAX_EXPANSION_RATIO = 100
MAX_SHARED_STRINGS = 100_000
MAX_ROWS = 1_000_000
MAX_COLUMNS = 16_384


def _validate_archive(archive: zipfile.ZipFile) -> None:
    infos = archive.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise ValueError("XLSX contains too many ZIP entries")
    expanded = sum(info.file_size for info in infos)
    compressed = max(sum(info.compress_size for info in infos), 1)
    if expanded > MAX_EXPANDED_BYTES or expanded > compressed * MAX_EXPANSION_RATIO:
        raise ValueError("XLSX exceeds expansion budget")


def column_index(reference: str) -> int:
    match = CELL_REF.fullmatch(reference)
    if not match:
        raise ValueError(f"invalid XLSX cell reference: {reference}")
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values = ["".join(text.text or "" for text in item.iter(f"{{{MAIN}}}t")) for item in root]
    if len(values) > MAX_SHARED_STRINGS:
        raise ValueError("XLSX contains too many shared strings")
    return values


def _sheet_path(archive: zipfile.ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationship_id = None
    for sheet in workbook.iter(f"{{{MAIN}}}sheet"):
        if sheet.attrib.get("name") == sheet_name:
            relationship_id = sheet.attrib.get(f"{{{REL}}}id")
            break
    if relationship_id is None:
        raise KeyError(f"XLSX sheet not found: {sheet_name}")
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for relationship in relationships.iter(f"{{{PACKAGE_REL}}}Relationship"):
        if relationship.attrib.get("Id") == relationship_id:
            target = relationship.attrib["Target"]
            return str(PurePosixPath("xl") / target).replace("xl/xl/", "xl/")
    raise KeyError(f"XLSX relationship not found: {relationship_id}")


def iter_xlsx_rows(path: Path, sheet_name: str) -> Iterable[tuple[int, list[Any]]]:
    with zipfile.ZipFile(path) as archive:
        _validate_archive(archive)
        shared = _shared_strings(archive)
        sheet_path = _sheet_path(archive, sheet_name)
        with archive.open(sheet_path) as source:
            parsed_rows = 0
            for _event, row in ET.iterparse(source, events=("end",)):
                if row.tag != f"{{{MAIN}}}row":
                    continue
                parsed_rows += 1
                if parsed_rows > MAX_ROWS:
                    raise ValueError("XLSX row count limit exceeded")
                row_number = int(row.attrib.get("r", "0"))
                if row_number > MAX_ROWS:
                    raise ValueError("XLSX row limit exceeded")
                cells: dict[int, Any] = {}
                for cell in row.findall(f"{{{MAIN}}}c"):
                    reference = cell.attrib.get("r", "")
                    index = column_index(reference)
                    if index >= MAX_COLUMNS:
                        raise ValueError("XLSX column limit exceeded")
                    cell_type = cell.attrib.get("t")
                    value_element = cell.find(f"{{{MAIN}}}v")
                    inline = cell.find(f"{{{MAIN}}}is")
                    raw = value_element.text if value_element is not None else None
                    if cell_type == "s" and raw is not None:
                        value: Any = shared[int(raw)]
                    elif cell_type == "inlineStr" and inline is not None:
                        value = "".join(text.text or "" for text in inline.iter(f"{{{MAIN}}}t"))
                    elif cell_type == "b" and raw is not None:
                        value = raw == "1"
                    elif raw is None:
                        value = None
                    else:
                        try:
                            number = float(raw)
                            value = int(number) if number.is_integer() else number
                        except ValueError:
                            value = raw
                    cells[index] = value
                if cells:
                    width = max(cells) + 1
                    yield row_number, [cells.get(index) for index in range(width)]
                row.clear()
