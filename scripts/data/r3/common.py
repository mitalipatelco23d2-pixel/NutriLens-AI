"""Shared safe download, hashing, manifest, and extraction primitives for R3 data."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import socket
import tarfile
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, TextIO

import requests
from huggingface_hub import snapshot_download
from urllib3.util import connection as urllib3_connection

REPO_ROOT = Path(__file__).resolve().parents[3]
USER_AGENT = "NutriLensX-R3/1.0 (college-research; local-dataset-acquisition)"
CHUNK_BYTES = 4 * 1024 * 1024


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def relative_to_repo(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def safe_child(root: Path, relative: str | Path) -> Path:
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise ValueError(f"path escapes target root: {relative}")
    return candidate


@contextmanager
def atomic_text(path: Path, *, newline: str | None = None) -> Iterator[TextIO]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.part")
    try:
        with temporary.open("w", encoding="utf-8", newline=newline) as target:
            yield target
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, payload: Mapping[str, Any] | Sequence[Any]) -> None:
    with atomic_text(path) as target:
        json.dump(payload, target, ensure_ascii=False, indent=2, sort_keys=True)
        target.write("\n")


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    with atomic_text(path) as target:
        for row in rows:
            target.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open(encoding="utf-8") as source:
        for line in source:
            if line.strip():
                yield json.loads(line)


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    with atomic_text(path, newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def download_file(
    url: str,
    destination: Path,
    *,
    expected_size: int | None = None,
    max_bytes: int,
    timeout_seconds: float = 60,
) -> str:
    """Resume into a .part file and never overwrite a completed destination."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    if max_bytes < 1 or (expected_size is not None and expected_size > max_bytes):
        raise ValueError("download byte limit must cover the expected size")
    if destination.is_file():
        if destination.stat().st_size > max_bytes:
            raise RuntimeError(f"existing file exceeds {max_bytes} byte limit: {destination}")
        if expected_size is not None and destination.stat().st_size != expected_size:
            raise RuntimeError(f"existing file has unexpected size: {destination}")
        return "EXISTS"

    partial = destination.with_suffix(destination.suffix + ".part")
    existing = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if existing:
        headers["Range"] = f"bytes={existing}-"
    with requests.get(url, headers=headers, stream=True, timeout=timeout_seconds) as response:
        if existing and response.status_code == 200:
            existing = 0
            mode = "wb"
        elif response.status_code in {200, 206}:
            mode = "ab" if existing else "wb"
        else:
            response.raise_for_status()
            raise RuntimeError(f"unexpected HTTP status {response.status_code} for {url}")
        declared = response.headers.get("Content-Length")
        if declared is not None and existing + int(declared) > max_bytes:
            raise RuntimeError(f"download exceeds {max_bytes} byte limit")
        total = existing
        with partial.open(mode) as target:
            for chunk in response.iter_content(CHUNK_BYTES):
                if chunk:
                    total += len(chunk)
                    if total > max_bytes:
                        raise RuntimeError(f"download exceeds {max_bytes} byte limit")
                    target.write(chunk)
    if expected_size is not None and partial.stat().st_size != expected_size:
        raise RuntimeError(
            f"download size mismatch for {destination}: {partial.stat().st_size} != {expected_size}"
        )
    partial.replace(destination)
    return "DOWNLOADED"


def download_file_parallel_ranges(
    url: str,
    destination: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    workers: int = 32,
    range_bytes: int = 16 * 1024 * 1024,
    timeout_seconds: float = 120,
    max_attempts: int = 10,
    force_ipv4: bool = False,
) -> str:
    """Download an exact-size file through validated, resumable HTTP byte ranges."""

    if workers < 1 or range_bytes < 1 or expected_size < 1:
        raise ValueError("workers, range_bytes, and expected_size must be positive")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if force_ipv4:
        urllib3_connection.allowed_gai_family = lambda: socket.AF_INET
    if destination.is_file():
        if destination.stat().st_size != expected_size:
            raise RuntimeError(f"existing file has unexpected size: {destination}")
        if sha256_file(destination) != expected_sha256:
            raise RuntimeError(f"existing file has unexpected digest: {destination}")
        return "EXISTS"

    ranges_root = destination.with_name(f".{destination.name}.ranges")
    ranges_root.mkdir(parents=True, exist_ok=True)
    ranges = [
        (start, min(start + range_bytes, expected_size) - 1)
        for start in range(0, expected_size, range_bytes)
    ]

    def download_range(start: int, end: int) -> Path:
        expected_range_size = end - start + 1
        range_path = ranges_root / f"{start:012d}-{end:012d}.part"
        existing = range_path.stat().st_size if range_path.exists() else 0
        if existing > expected_range_size:
            raise RuntimeError(f"oversized range file: {range_path}")
        if existing == expected_range_size:
            return range_path

        for attempt in range(1, max_attempts + 1):
            request_start = start + existing
            headers = {
                "Range": f"bytes={request_start}-{end}",
                "User-Agent": USER_AGENT,
            }
            try:
                with requests.get(
                    url,
                    headers=headers,
                    stream=True,
                    timeout=(30, timeout_seconds),
                ) as response:
                    if response.status_code != 206:
                        raise RuntimeError(
                            f"server did not honor range {request_start}-{end}: "
                            f"HTTP {response.status_code}"
                        )
                    expected_content_range = f"bytes {request_start}-{end}/{expected_size}"
                    if response.headers.get("Content-Range") != expected_content_range:
                        raise RuntimeError(
                            "unexpected Content-Range "
                            f"{response.headers.get('Content-Range')!r}; "
                            f"expected {expected_content_range!r}"
                        )
                    with range_path.open("ab") as target:
                        for chunk in response.iter_content(CHUNK_BYTES):
                            if chunk:
                                target.write(chunk)
                existing = range_path.stat().st_size
                if existing == expected_range_size:
                    return range_path
                if existing > expected_range_size:
                    raise RuntimeError(f"range response exceeded requested bytes: {range_path}")
            except (OSError, requests.RequestException, RuntimeError):
                existing = range_path.stat().st_size if range_path.exists() else 0
                if attempt == max_attempts:
                    raise
                time.sleep(min(2 ** (attempt - 1), 8))
        raise AssertionError("unreachable range retry state")

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_range, start, end): (start, end) for start, end in ranges}
        for future in as_completed(futures):
            future.result()
            completed += 1
            if completed == 1 or completed % 25 == 0 or completed == len(ranges):
                print(f"Downloaded {completed}/{len(ranges)} validated ranges", flush=True)

    merged = destination.with_name(f".{destination.name}.merge.part")
    with merged.open("wb") as target:
        for start, end in ranges:
            range_path = ranges_root / f"{start:012d}-{end:012d}.part"
            if range_path.stat().st_size != end - start + 1:
                raise RuntimeError(f"range size changed before merge: {range_path}")
            with range_path.open("rb") as source:
                while chunk := source.read(CHUNK_BYTES):
                    target.write(chunk)
    if merged.stat().st_size != expected_size:
        raise RuntimeError(
            f"merged download size mismatch: {merged.stat().st_size} != {expected_size}"
        )
    if sha256_file(merged) != expected_sha256:
        merged.unlink(missing_ok=True)
        raise RuntimeError("merged download failed trusted SHA-256 verification")
    merged.replace(destination)

    for start, end in ranges:
        (ranges_root / f"{start:012d}-{end:012d}.part").unlink(missing_ok=True)
    ranges_root.rmdir()
    destination.with_suffix(destination.suffix + ".part").unlink(missing_ok=True)
    return "DOWNLOADED"


def download_huggingface_snapshot(
    *,
    repo_id: str,
    revision: str,
    destination: Path,
    allow_patterns: Sequence[str],
) -> Path:
    """Download an immutable official dataset revision into a controlled directory."""

    marker = destination / ".nutrilens-source.json"
    if marker.exists():
        existing = json.loads(marker.read_text(encoding="utf-8"))
        if existing.get("repo_id") != repo_id or existing.get("revision") != revision:
            raise RuntimeError(f"refusing to mix dataset revisions in {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    result = snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        revision=revision,
        local_dir=destination,
        allow_patterns=list(allow_patterns),
    )
    if not marker.exists():
        write_json(
            marker,
            {
                "acquired_at": utc_now(),
                "repo_id": repo_id,
                "revision": revision,
                "resolved_path": str(Path(result).resolve()),
            },
        )
    return Path(result)


def artifact_rows(root: Path, *, exclude_parts: set[str] | None = None) -> list[dict[str, Any]]:
    excluded = exclude_parts or {".cache", ".nutrilens-source.json", "images"}
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in excluded for part in path.relative_to(root).parts):
            continue
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return rows


def tree_digest(rows: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda item: str(item["path"])):
        digest.update(f"{row['sha256']}  {row['path']}\n".encode())
    return digest.hexdigest()


def safe_extract_tar(
    archive: Path,
    destination: Path,
    *,
    max_members: int = 100_000,
    max_expanded_bytes: int = 20 * 1024 * 1024 * 1024,
    max_expansion_ratio: int = 200,
) -> None:
    """Extract only regular directories/files that stay below destination."""

    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, "r:*") as source:
        members: list[tarfile.TarInfo] = []
        expanded_bytes = 0
        for member in source:
            members.append(member)
            if len(members) > max_members:
                raise RuntimeError("archive contains too many members")
            expanded_bytes += max(member.size, 0)
            if expanded_bytes > max_expanded_bytes:
                raise RuntimeError("archive exceeds expanded byte budget")
            target = (root / member.name).resolve()
            if root != target and root not in target.parents:
                raise RuntimeError(f"unsafe archive member: {member.name}")
            if member.issym() or member.islnk() or member.isdev():
                raise RuntimeError(f"unsupported archive member: {member.name}")
        compressed_bytes = max(archive.stat().st_size, 1)
        if expanded_bytes > compressed_bytes * max_expansion_ratio:
            raise RuntimeError("archive exceeds expansion ratio budget")
        source.extractall(root, members=members, filter="data")


def copy_stream(source: BinaryIO, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    with temporary.open("wb") as target:
        while chunk := source.read(CHUNK_BYTES):
            target.write(chunk)
    temporary.replace(destination)
