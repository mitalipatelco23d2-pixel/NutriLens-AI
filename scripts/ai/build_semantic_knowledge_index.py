"""Build and validate the optional governed Sentence-BERT/FAISS knowledge index."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from ai.rag.semantic_retrieval import (
    SentenceBertEncoder,
    build_semantic_index,
    load_semantic_retriever,
)
from backend.knowledge_api import semantic_knowledge_documents

MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_LICENSE = "Apache-2.0"


def _download_model(model_dir: Path) -> str:
    sentence_transformers = import_module("sentence_transformers")
    huggingface_hub = import_module("huggingface_hub")
    model_type = sentence_transformers.SentenceTransformer
    model = model_type(MODEL_ID, device="cpu")
    model_dir.parent.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(model_dir))
    info = huggingface_hub.HfApi().model_info(MODEL_ID)
    revision = getattr(info, "sha", None)
    if not isinstance(revision, str) or not revision:
        raise RuntimeError("Unable to resolve the embedding model revision.")
    return revision


def _load_evaluation(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list) or not cases:
        raise RuntimeError("Semantic evaluation must contain a non-empty cases array.")
    return [case for case in cases if isinstance(case, dict)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, default=Path(".model-cache/rag/all-MiniLM-L6-v2"))
    parser.add_argument("--index-dir", type=Path, default=Path("databases/faiss/knowledge"))
    parser.add_argument(
        "--evaluation", type=Path, default=Path("data/evaluation/rag-semantic-v0.1.0.json")
    )
    parser.add_argument(
        "--report", type=Path, default=Path("reports/rag/semantic-rag-validation.json")
    )
    parser.add_argument("--download-model", action="store_true")
    parser.add_argument("--model-revision", default="local-unresolved")
    args = parser.parse_args()

    revision = _download_model(args.model_dir) if args.download_model else args.model_revision
    documents = semantic_knowledge_documents()
    encoder = SentenceBertEncoder(args.model_dir)
    build_started = time.perf_counter()
    manifest = build_semantic_index(
        documents,
        encoder,
        args.index_dir,
        model_id=MODEL_ID,
        model_revision=revision,
        model_license=MODEL_LICENSE,
    )
    build_ms = (time.perf_counter() - build_started) * 1000
    retriever = load_semantic_retriever(
        documents,
        encoder,
        args.index_dir,
        expected_model_id=MODEL_ID,
    )

    cases = _load_evaluation(args.evaluation)
    latencies: list[float] = []
    results: list[dict[str, Any]] = []
    passed = 0
    for case in cases:
        query = str(case["query"])
        expected = {str(value) for value in case["expected_document_ids"]}
        top_k = int(case.get("top_k", 5))
        started = time.perf_counter()
        hits = retriever.retrieve(
            query,
            limit=top_k,
            min_score=float(case.get("min_score", 0.35)),
        )
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        actual = [hit.document.document_id for hit in hits]
        expect_no_hits = bool(case.get("expect_no_hits", False))
        case_passed = not actual if expect_no_hits else bool(expected.intersection(actual))
        passed += int(case_passed)
        results.append(
            {
                "case_id": str(case["case_id"]),
                "passed": case_passed,
                "latency_ms": round(latency_ms, 3),
                "expected_document_ids": sorted(expected),
                "expect_no_hits": expect_no_hits,
                "top_document_ids": actual,
                "top_scores": [hit.score for hit in hits],
            }
        )

    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "1.0.0",
        "validated_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if passed == len(cases) else "FAIL",
        "scope": "LOCAL_ONLY_GOVERNED_RETRIEVAL",
        "model_id": manifest.model_id,
        "model_revision": manifest.model_revision,
        "model_license": manifest.model_license,
        "faiss_index": manifest.index_kind,
        "corpus_sha256": manifest.corpus_sha256,
        "document_count": len(manifest.document_ids),
        "documents_with_references": sum(bool(item.reference_ids) for item in documents),
        "dimensions": manifest.dimensions,
        "build_ms": round(build_ms, 3),
        "evaluation": {
            "passed": passed,
            "total": len(cases),
            "recall_at_k": round(passed / len(cases), 4),
            "latency_p50_ms": round(statistics.median(latencies), 3),
            "latency_p95_ms": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 3),
            "cases": results,
        },
        "authorization": "API route requires a verified NutriLens bearer session.",
        "fallback": "Governed lexical retrieval remains active if semantic artifacts fail.",
        "claims_boundary": (
            "Similarity ranks governed taxonomy records only; it does not establish diagnosis, "
            "health effects, product composition, or nutritional equivalence."
        ),
    }
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "model_id", "document_count")}))
    if report["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
