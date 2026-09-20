"""Reproducible offline builder for the verified NutriLens RAG corpus."""

from __future__ import annotations

import hashlib
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any

from .corpus import normalized_passage_hash


MAX_DOWNLOAD_BYTES = 12 * 1024 * 1024
ALLOWED_CONTENT_TYPES = {"application/pdf", "text/html"}
ALLOWED_REDISTRIBUTION_MODES = {
    "fetch_at_build_time",
    "public_domain",
    "redistributable_with_attribution",
}


class CorpusBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class DownloadedDocument:
    body: bytes
    content_type: str
    final_url: str


@dataclass(frozen=True)
class ExtractionUnit:
    text: str
    page: int | None
    heading: str | None


class _RestrictedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_domains: set[str]) -> None:
        super().__init__()
        self.allowed_domains = allowed_domains

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        _validate_url(newurl, self.allowed_domains)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_url(url: str, allowed_domains: set[str]) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise CorpusBuildError("Corpus sources must use allowlisted HTTPS URLs.")
    if parsed.hostname.casefold() not in allowed_domains:
        raise CorpusBuildError(f"Corpus source domain is not allowlisted: {parsed.hostname}")
    if parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise CorpusBuildError("Corpus source URL contains unsupported authority data.")


def download_document(
    url: str,
    *,
    allowed_domains: set[str],
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> DownloadedDocument:
    _validate_url(url, allowed_domains)
    opener = urllib.request.build_opener(
        _RestrictedRedirectHandler(allowed_domains),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "NutriLens-AI-corpus-builder/1.0"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=30) as response:
            final_url = response.geturl()
            _validate_url(final_url, allowed_domains)
            content_type = response.headers.get_content_type().casefold()
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise CorpusBuildError(
                    f"Unsupported source content type: {content_type or 'missing'}"
                )
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > max_bytes:
                raise CorpusBuildError("Corpus source exceeds the download-size limit.")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise CorpusBuildError("Corpus source exceeds the download-size limit.")
            return DownloadedDocument(body, content_type, final_url)
    except CorpusBuildError:
        raise
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise CorpusBuildError(f"Could not download official source: {url}") from exc


class _ReadableHtmlParser(HTMLParser):
    BLOCK_TAGS = {"p", "li", "td", "th", "blockquote"}
    HEADING_TAGS = {"h1", "h2", "h3", "h4"}
    IGNORED_TAGS = {"script", "style", "nav", "footer", "header", "form", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._capture_tag: str | None = None
        self._buffer: list[str] = []
        self._heading: str | None = None
        self.units: list[ExtractionUnit] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if tag in self.IGNORED_TAGS:
            self._ignored_depth += 1
        if self._ignored_depth == 0 and tag in self.BLOCK_TAGS | self.HEADING_TAGS:
            self._capture_tag = tag
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self.IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth or tag != self._capture_tag:
            return
        text = " ".join(" ".join(self._buffer).split())
        if tag in self.HEADING_TAGS:
            self._heading = text[:500] or self._heading
        elif len(text) >= 40:
            self.units.append(ExtractionUnit(text, None, self._heading))
        self._capture_tag = None
        self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0 and self._capture_tag:
            self._buffer.append(data)


def extract_document(document: DownloadedDocument) -> list[ExtractionUnit]:
    if document.content_type == "text/html":
        parser = _ReadableHtmlParser()
        parser.feed(document.body.decode("utf-8", errors="replace"))
        return parser.units
    if document.content_type == "application/pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise CorpusBuildError("pypdf is required to extract approved PDF sources.") from exc
        try:
            reader = PdfReader(BytesIO(document.body))
            units: list[ExtractionUnit] = []
            for page_number, page in enumerate(reader.pages, start=1):
                text = "\n".join(
                    " ".join(line.split())
                    for line in (page.extract_text() or "").splitlines()
                    if line.strip()
                )
                if len(text) >= 40:
                    units.append(ExtractionUnit(text, page_number, None))
            return units
        except Exception as exc:
            raise CorpusBuildError("The approved PDF source could not be extracted.") from exc
    raise CorpusBuildError("Unsupported corpus document type.")


def extracted_text_sha256(units: list[ExtractionUnit]) -> str:
    normalized = "\n".join(
        f"{item.page or ''}|{item.heading or ''}|{' '.join(item.text.split())}"
        for item in units
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _split_words(text: str, *, target_words: int = 420, overlap_words: int = 60) -> list[str]:
    words = text.split()
    if len(words) <= target_words:
        return [" ".join(words)] if words else []
    chunks: list[str] = []
    step = target_words - overlap_words
    for start in range(0, len(words), step):
        chunk = words[start : start + target_words]
        if len(chunk) < 35 and chunks:
            break
        chunks.append(" ".join(chunk))
        if start + target_words >= len(words):
            break
    return chunks


def chunk_units(doc_id: str, units: list[ExtractionUnit]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for unit in units:
        for text in _split_words(unit.text):
            digest = normalized_passage_hash(
                doc_id,
                text,
                page=unit.page,
                heading=unit.heading,
            )
            chunks.append(
                {
                    "chunk_id": f"{re.sub(r'[^a-z0-9]+', '_', doc_id.casefold()).strip('_')}_{digest[:16]}",
                    "doc_id": doc_id,
                    "text": text,
                    "page": unit.page,
                    "heading": unit.heading,
                    "chunk_sha256": digest,
                }
            )
    return chunks


def build_corpus(
    source_manifest_path: Path,
    output_dir: Path,
    *,
    review_unpinned: bool = False,
    downloader=download_document,
) -> dict[str, Any]:
    source_manifest = json.loads(Path(source_manifest_path).read_text(encoding="utf-8"))
    if source_manifest.get("schema_version") != 1:
        raise CorpusBuildError("Unsupported source-manifest schema.")
    allowed_domains = {
        str(item).casefold() for item in source_manifest.get("allowed_domains") or []
    }
    if not allowed_domains:
        raise CorpusBuildError("The source-domain allowlist is empty.")

    today = date.today()
    built_sources: list[dict[str, Any]] = []
    all_chunks: list[dict[str, Any]] = []
    review_hashes: dict[str, str] = {}
    raw_dir = Path(output_dir) / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for raw in source_manifest.get("sources") or []:
        if raw.get("enabled") is not True or raw.get("verification_status") != "verified":
            continue
        if raw.get("redistribution_mode") not in ALLOWED_REDISTRIBUTION_MODES:
            continue
        effective_date = raw.get("effective_date")
        if effective_date and date.fromisoformat(effective_date) > today:
            continue
        if date.fromisoformat(raw["review_after"]) < today:
            raise CorpusBuildError(f"Source review is stale: {raw['doc_id']}")
        document = downloader(raw["canonical_url"], allowed_domains=allowed_domains)
        if document.content_type != raw["content_type"]:
            raise CorpusBuildError(f"Content type changed for source {raw['doc_id']}")
        units = extract_document(document)
        if not units:
            raise CorpusBuildError(f"No usable text was extracted from {raw['doc_id']}")
        raw_sha256 = hashlib.sha256(document.body).hexdigest()
        extracted_sha256 = extracted_text_sha256(units)
        review_hashes[raw["doc_id"]] = extracted_sha256
        expected = raw.get("expected_extracted_sha256")
        if not expected and not review_unpinned:
            raise CorpusBuildError(f"Source is not hash-pinned: {raw['doc_id']}")
        if expected and expected != extracted_sha256:
            raise CorpusBuildError(f"Extracted source hash changed: {raw['doc_id']}")
        suffix = ".pdf" if document.content_type == "application/pdf" else ".html"
        (raw_dir / f"{raw['doc_id']}{suffix}").write_bytes(document.body)
        source_record = {
            key: raw.get(key)
            for key in (
                "doc_id",
                "title",
                "organization",
                "canonical_url",
                "jurisdiction",
                "publication_date",
                "revision_date",
                "effective_date",
                "review_after",
                "topics",
                "license_name",
                "license_url",
                "redistribution_mode",
                "verified_on",
            )
        }
        source_record.update(
            {"extracted_sha256": extracted_sha256, "raw_sha256": raw_sha256}
        )
        built_sources.append(source_record)
        all_chunks.extend(chunk_units(raw["doc_id"], units))

    if not built_sources or not all_chunks:
        raise CorpusBuildError("No verified source passages were built.")
    built_sources.sort(key=lambda item: item["doc_id"])
    all_chunks.sort(key=lambda item: item["chunk_id"])
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": 1,
        "corpus_id": source_manifest.get("corpus_id", "nutrilens_official_sources"),
        "corpus_version": source_manifest["corpus_version"],
        "built_at": datetime.now(timezone.utc).isoformat(),
        "sources": built_sources,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (output / "chunks.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for chunk in all_chunks:
            stream.write(json.dumps(chunk, ensure_ascii=False, separators=(",", ":")) + "\n")
    return {
        "source_count": len(built_sources),
        "chunk_count": len(all_chunks),
        "review_hashes": review_hashes,
        "output_dir": str(output.resolve()),
    }
