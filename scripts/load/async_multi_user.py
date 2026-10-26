"""Owner-isolated asynchronous scan validation against a running NutriLens API.

The API process and this script must share POSTGRES_URL, REDIS_URL, and JWT_SECRET.
The script never prints credentials or image bytes. It is intended for an isolated
test database whose API dispatcher targets the deployed private AI worker.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import httpx
import psycopg
import redis

from backend.auth import create_session_token, user_store
from backend.settings import settings

_WAKE_QUEUE = "nutrilens:scan-jobs:wake:v1"
_TERMINAL = {"COMPLETE", "FAILED", "TIMED_OUT"}


@dataclass(frozen=True)
class OwnerFixture:
    index: int
    user_id: str
    token: str
    image_path: Path
    idempotency_key: str


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 2)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _elapsed_ms(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return round((end - start).total_seconds() * 1000, 2)


def _seed_owners(images: list[Path], run_id: str) -> list[OwnerFixture]:
    fixtures: list[OwnerFixture] = []
    for index, image_path in enumerate(images, start=1):
        user = user_store.upsert_google_user(
            {
                "sub": f"load-{run_id}-{index}",
                "email": f"load-{run_id}-{index}@fixture.invalid",
                "email_verified": True,
                "name": f"Load owner {index}",
            }
        )
        token, _ = create_session_token(user)
        fixtures.append(
            OwnerFixture(
                index=index,
                user_id=user.id,
                token=token,
                image_path=image_path,
                idempotency_key=f"async-load-{run_id}-{index}",
            )
        )
    return fixtures


def _seed_intruder(image_path: Path, run_id: str) -> OwnerFixture:
    user = user_store.upsert_google_user(
        {
            "sub": f"load-{run_id}-intruder",
            "email": f"load-{run_id}-intruder@fixture.invalid",
            "email_verified": True,
            "name": "Load isolation intruder",
        }
    )
    token, _ = create_session_token(user)
    return OwnerFixture(
        index=0,
        user_id=user.id,
        token=token,
        image_path=image_path,
        idempotency_key=f"async-load-{run_id}-intruder",
    )


async def _submit(
    client: httpx.AsyncClient, base_url: str, fixture: OwnerFixture
) -> tuple[dict[str, Any], float, int]:
    started = perf_counter()
    response = await client.post(
        f"{base_url}/api/v1/scan/jobs/product",
        headers={
            "Authorization": f"Bearer {fixture.token}",
            "Idempotency-Key": fixture.idempotency_key,
        },
        data={"view_types": "GENERAL", "languages": "en"},
        files={
            "files": (
                fixture.image_path.name,
                fixture.image_path.read_bytes(),
                "image/jpeg",
            )
        },
    )
    elapsed = round((perf_counter() - started) * 1000, 2)
    response.raise_for_status()
    return response.json(), elapsed, response.status_code


async def _get_job(
    client: httpx.AsyncClient, base_url: str, fixture: OwnerFixture, job_id: str
) -> httpx.Response:
    while True:
        response = await client.get(
            f"{base_url}/api/v1/scan/jobs/{job_id}",
            headers={"Authorization": f"Bearer {fixture.token}"},
        )
        if response.status_code != 429:
            return response
        await asyncio.sleep(float(response.headers.get("Retry-After", "5")))


async def _poll_jobs(
    client: httpx.AsyncClient,
    base_url: str,
    fixtures: list[OwnerFixture],
    accepted: list[dict[str, Any]],
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    latest = list(accepted)
    while True:
        if all(str(item["status"]) in _TERMINAL for item in latest):
            return latest
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("Asynchronous jobs did not reach terminal state before timeout.")
        await asyncio.sleep(5)
        responses = await asyncio.gather(
            *(
                _get_job(client, base_url, fixture, str(job["job_id"]))
                for fixture, job in zip(fixtures, accepted, strict=True)
            )
        )
        for response in responses:
            response.raise_for_status()
        latest = [response.json() for response in responses]


def _database_evidence(job_ids: list[str], user_ids: list[str]) -> dict[str, Any]:
    with psycopg.connect(settings.postgres_url) as connection:
        jobs = connection.execute(
            """
            SELECT id, user_id, status, attempts, error_code,
                   created_at, started_at, completed_at
            FROM scan_jobs WHERE id = ANY(%s) ORDER BY created_at
            """,
            (job_ids,),
        ).fetchall()
        usage = connection.execute(
            """
            SELECT user_id, request_count FROM scan_usage
            WHERE user_id = ANY(%s) AND period_start = %s ORDER BY user_id
            """,
            (user_ids, date.today().replace(day=1)),
        ).fetchall()
        retained_images = connection.execute(
            "SELECT count(*) FROM scan_job_images WHERE job_id = ANY(%s)", (job_ids,)
        ).fetchone()
    job_rows = [
        {
            "job_id": str(row[0]),
            "owner_id": str(row[1]),
            "status": str(row[2]),
            "attempts": int(row[3]),
            "error_code": str(row[4]) if row[4] else None,
            "queue_delay_ms": _elapsed_ms(row[5], row[6]),
            "inference_latency_ms": _elapsed_ms(row[6], row[7]),
            "durable_end_to_end_ms": _elapsed_ms(row[5], row[7]),
        }
        for row in jobs
    ]
    return {
        "jobs": job_rows,
        "quota_by_owner": {str(row[0]): int(row[1]) for row in usage},
        "retained_input_images": int(retained_images[0]) if retained_images else None,
    }


def _wake_evidence(job_ids: list[str]) -> dict[str, Any]:
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        positions = {job_id: client.lpos(_WAKE_QUEUE, job_id) for job_id in job_ids}
    finally:
        client.close()
    return {
        "queue": _WAKE_QUEUE,
        "observed_job_ids": sum(position is not None for position in positions.values()),
        "expected_job_ids": len(job_ids),
    }


def _result_summary(job: dict[str, Any]) -> dict[str, Any]:
    result = job.get("result") or {}
    nutrition = result.get("nutrition") or {}
    ingredients = result.get("ingredients") or {}
    models = result.get("models") or []
    ocr_results = result.get("ocr_results") or {}
    return {
        "job_id": job.get("job_id"),
        "scan_id": result.get("scan_id"),
        "result_status": result.get("status"),
        "nutrition_basis": nutrition.get("basis"),
        "nutrition_rows": len(nutrition.get("table_rows") or []),
        "allergen_text": ingredients.get("allergen_text", ""),
        "ocr_engines": sorted(
            {
                str(item.get("selected_engine"))
                for item in ocr_results.values()
                if isinstance(item, dict) and item.get("selected_engine")
            }
        ),
        "loaded_models": [
            {
                "name": item.get("model_name"),
                "device": item.get("device"),
                "training_status": item.get("training_status"),
            }
            for item in models
            if item.get("loaded")
        ],
        "worker_total_ms": (result.get("timings") or {}).get("total_ms"),
        "warnings": result.get("warnings") or [],
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    image_paths = [Path(value).resolve() for value in args.image]
    missing = [str(path) for path in image_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing fixture images: {missing}")
    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    fixtures = _seed_owners(image_paths, run_id)
    intruder = fixtures[1] if len(fixtures) > 1 else _seed_intruder(image_paths[0], run_id)
    base_url = args.base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=httpx.Timeout(args.request_timeout)) as client:
        submissions = await asyncio.gather(
            *(_submit(client, base_url, fixture) for fixture in fixtures)
        )
        accepted = [item[0] for item in submissions]
        acknowledgement_ms = [item[1] for item in submissions]
        statuses = [item[2] for item in submissions]
        job_ids = [str(item["job_id"]) for item in accepted]

        duplicate, duplicate_ms, duplicate_status = await _submit(client, base_url, fixtures[0])
        cross_owner = await _get_job(client, base_url, intruder, job_ids[0])
        terminal = await _poll_jobs(client, base_url, fixtures, accepted, args.timeout_seconds)

    database = _database_evidence(job_ids, [fixture.user_id for fixture in fixtures])
    queue_delays = [
        row["queue_delay_ms"] for row in database["jobs"] if row["queue_delay_ms"] is not None
    ]
    inference = [
        row["inference_latency_ms"]
        for row in database["jobs"]
        if row["inference_latency_ms"] is not None
    ]
    end_to_end = [
        row["durable_end_to_end_ms"]
        for row in database["jobs"]
        if row["durable_end_to_end_ms"] is not None
    ]
    final_statuses = [str(item["status"]) for item in terminal]
    attempts = [int(row["attempts"]) for row in database["jobs"]]
    quota = database["quota_by_owner"]
    expected_quota = {
        str(row["owner_id"]): 1 if row["status"] == "COMPLETE" else 0 for row in database["jobs"]
    }
    return {
        "run_id": run_id,
        "test_boundary": (
            "isolated signed owners -> real API -> durable dispatcher -> configured worker"
        ),
        "owner_count": len(fixtures),
        "accepted_http_202": sum(status == 202 for status in statuses),
        "completed": final_statuses.count("COMPLETE"),
        "failed": final_statuses.count("FAILED"),
        "timed_out": final_statuses.count("TIMED_OUT"),
        "acknowledgement_ms": {
            "p50": _percentile(acknowledgement_ms, 0.5),
            "p95": _percentile(acknowledgement_ms, 0.95),
            "max": round(max(acknowledgement_ms), 2),
        },
        "queue_delay_ms": {
            "p50": _percentile(queue_delays, 0.5),
            "p95": _percentile(queue_delays, 0.95),
            "max": round(max(queue_delays), 2) if queue_delays else None,
        },
        "inference_latency_ms": {
            "p50": _percentile(inference, 0.5),
            "p95": _percentile(inference, 0.95),
            "max": round(max(inference), 2) if inference else None,
        },
        "durable_end_to_end_ms": {
            "p50": _percentile(end_to_end, 0.5),
            "p95": _percentile(end_to_end, 0.95),
            "max": round(max(end_to_end), 2) if end_to_end else None,
        },
        "idempotency": {
            "http_status": duplicate_status,
            "same_job_id": duplicate.get("job_id") == job_ids[0],
            "duplicate_acknowledgement_ms": duplicate_ms,
        },
        "cross_owner_access": {
            "http_status": cross_owner.status_code,
            "denied": cross_owner.status_code == 404,
        },
        "quota": {
            "accepted_reservations": len(fixtures),
            "matches_terminal_outcome": all(
                quota.get(owner_id, 0) == expected for owner_id, expected in expected_quota.items()
            ),
            "reservation_counts": sorted(quota.values()),
        },
        "queue_wakeup": _wake_evidence(job_ids),
        "retries": sum(max(value - 1, 0) for value in attempts),
        "attempts": attempts,
        "failure_errors": sorted(
            str(row["error_code"]) for row in database["jobs"] if row["error_code"]
        ),
        "retained_input_images": database["retained_input_images"],
        "results": [_result_summary(item) for item in terminal],
        "fixtures": [
            {"owner_index": fixture.index, "image": fixture.image_path.name} for fixture in fixtures
        ],
        "job_ids": job_ids,
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8011")
    parser.add_argument("--image", action="append", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=900)
    parser.add_argument("--request-timeout", type=float, default=30)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = _arguments()
    report = asyncio.run(_run(args))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
