from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from time import monotonic

import psycopg
import redis
from neo4j import GraphDatabase
from pymongo import MongoClient

from backend.settings import Settings

ServiceState = str
_HEALTH_TTL_SECONDS = 10.0
_health_lock = Lock()
_health_cached_at = 0.0
_health_cache: dict[str, ServiceState] | None = None


def _check(check: Callable[[], None]) -> ServiceState:
    try:
        check()
        return "healthy"
    except Exception:
        return "unavailable"


def check_postgres(config: Settings) -> ServiceState:
    def connect() -> None:
        with (
            psycopg.connect(config.postgres_url, connect_timeout=2) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT 1")

    return _check(connect)


def check_mongodb(config: Settings) -> ServiceState:
    def connect() -> None:
        with MongoClient[dict[str, object]](
            config.mongodb_url, serverSelectionTimeoutMS=2000
        ) as client:
            client.admin.command("ping")

    return _check(connect)


def check_neo4j(config: Settings) -> ServiceState:
    def connect() -> None:
        with GraphDatabase.driver(
            config.neo4j_url,
            auth=(config.neo4j_user, config.neo4j_password),
            connection_timeout=2,
        ) as driver:
            driver.verify_connectivity()

    return _check(connect)


def check_redis(config: Settings) -> ServiceState:
    def connect() -> None:
        client = redis.Redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2)
        client.ping()
        client.close()

    return _check(connect)


def collect_service_health(config: Settings) -> dict[str, ServiceState]:
    """Return a short-lived, coalesced readiness snapshot."""
    global _health_cache, _health_cached_at
    now = monotonic()
    with _health_lock:
        if _health_cache is not None and now - _health_cached_at < _HEALTH_TTL_SECONDS:
            return dict(_health_cache)
        checks = {
            "postgres": check_postgres,
            "mongodb": check_mongodb,
            "neo4j": check_neo4j,
            "redis": check_redis,
        }
        with ThreadPoolExecutor(max_workers=len(checks)) as executor:
            futures = {name: executor.submit(check, config) for name, check in checks.items()}
            snapshot = {"api": "healthy"}
            snapshot.update({name: future.result() for name, future in futures.items()})
        _health_cache = snapshot
        _health_cached_at = monotonic()
        return dict(snapshot)


def clear_service_health_cache() -> None:
    global _health_cache, _health_cached_at
    with _health_lock:
        _health_cache = None
        _health_cached_at = 0.0
