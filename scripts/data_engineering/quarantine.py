"""Non-destructive invalid-record quarantine."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.data_engineering.io_utils import write_jsonl
from scripts.data_engineering.schemas import QuarantineRecord


class Quarantine:
    def __init__(self, dataset_id: str) -> None:
        self.dataset_id = dataset_id
        self.records: list[QuarantineRecord] = []

    def add(
        self,
        *,
        source_record_id: str | None,
        stage: str,
        rule: str,
        reason: str,
        snapshot: dict[str, Any],
    ) -> None:
        self.records.append(
            QuarantineRecord(
                dataset_id=self.dataset_id,
                source_record_id=source_record_id,
                processing_stage=stage,
                validation_rule=rule,
                failure_reason=reason,
                source_snapshot=snapshot,
                quarantined_at=datetime.now(UTC),
            )
        )

    def write(self, path: Path) -> int:
        return write_jsonl(path, self.records)
