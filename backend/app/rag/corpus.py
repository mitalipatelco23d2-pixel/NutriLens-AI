"""Load and validate the locally built, source-backed RAG corpus."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .models import CorpusPassage, CorpusSource


class CorpusUnavailableError(RuntimeError):
    """The optional RAG corpus is absent, stale, corrupt, or unverified."""


def normalized_passage_hash(
    doc_id: str,
    text: str,
    *,
    page: int | None,
    heading: str | None,
) -> str:
    payload = json.dumps(
        {
            "doc_id": doc_id,
            "heading": heading,
            "page": page,
            "text": " ".join(text.split()),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class LoadedCorpus:
    corpus_id: str
    corpus_version: str
    sources: dict[str, CorpusSource]
    passages: tuple[CorpusPassage, ...]

    @classmethod
    def load(
        cls,
        directory: Path,
        *,
        jurisdiction: str,
        today: date | None = None,
    ) -> "LoadedCorpus":
        root = Path(directory)
        manifest_path = root / "manifest.json"
        chunks_path = root / "chunks.jsonl"
        if not manifest_path.is_file() or not chunks_path.is_file():
            raise CorpusUnavailableError(
                "The optional source-backed RAG corpus is unavailable."
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CorpusUnavailableError("The RAG corpus manifest is invalid.") from exc
        if manifest.get("schema_version") != 1:
            raise CorpusUnavailableError("The RAG corpus schema version is unsupported.")

        current = today or date.today()
        wanted = jurisdiction.strip().upper()
        sources: dict[str, CorpusSource] = {}
        try:
            for raw_source in manifest.get("sources") or []:
                source = CorpusSource.model_validate(raw_source)
                if source.doc_id in sources:
                    raise CorpusUnavailableError(
                        f"The RAG corpus repeats source {source.doc_id}."
                    )
                effective = date.fromisoformat(source.effective_date) if source.effective_date else None
                review_after = date.fromisoformat(source.review_after)
                if effective and effective > current:
                    continue
                if review_after < current:
                    continue
                if source.jurisdiction.upper() not in {wanted, "GLOBAL"}:
                    continue
                sources[source.doc_id] = source
        except (ValidationError, ValueError) as exc:
            raise CorpusUnavailableError("The RAG source metadata is invalid.") from exc
        if not sources:
            raise CorpusUnavailableError(
                "The RAG corpus has no current sources for the configured jurisdiction."
            )

        passages: list[CorpusPassage] = []
        try:
            with chunks_path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    if not line.strip():
                        continue
                    passage = CorpusPassage.model_validate_json(line)
                    if passage.doc_id not in sources:
                        continue
                    actual_hash = normalized_passage_hash(
                        passage.doc_id,
                        passage.text,
                        page=passage.page,
                        heading=passage.heading,
                    )
                    if actual_hash != passage.chunk_sha256:
                        raise CorpusUnavailableError(
                            f"RAG passage hash mismatch at line {line_number}."
                        )
                    passages.append(passage)
        except CorpusUnavailableError:
            raise
        except (OSError, UnicodeError, ValidationError, ValueError) as exc:
            raise CorpusUnavailableError("The RAG passage index is invalid.") from exc
        if not passages:
            raise CorpusUnavailableError(
                "The RAG corpus has no usable passages for the configured jurisdiction."
            )
        return cls(
            corpus_id=str(manifest.get("corpus_id") or "nutrilens_official_sources"),
            corpus_version=str(manifest.get("corpus_version") or "unknown"),
            sources=sources,
            passages=tuple(passages),
        )

    def public_metadata(self) -> dict[str, Any]:
        return {
            "corpus_id": self.corpus_id,
            "corpus_version": self.corpus_version,
            "source_count": len(self.sources),
            "passage_count": len(self.passages),
        }
