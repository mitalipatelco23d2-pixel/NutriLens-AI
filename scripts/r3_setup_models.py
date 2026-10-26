"""Explicitly download selected free/open pretrained R3 models into a controlled cache."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Opt-in R3 pretrained-model setup; downloads are never part of CI."
    )
    parser.add_argument("--cache", type=Path, default=Path(".model-cache/r3"))
    parser.add_argument("--yolo", action="store_true", help="Download YOLO11n COCO weights.")
    parser.add_argument("--paddle", action="store_true", help="Prepare PaddleOCR English models.")
    parser.add_argument("--easy", action="store_true", help="Prepare EasyOCR English models.")
    args = parser.parse_args()
    if not any((args.yolo, args.paddle, args.easy)):
        parser.error("Select at least one of --yolo, --paddle, or --easy.")

    cache = args.cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    print(f"Controlled R3 model cache: {cache}")
    if args.yolo:
        from ultralytics import YOLO

        original = Path.cwd()
        try:
            os.chdir(cache)
            YOLO("yolo11n.pt")
        finally:
            os.chdir(original)
        print("Prepared YOLO11n PRETRAINED COCO weights (Ultralytics AGPL-3.0 distribution).")
    if args.paddle:
        os.environ["PADDLE_PDX_CACHE_HOME"] = str(cache / "paddle")
        from paddleocr import PaddleOCR

        PaddleOCR(
            enable_mkldnn=False,
            lang="en",
            device="cpu",
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="PP-OCRv5_mobile_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
        print("Prepared PaddleOCR pretrained English models; see PaddleOCR model licences.")
    if args.easy:
        import easyocr

        easyocr.Reader(
            ["en"],
            gpu=False,
            model_storage_directory=str(cache / "easyocr"),
            download_enabled=True,
            verbose=False,
        )
        print("Prepared EasyOCR pretrained English models (Apache-2.0 project).")


if __name__ == "__main__":
    main()
