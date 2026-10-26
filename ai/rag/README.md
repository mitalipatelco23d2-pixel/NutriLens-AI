# Evidence retrieval

NutriLens has two bounded retrieval paths over the same governed, versioned taxonomy records:

- `GOVERNED_LEXICAL_RETRIEVAL_V1` is the lightweight deterministic default.
- `GOVERNED_SENTENCE_BERT_FAISS_V1` is an optional, authenticated, local-only semantic path.

The semantic path uses `sentence-transformers/all-MiniLM-L6-v2` and exact cosine search with
FAISS `IndexFlatIP`. It is not installed in the public API or the 2-GiB vision worker. Runtime
loading is local-files-only, and the manifest binds model ID/revision, ordered document IDs,
corpus SHA-256, dimensions and normalization settings. A mismatch fails closed to lexical
retrieval.

Build and validate locally:

```powershell
.\.venv\Scripts\python.exe -m pip install -r ai\rag\requirements-semantic.txt
.\.venv\Scripts\python.exe -m scripts.ai.build_semantic_knowledge_index --download-model
```

The model and generated FAISS artifacts are ignored. The evaluation definition and sanitized
validation report remain tracked. Semantic results return the original governed record with
its source dataset/version and regulatory reference IDs. Similarity is never presented as a
health effect, diagnosis, product composition or nutritional equivalence.

The API route `/api/v1/knowledge/retrieve/authorized` requires a verified NutriLens bearer
session. It uses semantic retrieval only when `SEMANTIC_RAG_ENABLED=true` and all locally
verified artifacts are present; otherwise it returns the cited lexical fallback and an honest
semantic state.
