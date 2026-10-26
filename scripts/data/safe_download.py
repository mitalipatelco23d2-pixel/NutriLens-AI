"""Small dependency-free downloader with path, size, resume, and checksum safeguards."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import IO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

CHUNK_SIZE = 1024 * 1024
USER_AGENT = "NutriLens-X-R1/1.0 (+academic local dataset acquisition)"


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    size_bytes: int
    sha256: str
    reused_existing: bool


class DownloadError(RuntimeError):
    """Raised when a safe acquisition cannot be completed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def has_magic(path: Path, expected: bytes) -> bool:
    with path.open("rb") as source:
        return source.read(len(expected)) == expected


def resolve_destination(repo_root: Path, relative_path: str) -> Path:
    root = repo_root.resolve()
    destination = (root / relative_path).resolve()
    if destination == root or root not in destination.parents:
        raise ValueError(f"Destination escapes repository: {relative_path}")
    return destination


def _copy_response(response: IO[bytes], target: IO[bytes], max_bytes: int, initial: int) -> int:
    total = initial
    while chunk := response.read(CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            raise DownloadError(f"Download exceeded configured {max_bytes:,}-byte safety limit")
        target.write(chunk)
    return total


def download(
    url: str,
    destination: Path,
    *,
    max_bytes: int,
    timeout_seconds: int = 60,
    force: bool = False,
    expected_magic: bytes | None = None,
    expected_sha256: str,
) -> DownloadResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Only absolute HTTP(S) source URLs are allowed")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if len(expected_sha256) != 64:
        raise ValueError("A trusted SHA-256 digest is required")

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not force:
        if expected_magic and not has_magic(destination, expected_magic):
            raise DownloadError(f"Existing file has an unexpected signature: {destination}")
        actual_digest = sha256_file(destination)
        if actual_digest != expected_sha256:
            raise DownloadError(f"Existing file has an unexpected digest: {destination}")
        return DownloadResult(
            path=destination,
            size_bytes=destination.stat().st_size,
            sha256=actual_digest,
            reused_existing=True,
        )

    partial = destination.with_name(f"{destination.name}.part")
    if force:
        partial.unlink(missing_ok=True)
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > max_bytes:
        raise DownloadError("Existing partial file exceeds the configured safety limit")

    headers = {"User-Agent": USER_AGENT}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = Request(url, headers=headers)

    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            content_length = response.headers.get("Content-Length")
            response_size = int(content_length) if content_length else None
            resumed = offset > 0 and getattr(response, "status", None) == 206
            expected_total = offset + response_size if resumed and response_size else response_size
            if expected_total is not None and expected_total > max_bytes:
                raise DownloadError(
                    f"Server reports {expected_total:,} bytes; limit is {max_bytes:,} bytes"
                )
            mode = "ab" if resumed else "wb"
            initial = offset if resumed else 0
            with partial.open(mode) as target:
                size = _copy_response(response, target, max_bytes, initial)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise DownloadError(f"Could not download {url}: {exc}") from exc

    if expected_magic and not has_magic(partial, expected_magic):
        partial.unlink(missing_ok=True)
        raise DownloadError("Downloaded content has an unexpected file signature")
    actual_digest = sha256_file(partial)
    if actual_digest != expected_sha256:
        partial.unlink(missing_ok=True)
        raise DownloadError("Downloaded content failed trusted SHA-256 verification")
    if destination.exists():
        destination.unlink()
    shutil.move(str(partial), str(destination))
    return DownloadResult(destination, size, actual_digest, False)
