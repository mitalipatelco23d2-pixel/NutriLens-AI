"""Acquire and build a deterministic FAOSTAT Food Balances country bundle."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import urllib.request
from pathlib import Path
from typing import Any

SOURCE_URL = (
    "https://api.data.apps.fao.org/api/v2/bigquery?download=true&item_code=2901&"
    "sql_url=https%3A%2F%2Fdata.apps.fao.org%2Fcatalog%2Fdataset%2F"
    "5c00a4e6-0ec8-4191-a0c0-a7cd5fda3674%2Fresource%2F"
    "91b9d43c-55c4-4a2a-9b25-78f2fabba28b%2Fdownload%2F"
    "fct-fbs-food-balances.query.sql"
)
CATALOG_URL = "https://data.fao.org/catalog/iso/2f264bb6-1238-459a-bf8b-0e2d0a16804a"
TERMS_URL = "https://www.fao.org/contact-us/terms/db-terms-of-use/en/"
ACCESS_DATE = "2026-08-27"
REVISION_DATE = "2025-10-16"
INDICATORS = {
    "food_supply_kcal_capita_day_kcal_capita_day": (
        "food_supply_kcal_per_capita_day",
        "kcal/capita/day",
    ),
    "protein_supply_quantity_g_capita_day_g_capita_day": (
        "protein_supply_g_per_capita_day",
        "g/capita/day",
    ),
    "fat_supply_quantity_g_capita_day_g_capita_day": (
        "fat_supply_g_per_capita_day",
        "g/capita/day",
    ),
}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _gzip(payload: bytes) -> bytes:
    return gzip.compress(payload, compresslevel=9, mtime=0)


def _download() -> bytes:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "NutriLens-R12/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310 - fixed HTTPS URL.
        return bytes(response.read())


def _canonical_rows(payload: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = payload.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError("FAOSTAT response has no header.")
    rows = [dict(row) for row in reader]
    rows = [row for row in rows if row.get("item_code") == "2901"]
    rows.sort(key=lambda row: (int(row["m49_code"]), int(row["year"])))
    if len(rows) < 2_000:
        raise ValueError(f"Expected at least 2,000 country-year rows, found {len(rows)}.")
    if max(int(row["year"]) for row in rows) != 2023:
        raise ValueError("Pinned FAOSTAT source no longer ends at expected year 2023.")
    return list(reader.fieldnames), rows


def _csv_bytes(fieldnames: list[str], rows: list[dict[str, str]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def build_bundle(raw_csv: bytes) -> dict[str, Any]:
    _, rows = _canonical_rows(raw_csv)
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for row in rows:
        m49 = str(row["m49_code"]).zfill(3)
        year = int(row["year"])
        identity = (m49, year)
        if identity in seen:
            raise ValueError(f"Duplicate country-year row: {identity}")
        seen.add(identity)
        values: dict[str, float | None] = {}
        flags: dict[str, str] = {}
        for source_field, (indicator, _) in INDICATORS.items():
            raw_value = row.get(source_field, "").strip()
            values[indicator] = float(raw_value) if raw_value else None
            flag = row.get(f"{source_field}_flag", "").strip()
            if flag:
                flags[indicator] = flag
        records.append(
            {
                "m49_code": m49,
                "country": row["country_name_en"].strip(),
                "year": year,
                "values": values,
                "quality_flags": flags,
            }
        )
    countries = {record["m49_code"] for record in records}
    if len(countries) < 150:
        raise ValueError(f"Expected broad national coverage, found {len(countries)} countries.")
    return {
        "schema_version": "0.1.0",
        "method": "DIRECT_FAOSTAT_FBS_COUNTRY_INDICATOR_COMPARISON_V1",
        "source": {
            "dataset": "FAOSTAT Food Balances: Grand Total",
            "provider": "Food and Agriculture Organization of the United Nations",
            "catalog_url": CATALOG_URL,
            "download_url": SOURCE_URL,
            "terms_url": TERMS_URL,
            "license": "CC BY 4.0 subject to FAO Statistical Database Terms of Use",
            "revision_date": REVISION_DATE,
            "access_date": ACCESS_DATE,
            "raw_csv_sha256": _sha256(raw_csv),
            "citation": (
                "FAO. 2025. FAOSTAT: Food Balances. Accessed on 27 August 2026. "
                f"{CATALOG_URL} Licence: CC-BY-4.0."
            ),
        },
        "indicators": [{"id": indicator, "unit": unit} for indicator, unit in INDICATORS.values()],
        "limitations": [
            "Food balance supply availability is not measured individual intake or diet quality.",
            "Country sources, estimation, imputation and reporting methods affect comparability.",
            "Values are displayed descriptively; NutriLens does not rank country health.",
            "The pinned release covers 2010 through 2023 and may be revised by FAO.",
        ],
        "records": records,
    }


def _write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_gzip(payload))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--raw",
        type=Path,
        default=Path("data/raw/population/faostat-fbs-grand-total-v2025-10-16.csv.gz"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/runtime/faostat-country-indicators-v0.1.0.json.gz"),
    )
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.refresh:
        fieldnames, rows = _canonical_rows(_download())
        _write(args.raw, _csv_bytes(fieldnames, rows))
    if not args.raw.exists():
        raise SystemExit(f"Missing raw bundle: {args.raw}. Run with --refresh.")
    raw_csv = gzip.decompress(args.raw.read_bytes())
    bundle = build_bundle(raw_csv)
    encoded = json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    expected = _gzip(encoded)
    if args.check:
        # Compare canonical decompressed bytes. Gzip implementations may encode
        # an OS marker differently on Windows and Linux despite identical data.
        if not args.output.exists() or gzip.decompress(args.output.read_bytes()) != encoded:
            raise SystemExit("FAOSTAT runtime bundle is missing or stale.")
        print(
            json.dumps(
                {
                    "countries": len({item["m49_code"] for item in bundle["records"]}),
                    "records": len(bundle["records"]),
                    "sha256": _sha256(expected),
                    "status": "PASS",
                },
                sort_keys=True,
            )
        )
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(expected)
    print(
        json.dumps(
            {
                "countries": len({item["m49_code"] for item in bundle["records"]}),
                "output": args.output.as_posix(),
                "records": len(bundle["records"]),
                "sha256": _sha256(expected),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
