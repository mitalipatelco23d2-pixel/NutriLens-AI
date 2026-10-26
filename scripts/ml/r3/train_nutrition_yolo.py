"""Reproducible R3 nutrition-table YOLO11 training entry point."""

from __future__ import annotations

import argparse
import json
import os
import platform
import time
from pathlib import Path

import torch
import ultralytics
import yaml
from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--base-model", type=Path, required=True)
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--patience", type=int, default=5)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_root = args.data_root.resolve()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for this training entry point.")
    if not args.base_model.is_file():
        raise FileNotFoundError(args.base_model)
    for split in ("train", "val", "test"):
        if not (data_root / "images" / split).is_dir():
            raise FileNotFoundError(data_root / "images" / split)
        if not (data_root / "labels" / split).is_dir():
            raise FileNotFoundError(data_root / "labels" / split)

    # Generate a runtime-only YAML so the same tracked preparation code works on
    # Windows and under WSL without committing host-specific absolute paths.
    runtime_yaml = data_root / ".runtime-data-wsl.yaml"
    runtime_yaml.write_text(
        yaml.safe_dump(
            {
                "path": str(data_root),
                "train": "images/train",
                "val": "images/val",
                "test": "images/test",
                "names": {0: "nutrition_table"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    # This is an actual GPU operation, not just a driver visibility check.
    smoke = torch.randn((512, 512), device="cuda")
    smoke_result = smoke @ smoke
    torch.cuda.synchronize()
    environment = {
        "platform": platform.platform(),
        "torch": torch.__version__,
        "torch_cuda_runtime": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "gpu": torch.cuda.get_device_name(0),
        "gpu_total_memory_bytes": torch.cuda.get_device_properties(0).total_memory,
        "cuda_tensor_smoke": float(smoke_result[0, 0]),
        "ultralytics": ultralytics.__version__,
        "seed": args.seed,
    }
    args.project.mkdir(parents=True, exist_ok=True)
    (args.project / f"{args.name}-environment.json").write_text(
        json.dumps(environment, indent=2), encoding="utf-8"
    )
    print(json.dumps(environment, indent=2), flush=True)

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    started = time.perf_counter()
    if args.resume_from is not None:
        if not args.resume_from.is_file():
            raise FileNotFoundError(args.resume_from)
        model = YOLO(str(args.resume_from.resolve()))
        result = model.train(resume=True, device=0, workers=args.workers)
    else:
        model = YOLO(str(args.base_model.resolve()))
        result = model.train(
            data=str(runtime_yaml),
            epochs=args.epochs,
            imgsz=args.image_size,
            batch=args.batch,
            device=0,
            workers=args.workers,
            patience=args.patience,
            seed=args.seed,
            deterministic=True,
            project=str(args.project.resolve()),
            name=args.name,
            exist_ok=True,
            optimizer="auto",
            degrees=7.0,
            translate=0.05,
            scale=0.20,
            perspective=0.001,
            hsv_v=0.18,
            fliplr=0.0,
            mosaic=0.10,
            erasing=0.15,
            amp=True,
            plots=True,
        )
    elapsed_seconds = time.perf_counter() - started
    summary = {
        "elapsed_seconds": elapsed_seconds,
        "save_dir": str(result.save_dir),
        "epochs_requested": args.epochs,
        "image_size": args.image_size,
        "batch": args.batch,
        "patience": args.patience,
        "workers": args.workers,
    }
    (args.project / f"{args.name}-training-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
