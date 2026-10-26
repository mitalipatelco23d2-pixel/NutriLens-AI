"""R1-aware source resolution and licence/status enforcement for R2."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from scripts.data_engineering.io_utils import sha256_file
from scripts.data_engineering.schemas import Lineage


@dataclass(frozen=True)
class SourceInfo:
    dataset_id: str
    path: Path
    checksum: str
    version: str
    source_url: str
    license_status: str

    def lineage(self, source_record_id: str) -> Lineage:
        return Lineage(
            source_dataset=self.dataset_id,
            source_record_id=source_record_id,
            source_version=self.version,
            source_url=self.source_url,
            input_checksum=self.checksum,
            processing_timestamp=datetime.now(UTC),
            license_status=self.license_status,
        )


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def load_sources(repo_root: Path) -> dict[str, SourceInfo]:
    catalogue = {
        row["Dataset ID"]: row
        for row in _rows(repo_root / "documentation/datasets/dataset-catalogue.csv")
    }
    licences = {
        row["Dataset ID"]: row
        for row in _rows(repo_root / "documentation/datasets/license-register.csv")
    }
    manifest = _rows(repo_root / "data/manifests/downloaded-artifacts.csv")
    sources: dict[str, SourceInfo] = {}
    for row in manifest:
        dataset_id = row["Dataset ID"]
        catalogue_row = catalogue[dataset_id]
        if catalogue_row["Acquisition status"] != "DOWNLOADED":
            raise RuntimeError(f"{dataset_id}: R2 refuses a source that is not DOWNLOADED")
        path = (repo_root / row["Local path"]).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        checksum = sha256_file(path)
        if checksum != row["SHA-256"]:
            raise RuntimeError(f"{dataset_id}: R1 checksum mismatch")
        sources[dataset_id] = SourceInfo(
            dataset_id=dataset_id,
            path=path,
            checksum=checksum,
            version=row["Version"],
            source_url=row["Source URL"],
            license_status=licences[dataset_id]["Review status"],
        )
    return sources


def require_source(sources: dict[str, SourceInfo], dataset_id: str) -> SourceInfo:
    try:
        return sources[dataset_id]
    except KeyError as exc:
        raise RuntimeError(
            f"{dataset_id} is unavailable or access-gated; R2 will not fabricate or bypass it"
        ) from exc
