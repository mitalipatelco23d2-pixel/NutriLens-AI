# ADR-007 — FAISS vector retrieval

**Status:** Accepted for planned R15 work

**Context:** Semantic product/evidence retrieval requires local nearest-neighbour search.
**Decision:** Use a file-backed FAISS index.
**Rationale:** Free local similarity search without a new service.
**Alternatives:** pgvector, managed vector databases.
**Consequences:** Index versioning, metadata linkage and rebuilds are application responsibilities.
