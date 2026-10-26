# Optional governed semantic retrieval

## Release decision

Sentence-BERT and FAISS are validated as a separate, optional CPU subsystem. They are not a
dependency of scanning, Android ML Kit OCR, the web API, or the server vision worker. This keeps
the core scan result independent of an embedding model and avoids adding roughly 100 MB of
local artifacts plus the Python ML runtime to the 2-GiB worker.

## Trust and authorization boundary

Only public governed taxonomy records are indexed. User scans, OCR text, account data and
assistant prompts are not written into the FAISS index. The semantic API route requires the
normal authenticated NutriLens owner session. The client cannot select a different corpus,
model, index path, user or entitlement.

Each returned hit resolves back to its server-owned `KnowledgeRecord`, preserving the source
dataset, source version and primary reference objects. No free-form model answer is generated.
If the feature is disabled or its dependency, model, manifest, checksum or index is invalid,
the API uses deterministic lexical retrieval.

## Artifact governance

The selected model is `sentence-transformers/all-MiniLM-L6-v2`, pinned by revision in each
generated manifest and documented by its publisher as Apache-2.0. Sentence Transformers is
Apache-2.0 and FAISS is MIT licensed. Distribution must retain the applicable notices. This
review is independent of the unresolved custom YOLO distribution gate.

Primary sources:

- Model card and license: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- Sentence Transformers license: https://github.com/huggingface/sentence-transformers/blob/main/LICENSE
- FAISS license: https://github.com/facebookresearch/faiss/blob/main/LICENSE
- Sentence Transformers semantic-search design: https://sbert.net/examples/sentence_transformer/applications/semantic-search/README.html

Model weights and FAISS artifacts remain untracked under `.model-cache/rag/` and
`databases/faiss/knowledge/`. The tracked validation report contains only model metadata,
corpus checksum, bounded query cases, record IDs, scores and aggregate latency—no secrets or
user content.

## Current validation

See `reports/rag/semantic-rag-validation.json`. The local run covers 6,310 governed records,
checks citation coverage, records a fixed model revision, includes a nonsense-query unknown
case, and measures index build and retrieval latency. This is local technical validation, not
public production readiness or proof of health claims.
