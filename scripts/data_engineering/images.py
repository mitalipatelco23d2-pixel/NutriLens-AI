"""Dependency-free image integrity, format, dimension, and duplicate validation."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImageInspection:
    path: Path
    valid: bool
    format: str | None
    width: int | None
    height: int | None
    checksum: str | None
    failure_reason: str | None


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    offset = 2
    while offset + 9 < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(data):
            break
        length = int.from_bytes(data[offset : offset + 2], "big")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if offset + 7 > len(data):
                break
            height = int.from_bytes(data[offset + 3 : offset + 5], "big")
            width = int.from_bytes(data[offset + 5 : offset + 7], "big")
            return width, height
        if length < 2:
            break
        offset += length
    raise ValueError("JPEG dimensions not found")


def image_metadata(data: bytes) -> tuple[str, int, int]:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "PNG", width, height
    if data[:3] == b"GIF" and len(data) >= 10:
        width, height = struct.unpack("<HH", data[6:10])
        return "GIF", width, height
    if data.startswith(b"\xff\xd8"):
        width, height = _jpeg_dimensions(data)
        return "JPEG", width, height
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and len(data) >= 30:
        if data[12:16] == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return "WEBP", width, height
        raise ValueError("unsupported WEBP subtype for dimension extraction")
    raise ValueError("unsupported or corrupt image format")


def inspect_image(path: Path) -> ImageInspection:
    if not path.is_file():
        return ImageInspection(path, False, None, None, None, None, "MISSING_FILE")
    data = path.read_bytes()
    if not data:
        return ImageInspection(path, False, None, None, None, None, "ZERO_BYTE_FILE")
    checksum = hashlib.sha256(data).hexdigest()
    try:
        image_format, width, height = image_metadata(data)
    except ValueError as exc:
        return ImageInspection(path, False, None, None, None, checksum, str(exc))
    if width <= 0 or height <= 0:
        return ImageInspection(
            path, False, image_format, width, height, checksum, "INVALID_DIMENSIONS"
        )
    return ImageInspection(path, True, image_format, width, height, checksum, None)


def duplicate_checksums(inspections: list[ImageInspection]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for inspection in inspections:
        if inspection.checksum:
            groups.setdefault(inspection.checksum, []).append(inspection.path)
    return {checksum: paths for checksum, paths in groups.items() if len(paths) > 1}
