"""Validate the governed R3 custom-model registry entry and local artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY = REPO_ROOT / "ai/model-registry/r3-models.json"
REQUIRED_FIELDS = {
    "model_id",
    "name",
    "base_model",
    "task",
    "training_status",
    "training_dataset",
    "dataset_version",
    "train_manifest",
    "validation_manifest",
    "test_manifest",
    "pipeline_version",
    "framework",
    "training_parameters",
    "configuration",
    "metrics",
    "local_file",
    "checksum",
    "license",
    "created_at",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(*, metadata_only: bool = False) -> int:
    payload: dict[str, Any] = json.loads(REGISTRY.read_text(encoding="utf-8"))
    models = payload.get("models")
    if not isinstance(models, list):
        raise ValueError("registry models must be a list")
    custom = [model for model in models if model.get("training_status") == "CUSTOM_FINE_TUNED"]
    if len(custom) != 1:
        raise ValueError("R3 registry must contain exactly one custom fine-tuned model")
    model = custom[0]
    missing = sorted(REQUIRED_FIELDS - model.keys())
    if missing:
        raise ValueError(f"custom model is missing fields: {missing}")

    for split in ("train_manifest", "validation_manifest", "test_manifest"):
        manifest = model[split]
        path = REPO_ROOT / manifest["path"]
        actual = sha256_file(path)
        if actual != manifest["sha256"]:
            raise ValueError(f"{split} checksum mismatch")

    weight_path = REPO_ROOT / model["local_file"]
    artifact_status = "METADATA_ONLY"
    if not metadata_only:
        if not weight_path.is_file():
            raise ValueError("custom model weight is absent")
        if sha256_file(weight_path) != model["checksum"]:
            raise ValueError("custom model weight checksum mismatch")
        if weight_path.stat().st_size != model["weights_bytes"]:
            raise ValueError("custom model weight size mismatch")
        artifact_status = "CHECKSUM_AND_SIZE_VERIFIED"

    held_out = model["metrics"].get("held_out_test", {})
    for metric in ("precision", "recall", "f1", "map50", "map50_95", "mean_matched_iou"):
        value = held_out.get(metric)
        if not isinstance(value, int | float) or not 0 <= value <= 1:
            raise ValueError(f"invalid held-out metric: {metric}")

    print(
        json.dumps(
            {
                "status": "PASS",
                "model_id": model["model_id"],
                "training_status": model["training_status"],
                "weight_sha256": model["checksum"],
                "split_checksums": "PASS",
                "held_out_metrics": "VALID_RANGE",
                "artifact_status": artifact_status,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="Validate tracked metadata and split manifests without requiring ignored weights.",
    )
    arguments = parser.parse_args()
    raise SystemExit(main(metadata_only=arguments.metadata_only))
