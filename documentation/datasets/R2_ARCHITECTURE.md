# R2 dataset architecture

R2 is a local, zero-cost Python/Pydantic data layer. It is intentionally independent of model
training, embeddings, FAISS, production Neo4j population, RAG, and application feature logic.

```text
R1 catalogue + licence register + acquisition manifest
                         |
             checksum/privacy/licence gate
                         |
             immutable raw/external sources
                         |
       streaming/source-specific parser or adapter
                         |
                 versioned interim JSONL
                         |
       canonical normalization + semantic validation
                  /                    \
       processed JSONL              quarantine JSONL
                  \                    /
        quality, statistics, splits, output SHA-256
                         |
                R3-R13 input contracts
```

OFF taxonomy blocks and OWL elements are streamed; the USDA ZIP is read table-by-table without
extracting or changing the archive. The small FAO workbook is parsed from Open XML. The WHO PDF
produces attribution/citation metadata only. Product, image, annotation/OCR, recipe, synonym, and
population contracts are present but source-dependent outputs remain empty where R1 has no
permitted payload.

Output records link directly to their original source checksum and record ID. Interim paths and
transformation manifests provide the reproducible processing step; the R1 manifest connects the
checksum to the catalogue, provider, source URL, licence review, and acquisition event.
