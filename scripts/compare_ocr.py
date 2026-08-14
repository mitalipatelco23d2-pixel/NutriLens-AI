from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from backend.app.services.ocr_comparison import benchmark_ocr_engine


def _ground_truth(path: Path | None) -> dict[str, float] | None:
    if path is None:
        return None
    data: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("ground truth must be a JSON object")
    return {str(key): float(value) for key, value in data.items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the development Tesseract benchmark.")
    parser.add_argument("image", type=Path)
    parser.add_argument("--engine", choices=("tesseract",), default="tesseract")
    parser.add_argument("--ground-truth", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = benchmark_ocr_engine(
        args.image.read_bytes(),
        "tesseract",
        ground_truth=_ground_truth(args.ground_truth),
    )
    payload = {"image": args.image.name, "engine": "tesseract", **result}
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
