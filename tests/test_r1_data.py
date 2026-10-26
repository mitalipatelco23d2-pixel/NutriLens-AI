from __future__ import annotations

import hashlib
import http.server
import threading
from pathlib import Path

import pytest

from scripts.data.safe_download import DownloadError, download, resolve_destination, sha256_file
from scripts.r1_validation import (
    ACQUISITION_STATUSES,
    duplicate_values,
    invalid_values,
    missing_license_ids,
    read_csv,
    validate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        del format, args


def test_r1_governance_is_valid() -> None:
    assert validate(REPO_ROOT, require_downloads=False) == []


def test_duplicate_dataset_ids_are_detected() -> None:
    rows = [{"Dataset ID": "A"}, {"Dataset ID": "A"}, {"Dataset ID": "B"}]
    assert duplicate_values(rows, "Dataset ID") == {"A"}


def test_invalid_status_is_detected() -> None:
    rows = [{"Acquisition status": "AVAILABLE"}, {"Acquisition status": "MADE_UP"}]
    assert invalid_values(rows, "Acquisition status", ACQUISITION_STATUSES) == {"MADE_UP"}


def test_missing_license_record_is_detected() -> None:
    catalogue = [{"Dataset ID": "A"}, {"Dataset ID": "B"}]
    licences = [{"Dataset ID": "A"}]
    assert missing_license_ids(catalogue, licences) == {"B"}


def test_destination_cannot_escape_repository(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes repository"):
        resolve_destination(tmp_path, "../outside.bin")


def test_checksum_utility(tmp_path: Path) -> None:
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"NutriLens R1")
    assert sha256_file(payload) == hashlib.sha256(b"NutriLens R1").hexdigest()


def test_downloader_is_bounded_and_does_not_overwrite(tmp_path: Path) -> None:
    served = tmp_path / "served"
    served.mkdir()
    (served / "source.bin").write_bytes(b"first payload")
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(served), **kwargs)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        destination = tmp_path / "destination.bin"
        url = f"http://127.0.0.1:{server.server_port}/source.bin"
        expected = hashlib.sha256(b"first payload").hexdigest()
        first = download(url, destination, max_bytes=100, expected_sha256=expected)
        assert first.reused_existing is False
        (served / "source.bin").write_bytes(b"changed upstream")
        second = download(url, destination, max_bytes=100, expected_sha256=expected)
        assert second.reused_existing is True
        assert destination.read_bytes() == b"first payload"
    finally:
        server.shutdown()
        server.server_close()


def test_downloader_rejects_non_http_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="HTTP"):
        download(
            "file:///tmp/source",
            tmp_path / "destination.bin",
            max_bytes=100,
            expected_sha256="0" * 64,
        )


def test_downloader_rejects_untrusted_digest(tmp_path: Path) -> None:
    served = tmp_path / "served-digest"
    served.mkdir()
    (served / "source.bin").write_bytes(b"unexpected")
    handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(served), **kwargs)  # noqa: E731
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(DownloadError, match="SHA-256"):
            download(
                f"http://127.0.0.1:{server.server_port}/source.bin",
                tmp_path / "untrusted.bin",
                max_bytes=100,
                expected_sha256="0" * 64,
            )
    finally:
        server.shutdown()
        server.server_close()


def test_acquisition_manifest_schema_and_hashes() -> None:
    fields, rows = read_csv(REPO_ROOT / "data/manifests/downloaded-artifacts.csv")
    required = {
        "Dataset ID",
        "Source URL",
        "Download date UTC",
        "Version",
        "Size bytes",
        "SHA-256",
        "Local path",
        "Privacy status",
    }
    assert required.issubset(fields)
    assert rows
    assert all(int(row["Size bytes"]) > 0 for row in rows)
    assert all(len(row["SHA-256"]) == 64 for row in rows)
    assert all(set(row["SHA-256"]) <= set("0123456789abcdef") for row in rows)
