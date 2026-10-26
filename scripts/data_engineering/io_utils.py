"""Atomic I/O, checksums, source guards, and transformation manifests."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from pydantic import BaseModel

CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def atomic_text_writer(path: Path) -> Iterator[TextIO]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="") as target:
            yield target
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def json_ready(record: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(record, BaseModel):
        return record.model_dump(mode="json")
    return dict(record)


def write_jsonl(path: Path, records: Iterable[BaseModel | Mapping[str, Any]]) -> int:
    count = 0
    with atomic_text_writer(path) as target:
        for record in records:
            target.write(json.dumps(json_ready(record), ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    with atomic_text_writer(path) as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
            count += 1
    return count


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{line_number}: JSONL record is not an object")
                yield value


def snapshot_checksums(paths: Iterable[Path]) -> dict[str, str]:
    return {path.as_posix(): sha256_file(path) for path in sorted(paths)}


def verify_unchanged(before: Mapping[str, str]) -> None:
    changed = [path for path, checksum in before.items() if sha256_file(Path(path)) != checksum]
    if changed:
        raise RuntimeError(f"immutable source changed during processing: {changed}")


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    with atomic_text_writer(path) as target:
        json.dump(payload, target, ensure_ascii=False, indent=2, sort_keys=True)
        target.write("\n")


def output_metadata(path: Path, record_count: int, *, role: str) -> dict[str, Any]:
    return {
        "path": path.as_posix(),
        "role": role,
        "record_count": record_count,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
