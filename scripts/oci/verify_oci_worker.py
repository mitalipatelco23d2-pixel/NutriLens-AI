"""Run the governed milk-fixture acceptance directly against the OCI worker.

This is deployment validation, not product-specific production logic. The
server-to-server token is read only from AI_WORKER_TOKEN and is never emitted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import time
from pathlib import Path
from typing import Any

import httpx


def _normalized(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def _contains(values: list[object], expected: str) -> bool:
    needle = _normalized(expected)
    return any(needle in _normalized(value) for value in values)


def _acceptance(result: dict[str, Any]) -> dict[str, bool]:
    nutrition = dict(result.get("nutrition") or {})
    ingredients = dict(result.get("ingredients") or {})
    regions = list(result.get("regions") or [])
    models = list(result.get("models") or [])
    warnings = [str(value) for value in result.get("warnings") or []]
    dates = list(result.get("date_candidates") or [])
    products = [value.get("value", "") for value in result.get("product_name_candidates") or []]
    brands = [value.get("value", "") for value in result.get("brand_candidates") or []]
    rows = list(nutrition.get("table_rows") or [])
    row_names = [row.get("canonical_label") or row.get("label") or "" for row in rows]
    paddle_success = any(
        attempt.get("engine") == "PaddleOCR" and attempt.get("status") == "SUCCESS"
        for ocr_result in (result.get("ocr_results") or {}).values()
        for attempt in ocr_result.get("attempts") or []
    )
    custom_region = any(
        region.get("region_type") == "nutrition_table" and region.get("method") == "CUSTOM_MODEL"
        for region in regions
    )
    custom_model = any(
        model.get("loaded") is True and model.get("training_status") == "CUSTOM_FINE_TUNED"
        for model in models
    )
    warning_text = " ".join(warnings).casefold()
    date_text = [_normalized(candidate.get("raw_text", "")) for candidate in dates]

    return {
        "completed": result.get("status") in {"COMPLETED", "COMPLETED_WITH_WARNINGS"},
        "product_low_fat_cow_milk": _contains(products, "Low Fat Cow Milk"),
        "brand_country_delight": _contains(brands, "Country Delight"),
        "basis_per_100_ml": nutrition.get("basis") == "PER_100_ML",
        "serving_250_ml": _normalized(nutrition.get("serving_size_value")) in {"250", "250 0"}
        and _normalized(nutrition.get("serving_size_unit")) == "ml",
        "at_least_11_nutrition_rows": len(rows) >= 11,
        "total_fat": _contains(row_names, "total fat"),
        "saturated_fat": _contains(row_names, "saturated fat"),
        "sodium": _contains(row_names, "sodium"),
        "ingredient_pasteurized_cow_milk": "pasteurized cow milk"
        in _normalized(ingredients.get("raw_text", "")),
        "explicit_milk_allergen": "milk" in _normalized(ingredients.get("allergen_text", "")),
        "paddleocr_success": paddle_success,
        "custom_yolo_region": custom_region,
        "custom_yolo_loaded": custom_model,
        "no_contradictory_model_warning": not (
            custom_region
            and ("model_not_cached" in warning_text or "yolo_unavailable" in warning_text)
        ),
        "no_decimal_nutrient_date": not any(value in {"0 9", "0 99"} for value in date_text),
        "images_not_retained": result.get("images_retained") is False,
    }


def _run_once(worker_url: str, token: str, image: Path, timeout: float) -> dict[str, Any]:
    start = time.perf_counter()
    with (
        image.open("rb") as fixture,
        httpx.Client(timeout=httpx.Timeout(timeout, connect=10), follow_redirects=False) as client,
    ):
        response = client.post(
            f"{worker_url.rstrip('/')}/internal/r3/scan",
            headers={"Authorization": f"Bearer {token}"},
            files={"files": (image.name, fixture, "image/jpeg")},
            data={
                "input_kind": "PRODUCT",
                "view_types": "GENERAL",
                "languages": "en",
                "trace_id": f"oci-acceptance-{time.time_ns()}",
            },
        )
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.raise_for_status()
    payload = response.json()
    checks = _acceptance(payload)
    return {
        "http_status": response.status_code,
        "elapsed_ms": round(elapsed_ms, 2),
        "pipeline_timings": payload.get("timings"),
        "scan_status": payload.get("status"),
        "checks": checks,
        "passed": all(checks.values()),
        "warnings": payload.get("warnings") or [],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-url", required=True)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=2, choices=range(1, 6))
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    token = os.getenv("AI_WORKER_TOKEN", "")
    if not token:
        raise SystemExit("AI_WORKER_TOKEN must be set in the local environment")
    if not args.image.is_file():
        raise SystemExit(f"Fixture does not exist: {args.image}")
    if not args.worker_url.startswith("https://") and not args.worker_url.startswith(
        "http://127.0.0.1:"
    ):
        raise SystemExit("Worker URL must use HTTPS, except for loopback VM validation")

    with httpx.Client(timeout=10, follow_redirects=False) as client:
        health = client.get(f"{args.worker_url.rstrip('/')}/health")
    health.raise_for_status()
    if health.json().get("status") != "ok":
        raise SystemExit("OCI worker health endpoint did not return status=ok")

    runs = [
        _run_once(args.worker_url, token, args.image, args.timeout_seconds)
        for _ in range(args.runs)
    ]
    report = {
        "provider": "oci",
        "fixture": args.image.name,
        "run_count": len(runs),
        "cold_or_first_ms": runs[0]["elapsed_ms"],
        "warm_ms": [run["elapsed_ms"] for run in runs[1:]],
        "p50_ms": round(statistics.median(run["elapsed_ms"] for run in runs), 2),
        "runs": runs,
        "passed": all(run["passed"] for run in runs),
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
