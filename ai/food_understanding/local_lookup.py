"""Offline-only product lookup adapter."""

from __future__ import annotations

from typing import Any


class LocalProductLookup:
    def __init__(self, records: dict[str, dict[str, Any]] | None = None) -> None:
        self._records = records or {}

    def find(self, barcode: str) -> tuple[str, dict[str, Any] | None]:
        record = self._records.get(barcode)
        return ("FOUND", record) if record is not None else ("NOT_FOUND", None)
