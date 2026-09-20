"""Evaluate local RAG retrieval against the reviewed labelled query set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.app.rag.corpus import LoadedCorpus
from backend.app.rag.retriever import BM25Retriever


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "processed" / "rag",
    )
    parser.add_argument(
        "--eval-set",
        type=Path,
        default=REPOSITORY_ROOT / "backend" / "app" / "rag" / "retrieval_eval.json",
    )
    parser.add_argument("--min-score", type=float, default=1.0)
    args = parser.parse_args()
    labelled = json.loads(args.eval_set.read_text(encoding="utf-8"))
    cases = labelled["cases"]
    reciprocal_ranks: list[float] = []
    recall_at_3: list[float] = []
    rows: list[dict[str, object]] = []
    for case in cases:
        corpus = LoadedCorpus.load(args.corpus_dir, jurisdiction=case["jurisdiction"])
        results = BM25Retriever(
            corpus, top_k=3, min_score=args.min_score, max_per_source=2
        ).search(case["query"])
        returned = [item.source.doc_id for item in results]
        expected = set(case["expected_doc_ids"])
        if not expected:
            rank = 1.0 if not results else 0.0
            recall = 1.0 if not results else 0.0
        else:
            first_rank = next(
                (index for index, doc_id in enumerate(returned, start=1) if doc_id in expected),
                None,
            )
            rank = 1.0 / first_rank if first_rank else 0.0
            recall = len(expected.intersection(returned[:3])) / len(expected)
        reciprocal_ranks.append(rank)
        recall_at_3.append(recall)
        rows.append(
            {
                "id": case["id"],
                "expected": sorted(expected),
                "returned": returned,
                "top_score": results[0].score if results else None,
            }
        )
    output = {
        "cases": len(cases),
        "mean_reciprocal_rank": round(sum(reciprocal_ranks) / len(cases), 4),
        "mean_recall_at_3": round(sum(recall_at_3) / len(cases), 4),
        "threshold": args.min_score,
        "results": rows,
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
