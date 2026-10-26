from __future__ import annotations

from dataclasses import replace

import numpy as np

from ai.rag.semantic_retrieval import (
    SemanticArtifactMismatch,
    SemanticDocument,
    SemanticIndexManifest,
    SemanticRetriever,
    corpus_sha256,
)


class FakeEncoder:
    dimensions = 2

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return np.asarray([[1.0, 0.0] for _ in texts], dtype=np.float32)

    def encode_query(self, text: str) -> np.ndarray:
        del text
        return np.asarray([[1.0, 0.0]], dtype=np.float32)


class FakeIndex:
    dimensions = 2
    size = 2

    def search(self, query: np.ndarray, limit: int) -> tuple[tuple[int, float], ...]:
        assert query.shape == (1, 2)
        return ((0, 0.91), (1, 0.2))[:limit]


def _documents() -> tuple[SemanticDocument, ...]:
    return (
        SemanticDocument("one", "soy lecithin", "taxonomy", "1", ("citation-1",)),
        SemanticDocument("two", "citrus pectin", "taxonomy", "1", ("citation-2",)),
    )


def test_semantic_retriever_bounds_query_and_applies_score_gate() -> None:
    retriever = SemanticRetriever(_documents(), FakeEncoder(), FakeIndex())  # type: ignore[arg-type]

    hits = retriever.retrieve("soy emulsifier", limit=2, min_score=0.35)

    assert [hit.document.document_id for hit in hits] == ["one"]
    assert hits[0].document.reference_ids == ("citation-1",)
    assert retriever.retrieve(" ") == []
    assert retriever.retrieve("x" * 501) == []


def test_corpus_hash_binds_text_and_provenance() -> None:
    documents = _documents()
    assert corpus_sha256(documents) == corpus_sha256(documents)
    changed = (replace(documents[0], reference_ids=("different",)), documents[1])
    assert corpus_sha256(documents) != corpus_sha256(changed)


def test_manifest_rejects_incomplete_json() -> None:
    try:
        SemanticIndexManifest.from_json('{"schema_version":"1"}')
    except SemanticArtifactMismatch as exc:
        assert "incomplete or invalid" in str(exc)
    else:
        raise AssertionError("Incomplete semantic manifests must fail closed.")
