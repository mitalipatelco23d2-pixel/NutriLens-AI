"""Benchmark an already-running owner-controlled AI worker over loopback."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(round((len(ordered) - 1) * percentile), len(ordered) - 1)
    return ordered[index]


def _memory_bytes(value: str) -> int:
    match = re.fullmatch(r"([0-9.]+)\s*([A-Za-z]+)", value.strip())
    if match is None:
        raise ValueError(f"Unrecognized Docker memory value: {value}")
    amount, unit = match.groups()
    factors = {
        "B": 1,
        "kB": 1000,
        "KiB": 1024,
        "MB": 1000**2,
        "MiB": 1024**2,
        "GB": 1000**3,
        "GiB": 1024**3,
    }
    return round(float(amount) * factors[unit])


def _sample_container(container: str, stop: threading.Event, samples: list[dict[str, Any]]) -> None:
    while not stop.wait(0.5):
        completed = subprocess.run(
            ["docker", "stats", container, "--no-stream", "--format", "{{json .}}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            continue
        payload = json.loads(completed.stdout)
        memory_usage = payload["MemUsage"].split("/")[0].strip()
        samples.append(
            {
                "at": time.time(),
                "cpu_percent": float(payload["CPUPerc"].rstrip("%")),
                "memory_bytes": _memory_bytes(memory_usage),
                "pids": int(payload["PIDs"]),
            }
        )


def _summary(payload: dict[str, Any], request_ms: float, status_code: int) -> dict[str, Any]:
    ocr_results = list(payload.get("ocr_results", {}).values())
    selected_engines = [result.get("selected_engine") for result in ocr_results]
    return {
        "http_status": status_code,
        "request_ms": request_ms,
        "scan_id": payload.get("scan_id"),
        "scan_status": payload.get("status"),
        "pipeline_total_ms": payload.get("timings", {}).get("total_ms"),
        "detection_ms": payload.get("timings", {}).get("detection_ms"),
        "ocr_ms": payload.get("timings", {}).get("ocr_ms"),
        "extraction_ms": payload.get("timings", {}).get("extraction_ms"),
        "ocr_engines": selected_engines,
        "nutrition_basis": payload.get("nutrition", {}).get("basis"),
        "nutrition_rows": len(payload.get("nutrition", {}).get("table_rows", [])),
        "ingredient_text": payload.get("ingredients", {}).get("raw_text"),
        "allergen_text": payload.get("ingredients", {}).get("allergen_text"),
        "warnings": payload.get("warnings", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--container", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    stop = threading.Event()
    resource_samples: list[dict[str, Any]] = []
    monitor = threading.Thread(
        target=_sample_container,
        args=(args.container, stop, resource_samples),
        daemon=True,
    )
    monitor.start()
    scans: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=180) as client:
            for index in range(args.iterations):
                started = time.perf_counter()
                with args.image.open("rb") as image:
                    response = client.post(
                        args.endpoint,
                        headers={"Authorization": f"Bearer {args.token}"},
                        data={
                            "input_kind": "PRODUCT",
                            "view_types": "GENERAL",
                            "languages": "en",
                            "trace_id": f"local-owner-benchmark-{index + 1}",
                        },
                        files={"files": (args.image.name, image, "image/jpeg")},
                    )
                elapsed_ms = (time.perf_counter() - started) * 1000
                response.raise_for_status()
                scans.append(_summary(response.json(), elapsed_ms, response.status_code))
    finally:
        stop.set()
        monitor.join(timeout=3)

    warm = [float(scan["request_ms"]) for scan in scans[1:]] or [float(scans[0]["request_ms"])]
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": "Owner-controlled loopback CPU worker feasibility; not production routing.",
        "container": args.container,
        "iterations": len(scans),
        "cold_request_ms": scans[0]["request_ms"],
        "warm_request_ms": {
            "p50": statistics.median(warm),
            "p95": _percentile(warm, 0.95),
        },
        "resources": {
            "sample_count": len(resource_samples),
            "peak_cpu_percent": max(
                (sample["cpu_percent"] for sample in resource_samples), default=None
            ),
            "peak_memory_bytes": max(
                (sample["memory_bytes"] for sample in resource_samples), default=None
            ),
            "peak_pids": max((sample["pids"] for sample in resource_samples), default=None),
        },
        "scans": scans,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
