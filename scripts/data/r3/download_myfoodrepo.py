"""Check the official MyFoodRepo v2.1 access route without bypassing its login gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import requests

from scripts.data.r3.common import REPO_ROOT, USER_AGENT, utc_now, write_json

SOURCE_URL = "https://www.aicrowd.com/challenges/food-recognition-benchmark-2022/dataset_files"


def check_access(destination: Path) -> dict[str, object]:
    response = requests.get(
        SOURCE_URL,
        headers={"User-Agent": USER_AGENT},
        allow_redirects=True,
        timeout=30,
    )
    gated = "participants/sign_in" in response.url
    status = {
        "checked_at": utc_now(),
        "dataset": "Food Recognition Benchmark 2022 / MyFoodRepo v2.1",
        "final_url": response.url,
        "http_status": response.status_code,
        "license": "CC-BY-4.0 per official AIcrowd challenge rules",
        "source_url": SOURCE_URL,
        "status": "MANUAL_ACCESS_REQUIRED" if gated else "OFFICIAL_ROUTE_ACCESSIBLE",
        "terms": "Do not bypass AIcrowd login or acceptance requirements.",
    }
    destination.mkdir(parents=True, exist_ok=True)
    write_json(destination / "access-status.json", status)
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destination",
        type=Path,
        default=REPO_ROOT / "data/external/r3/myfoodrepo",
    )
    args = parser.parse_args()
    print(json.dumps(check_access(args.destination), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
