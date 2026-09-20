"""Build the local source-backed RAG corpus outside request handling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.app.rag.builder import build_corpus


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-manifest",
        type=Path,
        default=REPOSITORY_ROOT / "backend" / "app" / "rag" / "sources.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPOSITORY_ROOT / "data" / "processed" / "rag",
    )
    parser.add_argument(
        "--review-unpinned",
        action="store_true",
        help="Build once to obtain candidate extracted-text hashes for human review.",
    )
    args = parser.parse_args()
    result = build_corpus(
        args.source_manifest,
        args.output_dir,
        review_unpinned=args.review_unpinned,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
