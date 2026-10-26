"""Thread-safe ephemeral structured scan store; image bytes are never retained."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from threading import RLock
from time import monotonic
from typing import Any

from ai.food_understanding.schemas import CorrectionRequest, R3ScanResult, StoredCorrection


class ScanNotFoundError(KeyError):
    pass


class EphemeralScanStore:
    def __init__(
        self,
        *,
        max_records: int = 250,
        ttl_seconds: float = 3600,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if max_records < 1 or ttl_seconds <= 0:
            raise ValueError("Ephemeral scan limits must be positive.")
        self._records: OrderedDict[str, tuple[R3ScanResult, str | None, float]] = OrderedDict()
        self._max_records = max_records
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = RLock()

    def _purge(self) -> None:
        cutoff = self._clock() - self._ttl_seconds
        expired = [key for key, (_, _, saved_at) in self._records.items() if saved_at <= cutoff]
        for key in expired:
            self._records.pop(key, None)

    def save(self, result: R3ScanResult, *, owner_id: str | None = None) -> R3ScanResult:
        with self._lock:
            self._purge()
            self._records.pop(result.scan_id, None)
            self._records[result.scan_id] = (result.model_copy(deep=True), owner_id, self._clock())
            while len(self._records) > self._max_records:
                self._records.popitem(last=False)
            return result.model_copy(deep=True)

    def get(self, scan_id: str) -> R3ScanResult:
        with self._lock:
            self._purge()
            stored = self._records.get(scan_id)
            record = stored[0] if stored else None
            if record is None:
                raise ScanNotFoundError(scan_id)
            return record.model_copy(deep=True)

    def list(
        self, scan_ids: set[str] | None = None, *, owner_id: str | None = None
    ) -> list[R3ScanResult]:
        with self._lock:
            self._purge()
            records = (
                (
                    entry[0]
                    for entry in self._records.values()
                    if owner_id is None or entry[1] == owner_id
                )
                if scan_ids is None
                else (
                    entry[0]
                    for scan_id, entry in self._records.items()
                    if scan_id in scan_ids and (owner_id is None or entry[1] == owner_id)
                )
            )
            return [
                record.model_copy(deep=True)
                for record in sorted(records, key=lambda item: item.created_at, reverse=True)
            ]

    def correct(self, scan_id: str, request: CorrectionRequest) -> R3ScanResult:
        with self._lock:
            self._purge()
            stored = self._records.get(scan_id)
            if stored is None:
                raise ScanNotFoundError(scan_id)
            record, owner_id, _ = stored
            updated = record.model_copy(deep=True)
            for correction in request.corrections:
                original, confidence = _prediction(updated, correction.field)
                updated.corrections.append(
                    StoredCorrection(
                        field=correction.field,
                        corrected_value=deepcopy(correction.corrected_value),
                        original_prediction=deepcopy(original),
                        confidence_before=confidence,
                        corrected_at=datetime.now(UTC),
                    )
                )
            self._records[scan_id] = (updated, owner_id, self._clock())
            self._records.move_to_end(scan_id)
            return updated.model_copy(deep=True)

    def delete(self, scan_id: str) -> bool:
        with self._lock:
            self._purge()
            return self._records.pop(scan_id, None) is not None

    def owner_of(self, scan_id: str) -> str | None:
        with self._lock:
            self._purge()
            stored = self._records.get(scan_id)
            if stored is None:
                raise ScanNotFoundError(scan_id)
            return stored[1]


def _prediction(result: R3ScanResult, field: str) -> tuple[Any, float | None]:
    if field == "product_name":
        product = result.product_name_candidates[0] if result.product_name_candidates else None
        return (product.value, product.confidence) if product else (None, None)
    if field == "brand":
        brand = result.brand_candidates[0] if result.brand_candidates else None
        return (brand.value, brand.confidence) if brand else (None, None)
    if field == "barcode":
        barcode = result.barcode_results[0] if result.barcode_results else None
        return (barcode.value, barcode.confidence) if barcode else (None, None)
    if field == "nutrition_text":
        return result.nutrition.raw_table_text, result.nutrition.confidence
    if field == "ingredient_text":
        return result.ingredients.raw_text, result.ingredients.confidence
    if field == "food_category":
        category = result.category_candidates[0] if result.category_candidates else None
        return (category.value, category.confidence) if category else (None, None)
    if field == "meal_item":
        return [item.model_dump(mode="json") for item in result.meal_items], None
    if field == "serving_amount":
        return [item.model_dump(mode="json") for item in result.portion_estimates], None
    if field == "detected_region":
        return [item.model_dump(mode="json") for item in result.regions], None
    return None, None
