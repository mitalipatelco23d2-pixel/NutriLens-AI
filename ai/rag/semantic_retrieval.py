"""Optional, local-only Sentence-BERT and FAISS retrieval primitives.

The production API does not install or download these dependencies by default.  Callers must
provide a local model directory and a checksum-bound index built from governed documents.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import numpy.typing as npt

FloatMatrix = npt.NDArray[np.float32]


class SemanticRuntimeUnavailable(RuntimeError):
    """Raised when optional semantic artifacts or dependencies are unavailable."""


class SemanticArtifactMismatch(RuntimeError):
    """Raised when a model/index/corpus binding cannot be verified."""


@dataclass(frozen=True)
class SemanticDocument:
    """A public governed record safe to place in the semantic index."""

    document_id: str
    text: str
    source_dataset: str
    source_version: str
    reference_ids: tuple[str, ...]


@dataclass(frozen=True)
class SemanticHit:
    document: SemanticDocument
    score: float


@dataclass(frozen=True)
class SemanticIndexManifest:
    schema_version: str
    model_id: str
    model_revision: str
    model_license: str
    corpus_sha256: str
    document_ids: tuple[str, ...]
    dimensions: int
    index_kind: str
    normalized_embeddings: bool
    built_at: str

    @classmethod
    def from_json(cls, value: str) -> SemanticIndexManifest:
        raw = json.loads(value)
        if not isinstance(raw, dict):
            raise SemanticArtifactMismatch("Semantic manifest must be a JSON object.")
        try:
            return cls(
                schema_version=str(raw["schema_version"]),
                model_id=str(raw["model_id"]),
                model_revision=str(raw["model_revision"]),
                model_license=str(raw["model_license"]),
                corpus_sha256=str(raw["corpus_sha256"]),
                document_ids=tuple(str(value) for value in raw["document_ids"]),
                dimensions=int(raw["dimensions"]),
                index_kind=str(raw["index_kind"]),
                normalized_embeddings=bool(raw["normalized_embeddings"]),
                built_at=str(raw["built_at"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SemanticArtifactMismatch("Semantic manifest is incomplete or invalid.") from exc

    def to_json(self) -> str:
        payload = asdict(self)
        payload["document_ids"] = list(self.document_ids)
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"


class TextEncoder(Protocol):
    @property
    def dimensions(self) -> int: ...

    def encode_documents(self, texts: Sequence[str]) -> FloatMatrix: ...

    def encode_query(self, text: str) -> FloatMatrix: ...


def corpus_sha256(documents: Sequence[SemanticDocument]) -> str:
    """Hash the complete ordered governed corpus, including its provenance."""

    serialized = json.dumps(
        [asdict(document) for document in documents],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(serialized).hexdigest()


def _normalized_matrix(value: Any) -> FloatMatrix:
    matrix = np.asarray(value, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or not matrix.shape[0] or not matrix.shape[1]:
        raise SemanticArtifactMismatch("Encoder returned an invalid embedding matrix.")
    if not np.isfinite(matrix).all():
        raise SemanticArtifactMismatch("Encoder returned non-finite embeddings.")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms <= 0):
        raise SemanticArtifactMismatch("Encoder returned a zero-length embedding.")
    return np.ascontiguousarray(matrix / norms, dtype=np.float32)


class SentenceBertEncoder:
    """Sentence-Transformers adapter that never downloads during runtime."""

    def __init__(self, model_path: Path) -> None:
        resolved = model_path.resolve()
        if not resolved.is_dir():
            raise SemanticRuntimeUnavailable(f"Local embedding model is absent: {resolved}")
        try:
            sentence_transformers = import_module("sentence_transformers")
        except ImportError as exc:
            raise SemanticRuntimeUnavailable(
                "Install the optional semantic RAG dependencies before loading Sentence-BERT."
            ) from exc
        model_type = getattr(sentence_transformers, "SentenceTransformer", None)
        if model_type is None:
            raise SemanticRuntimeUnavailable("SentenceTransformer runtime is invalid.")
        self._model = model_type(str(resolved), local_files_only=True, device="cpu")
        dimensions_getter = getattr(
            self._model,
            "get_embedding_dimension",
            self._model.get_sentence_embedding_dimension,
        )
        dimensions = dimensions_getter()
        if not isinstance(dimensions, int) or dimensions <= 0:
            raise SemanticArtifactMismatch("Embedding model has invalid dimensions.")
        self._dimensions = dimensions

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def encode_documents(self, texts: Sequence[str]) -> FloatMatrix:
        return _normalized_matrix(
            self._model.encode(
                list(texts),
                batch_size=32,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        )

    def encode_query(self, text: str) -> FloatMatrix:
        return _normalized_matrix(
            self._model.encode(
                [text],
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        )


class FaissCosineIndex:
    """Exact cosine retrieval using normalized vectors and FAISS IndexFlatIP."""

    def __init__(self, index: Any) -> None:
        self._index = index

    @classmethod
    def build(cls, vectors: FloatMatrix) -> FaissCosineIndex:
        try:
            faiss = import_module("faiss")
        except ImportError as exc:
            raise SemanticRuntimeUnavailable(
                "Install the optional semantic RAG dependencies before building FAISS."
            ) from exc
        normalized = _normalized_matrix(vectors)
        index = faiss.IndexFlatIP(int(normalized.shape[1]))
        index.add(normalized)
        return cls(index)

    @classmethod
    def load(cls, path: Path) -> FaissCosineIndex:
        if not path.is_file():
            raise SemanticRuntimeUnavailable(f"FAISS index is absent: {path}")
        try:
            faiss = import_module("faiss")
        except ImportError as exc:
            raise SemanticRuntimeUnavailable(
                "Install the optional semantic RAG dependencies before loading FAISS."
            ) from exc
        return cls(faiss.read_index(str(path.resolve())))

    @property
    def dimensions(self) -> int:
        return int(self._index.d)

    @property
    def size(self) -> int:
        return int(self._index.ntotal)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        faiss = import_module("faiss")
        faiss.write_index(self._index, str(path.resolve()))

    def search(self, query: FloatMatrix, limit: int) -> tuple[tuple[int, float], ...]:
        normalized = _normalized_matrix(query)
        if normalized.shape[0] != 1 or normalized.shape[1] != self.dimensions:
            raise SemanticArtifactMismatch("Query dimensions do not match the FAISS index.")
        scores, indices = self._index.search(normalized, max(1, min(limit, self.size)))
        return tuple(
            (int(index), float(score))
            for index, score in zip(indices[0], scores[0], strict=True)
            if int(index) >= 0
        )


class SemanticRetriever:
    def __init__(
        self,
        documents: Sequence[SemanticDocument],
        encoder: TextEncoder,
        index: FaissCosineIndex,
    ) -> None:
        self.documents = tuple(documents)
        self.encoder = encoder
        self.index = index
        if not self.documents:
            raise SemanticArtifactMismatch("Semantic corpus is empty.")
        if self.index.size != len(self.documents):
            raise SemanticArtifactMismatch("FAISS row count does not match the governed corpus.")
        if self.index.dimensions != self.encoder.dimensions:
            raise SemanticArtifactMismatch("FAISS and encoder dimensions do not match.")

    def retrieve(self, query: str, *, limit: int = 5, min_score: float = 0.35) -> list[SemanticHit]:
        bounded_query = query.strip()
        if not bounded_query or len(bounded_query) > 500:
            return []
        hits: list[SemanticHit] = []
        for index, score in self.index.search(self.encoder.encode_query(bounded_query), limit):
            if score < min_score:
                continue
            hits.append(SemanticHit(document=self.documents[index], score=round(score, 6)))
        return hits


def build_semantic_index(
    documents: Sequence[SemanticDocument],
    encoder: TextEncoder,
    output_dir: Path,
    *,
    model_id: str,
    model_revision: str,
    model_license: str,
) -> SemanticIndexManifest:
    ordered = tuple(documents)
    if not ordered or len({document.document_id for document in ordered}) != len(ordered):
        raise SemanticArtifactMismatch("Semantic documents must be non-empty with unique IDs.")
    vectors = encoder.encode_documents([document.text for document in ordered])
    if vectors.shape != (len(ordered), encoder.dimensions):
        raise SemanticArtifactMismatch("Embedding count or dimensions do not match the corpus.")
    index = FaissCosineIndex.build(vectors)
    output_dir.mkdir(parents=True, exist_ok=True)
    index.save(output_dir / "knowledge.index")
    manifest = SemanticIndexManifest(
        schema_version="1.0.0",
        model_id=model_id,
        model_revision=model_revision,
        model_license=model_license,
        corpus_sha256=corpus_sha256(ordered),
        document_ids=tuple(document.document_id for document in ordered),
        dimensions=encoder.dimensions,
        index_kind="FAISS_INDEX_FLAT_IP_COSINE",
        normalized_embeddings=True,
        built_at=datetime.now(UTC).isoformat(),
    )
    (output_dir / "manifest.json").write_text(manifest.to_json(), encoding="utf-8")
    return manifest


def load_semantic_retriever(
    documents: Sequence[SemanticDocument],
    encoder: TextEncoder,
    index_dir: Path,
    *,
    expected_model_id: str,
) -> SemanticRetriever:
    manifest_path = index_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SemanticRuntimeUnavailable(f"Semantic manifest is absent: {manifest_path}")
    manifest = SemanticIndexManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    ordered = tuple(documents)
    if manifest.schema_version != "1.0.0":
        raise SemanticArtifactMismatch("Semantic manifest version is unsupported.")
    if manifest.model_id != expected_model_id:
        raise SemanticArtifactMismatch("Semantic model ID does not match configuration.")
    if manifest.corpus_sha256 != corpus_sha256(ordered):
        raise SemanticArtifactMismatch("Semantic corpus checksum does not match the index.")
    if manifest.document_ids != tuple(document.document_id for document in ordered):
        raise SemanticArtifactMismatch("Semantic document ordering does not match the index.")
    if manifest.dimensions != encoder.dimensions or not manifest.normalized_embeddings:
        raise SemanticArtifactMismatch("Semantic embedding configuration does not match the index.")
    return SemanticRetriever(ordered, encoder, FaissCosineIndex.load(index_dir / "knowledge.index"))
